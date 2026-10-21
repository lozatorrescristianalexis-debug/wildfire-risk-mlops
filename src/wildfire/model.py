from __future__ import annotations

import json
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
import seaborn as sns
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from .features import GRID_FEATURES
from .geography import region_at, region_catalog

REQUIRED_COLUMNS = [
    "date",
    "label",
    "data_source",
    "fire_count",
    "cell_id",
    *GRID_FEATURES,
]
MODEL_NAMES = ("logistic", "random_forest", "hist_gradient_boosting", "xgboost")


class CalibratedHotspotModel:
    """Apply temporal out-of-fold Platt calibration to a fitted classifier."""

    def __init__(self, base_model, calibrator):
        self.base_model = base_model
        self.calibrator = calibrator
        self.classes_ = np.array([0, 1])

    def predict_proba(self, features):
        raw = self.base_model.predict_proba(features)[:, 1]
        positive = self.calibrator.predict_proba(raw.reshape(-1, 1))[:, 1]
        return np.column_stack((1 - positive, positive))

    def predict(self, features):
        return (self.predict_proba(features)[:, 1] >= 0.5).astype(int)


def load_training_data(path: Path, *, allow_demo: bool = False) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}. Run `make data` to fetch real data.")
    frame = pd.read_csv(path)
    sources = set(frame["data_source"].dropna().unique()) if "data_source" in frame else set()
    if sources == {"synthetic_demo"} and not allow_demo:
        raise ValueError(
            "Synthetic demo data cannot be used for final training or report metrics."
        )
    if allow_demo and sources == {"synthetic_demo"}:
        demo_columns = {
            "date",
            "label",
            "data_source",
            "fire_count",
            "temperature_2m_max",
            "relative_humidity_2m_mean",
            "precipitation_sum",
            "wind_speed_10m_max",
            "latitude",
            "longitude",
        }
        missing_demo = sorted(demo_columns - set(frame.columns))
        if missing_demo:
            raise ValueError(f"Synthetic test data is missing: {', '.join(missing_demo)}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        return frame.sort_values("date").reset_index(drop=True)
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Dataset is missing required column(s): {', '.join(missing)}")
    if frame.empty:
        raise ValueError("Dataset is empty.")
    if sources == {"synthetic_demo"} and not allow_demo:
        raise ValueError(
            "Synthetic demo data cannot be used for final training or report metrics."
        )
    if sources != {"firms_open_meteo"} and not (allow_demo and sources == {"synthetic_demo"}):
        raise ValueError("Training requires a dataset marked firms_open_meteo.")
    frame = frame[REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("Dataset contains invalid dates.")
    if frame.duplicated(["date", "cell_id"]).any():
        raise ValueError("Dataset must contain at most one row per date and grid cell.")
    for column in ["label", "fire_count", *GRID_FEATURES]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"Dataset contains missing or non-numeric values in {column}.")
    if (frame["fire_count"] < 0).any() or (frame["fire_count"] % 1 != 0).any():
        raise ValueError("fire_count must contain non-negative integer values.")
    if not set(frame["label"].unique()).issubset({0, 1}):
        raise ValueError("label must contain only binary values 0 and 1.")
    if not frame["label"].eq(frame["fire_count"].gt(0).astype(int)).all():
        raise ValueError("label must match whether fire_count is greater than zero.")
    return frame.sort_values(["date", "cell_id"]).reset_index(drop=True)


def _temporal_splits(frame: pd.DataFrame, n_splits: int) -> list[tuple[np.ndarray, np.ndarray]]:
    dates = np.array(sorted(frame["date"].unique()))
    if len(dates) <= n_splits:
        raise ValueError("Not enough distinct dates for temporal cross-validation.")
    splitter = TimeSeriesSplit(n_splits=n_splits)
    splits = []
    for train_indices, validation_indices in splitter.split(dates):
        train_dates = dates[train_indices]
        validation_dates = dates[validation_indices]
        train_rows = np.flatnonzero(frame["date"].isin(train_dates).to_numpy())
        validation_rows = np.flatnonzero(frame["date"].isin(validation_dates).to_numpy())
        splits.append((train_rows, validation_rows))
    return splits


def _make_estimator(
    name: str,
    params: dict,
    positive_weight: float,
    *,
    seed: int = 42,
):
    if name == "logistic":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=params["C"],
                class_weight="balanced",
                max_iter=1000,
                solver="lbfgs",
                random_state=seed,
            ),
        )
    if name == "random_forest":
        return RandomForestClassifier(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            min_samples_leaf=params["min_samples_leaf"],
            max_features=params["max_features"],
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=-1,
        )
    if name == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(
            max_iter=params["max_iter"],
            learning_rate=params["learning_rate"],
            max_leaf_nodes=params["max_leaf_nodes"],
            l2_regularization=params["l2_regularization"],
            class_weight="balanced",
            random_state=seed,
        )
    if name == "xgboost":
        return XGBClassifier(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            learning_rate=params["learning_rate"],
            subsample=params["subsample"],
            colsample_bytree=params["colsample_bytree"],
            reg_lambda=params["reg_lambda"],
            scale_pos_weight=positive_weight,
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            n_jobs=4,
            random_state=seed,
            verbosity=0,
        )
    raise ValueError(f"Unsupported model: {name}")


def _suggest_params(trial: optuna.Trial, name: str) -> dict:
    if name == "logistic":
        return {"C": trial.suggest_float("C", 1e-3, 100, log=True)}
    if name == "random_forest":
        return {
            "n_estimators": trial.suggest_int("n_estimators", 100, 300, step=50),
            "max_depth": trial.suggest_int("max_depth", 4, 20),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 20),
            "max_features": trial.suggest_categorical("max_features", ["sqrt", 0.5, 1.0]),
        }
    if name == "hist_gradient_boosting":
        return {
            "max_iter": trial.suggest_int("max_iter", 100, 300, step=50),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "max_leaf_nodes": trial.suggest_int("max_leaf_nodes", 15, 63, step=12),
            "l2_regularization": trial.suggest_float("l2_regularization", 1e-4, 10, log=True),
        }
    if name == "xgboost":
        return {
            "n_estimators": trial.suggest_int("n_estimators", 100, 300, step=50),
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.2, log=True),
            "subsample": trial.suggest_float("subsample", 0.7, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.7, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 20, log=True),
        }
    raise ValueError(f"Unsupported model: {name}")


def _positive_weight(labels: pd.Series) -> float:
    positives = int(labels.sum())
    return max(1.0, (len(labels) - positives) / max(positives, 1))


def _choose_threshold(labels: np.ndarray, probabilities: np.ndarray) -> tuple[float, float]:
    precision, recall, thresholds = precision_recall_curve(labels, probabilities)
    if len(thresholds) == 0:
        return 0.5, float(f1_score(labels, probabilities >= 0.5, zero_division=0))
    f1_values = 2 * precision[:-1] * recall[:-1] / np.maximum(
        precision[:-1] + recall[:-1], 1e-12
    )
    best = np.flatnonzero(f1_values == f1_values.max())
    best_index = int(best[-1])
    return float(thresholds[best_index]), float(f1_values[best_index])


def _evaluate(labels: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict:
    predictions = (probabilities >= threshold).astype(int)
    return {
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "threshold": float(threshold),
        "confusion_matrix": confusion_matrix(labels, predictions, labels=[0, 1]).tolist(),
    }


def _regional_holdout(test: pd.DataFrame, probabilities: np.ndarray, threshold: float) -> dict:
    """Report geographic subsets of the untouched temporal holdout by cell center."""
    centers = test[["cell_id", "latitude", "longitude"]].drop_duplicates("cell_id")
    cell_regions = {
        row.cell_id: region_at(float(row.latitude), float(row.longitude))
        for row in centers.itertuples()
    }
    labels = test["label"].to_numpy(dtype=int)
    region_ids = test["cell_id"].map(cell_regions).to_numpy()
    summary = {}
    for region in region_catalog()[1:]:
        mask = region_ids == region["id"]
        regional_labels = labels[mask]
        result = {
            "name": region["name"],
            "test_rows": int(mask.sum()),
            "positive_rows": int(regional_labels.sum()),
            "negative_rows": int(len(regional_labels) - regional_labels.sum()),
            "grid_cells": int(test.loc[mask, "cell_id"].nunique()),
        }
        if len(regional_labels) and len(np.unique(regional_labels)) == 2:
            result["metrics"] = _evaluate(regional_labels, probabilities[mask], threshold)
        else:
            result["metrics"] = None
        summary[region["id"]] = result
    return summary


def _save_figures(
    frame: pd.DataFrame,
    results: dict,
    best_name: str,
    best_model,
    train_x: pd.DataFrame,
    train_y: pd.Series,
    test_x: pd.DataFrame,
    test_y: pd.Series,
    threshold: float,
    figures_dir: Path,
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    monthly = frame.assign(month=frame["date"].dt.to_period("M").astype(str)).groupby(
        "month", as_index=False
    ).agg(positive_grid_days=("label", "sum"), sampled_grid_days=("label", "size"))
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    sns.barplot(monthly, x="month", y="positive_grid_days", color="#d95f02", ax=axes[0])
    sns.lineplot(monthly, x="month", y="sampled_grid_days", color="#1b9e77", ax=axes[1])
    axes[0].set_title("Detecciones por celda-dia, agrupadas por mes")
    axes[1].set_title("Ejemplos celda-dia (solo fechas con detecciones en el area)")
    axes[0].tick_params(axis="x", rotation=70)
    axes[1].tick_params(axis="x", rotation=70)
    fig.tight_layout()
    fig.savefig(figures_dir / "eda_real.png", dpi=160)
    plt.close(fig)

    comparison = pd.DataFrame(
        [
            {
                "model": name,
                "F1": result["test"]["f1"],
                "Precision": result["test"]["precision"],
                "Recall": result["test"]["recall"],
                "ROC-AUC": result["test"]["roc_auc"],
                "PR-AUC": result["test"]["pr_auc"],
            }
            for name, result in results.items()
        ]
    ).melt(id_vars="model", var_name="metric", value_name="score")
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(comparison, x="model", y="score", hue="metric", ax=ax)
    ax.set_ylim(0, 1)
    ax.set_title("Comparacion de modelos en el holdout temporal")
    ax.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    fig.savefig(figures_dir / "model_comparison_real.png", dpi=160)
    plt.close(fig)

    probabilities = results[best_name]["test_probabilities"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    false_positive_rate, true_positive_rate, _ = roc_curve(test_y, probabilities)
    axes[0].plot(false_positive_rate, true_positive_rate, label=f"ROC-AUC={results[best_name]['test']['roc_auc']:.3f}")
    axes[0].plot([0, 1], [0, 1], linestyle="--", color="grey")
    axes[0].set(xlabel="False positive rate", ylabel="True positive rate", title=f"ROC: {best_name}")
    axes[0].legend()
    precision, recall, _ = precision_recall_curve(test_y, probabilities)
    axes[1].plot(recall, precision, label=f"PR-AUC={results[best_name]['test']['pr_auc']:.3f}")
    axes[1].axvline(
        results[best_name]["test"]["recall"],
        linestyle="--",
        color="grey",
        label=f"recall at selected threshold={threshold:.3f}",
    )
    axes[1].set(xlabel="Recall", ylabel="Precision", title=f"Precision-recall: {best_name}")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(figures_dir / "roc_pr_real.png", dpi=160)
    plt.close(fig)

    predictions = (probabilities >= threshold).astype(int)
    fig, ax = plt.subplots(figsize=(6, 5))
    sns.heatmap(
        confusion_matrix(test_y, predictions, labels=[0, 1]),
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=["No detection", "Detection"],
        yticklabels=["No detection", "Detection"],
        ax=ax,
    )
    ax.set(xlabel="Predicted", ylabel="Observed", title=f"Holdout: {best_name}")
    fig.tight_layout()
    fig.savefig(figures_dir / "confusion_matrix_real.png", dpi=160)
    plt.close(fig)

    sample_size = min(5000, len(train_x))
    sample_x = train_x.sample(sample_size, random_state=42)
    sample_y = train_y.loc[sample_x.index]
    # Platt calibration is monotonic, so average-precision importance has the
    # same ranking and score when evaluated on the fitted base classifier.
    importance = permutation_importance(
        best_model.base_model,
        sample_x,
        sample_y,
        n_repeats=3,
        random_state=42,
        scoring="average_precision",
        n_jobs=1,
    )
    order = np.argsort(importance.importances_mean)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(
        np.array(GRID_FEATURES)[order],
        importance.importances_mean[order],
        xerr=importance.importances_std[order],
        color="#7570b3",
    )
    ax.set(xlabel="Decrease in training-sample average precision", title=f"Importancia por permutacion: {best_name}")
    fig.tight_layout()
    fig.savefig(figures_dir / "feature_importance_real.png", dpi=160)
    plt.close(fig)


def _train_demo_for_tests(frame: pd.DataFrame, model_path: Path, metrics_path: Path) -> dict:
    demo_features = [
        "temperature_2m_max",
        "relative_humidity_2m_mean",
        "precipitation_sum",
        "wind_speed_10m_max",
        "latitude",
        "longitude",
    ]
    split = int(len(frame) * 0.8)
    train, test = frame.iloc[:split], frame.iloc[split:]
    if split < 10 or train["label"].nunique() < 2 or test["label"].nunique() < 2:
        raise ValueError("Training requires both classes in the temporal train and test splits.")
    classifier = RandomForestClassifier(n_estimators=10, random_state=42)
    classifier.fit(train[demo_features], train["label"].astype(int))
    probabilities = classifier.predict_proba(test[demo_features])[:, 1]
    threshold, _ = _choose_threshold(test["label"].to_numpy(), probabilities)
    metrics = _evaluate(test["label"].to_numpy(), probabilities, threshold)
    metrics.update(
        {
            "data_source": "synthetic_demo",
            "rows": int(len(frame)),
            "test_rows": int(len(test)),
            "features": demo_features,
        }
    )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": classifier, "features": demo_features, "threshold": threshold}, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def train_model(
    input_path: Path,
    model_path: Path,
    metrics_path: Path,
    *,
    allow_demo: bool = False,
    n_trials: int = 10,
    figures_dir: Path | None = None,
    training_region: str | None = None,
    weather_sampling: str | None = None,
    model_names: tuple[str, ...] | None = None,
) -> dict:
    frame = load_training_data(input_path, allow_demo=allow_demo)
    if allow_demo:
        return _train_demo_for_tests(frame, model_path, metrics_path)
    if training_region not in {"madre_de_dios", "peru"}:
        raise ValueError("Real training requires training_region='madre_de_dios' or 'peru'.")
    if training_region == "peru" and (
        frame["latitude"].max() - frame["latitude"].min() < 12
        or frame["longitude"].max() - frame["longitude"].min() < 8
    ):
        raise ValueError("A Peru model requires training cells across the national extent.")
    model_names = model_names or (
        ("logistic", "hist_gradient_boosting", "xgboost")
        if training_region == "peru" else MODEL_NAMES
    )
    if not model_names or any(name not in MODEL_NAMES for name in model_names):
        raise ValueError("Training model_names must contain supported estimators.")
    unique_dates = np.array(sorted(frame["date"].unique()))
    if len(unique_dates) < 60 or (unique_dates[-1] - unique_dates[0]).days < 364:
        raise ValueError("Final training requires at least one year and 60 active dates of real data.")
    if frame["label"].nunique() != 2:
        raise ValueError("Real dataset must contain positive and negative grid-day labels.")
    split_index = int(len(unique_dates) * 0.8)
    train_dates, test_dates = unique_dates[:split_index], unique_dates[split_index:]
    train = frame.loc[frame["date"].isin(train_dates)].reset_index(drop=True)
    test = frame.loc[frame["date"].isin(test_dates)].reset_index(drop=True)
    if train["label"].nunique() != 2 or test["label"].nunique() != 2:
        raise ValueError("Temporal train and test partitions must each contain both classes.")
    splits = _temporal_splits(train, n_splits=3)
    train_x, train_y = train[GRID_FEATURES], train["label"].astype(int)
    test_x, test_y = test[GRID_FEATURES], test["label"].astype(int)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    results = {}
    fitted_models = {}

    for name in model_names:
        def objective(trial: optuna.Trial) -> float:
            params = _suggest_params(trial, name)
            fold_scores = []
            for train_index, validation_index in splits:
                x_fit, y_fit = train_x.iloc[train_index], train_y.iloc[train_index]
                x_valid, y_valid = train_x.iloc[validation_index], train_y.iloc[validation_index]
                if y_fit.nunique() < 2:
                    continue
                estimator = _make_estimator(name, params, _positive_weight(y_fit))
                estimator.fit(x_fit, y_fit)
                probabilities = estimator.predict_proba(x_valid)[:, 1]
                fold_scores.append(average_precision_score(y_valid, probabilities))
            return float(np.mean(fold_scores)) if fold_scores else 0.0

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
        best_params = study.best_params

        oof_probabilities = np.full(len(train), np.nan)
        for train_index, validation_index in splits:
            x_fit, y_fit = train_x.iloc[train_index], train_y.iloc[train_index]
            if y_fit.nunique() < 2:
                continue
            estimator = _make_estimator(name, best_params, _positive_weight(y_fit))
            estimator.fit(x_fit, y_fit)
            oof_probabilities[validation_index] = estimator.predict_proba(
                train_x.iloc[validation_index]
            )[:, 1]
        valid_oof = np.isfinite(oof_probabilities)
        calibrator = LogisticRegression(max_iter=1000, solver="lbfgs")
        calibrator.fit(
            oof_probabilities[valid_oof].reshape(-1, 1),
            train_y.to_numpy()[valid_oof],
        )
        if calibrator.coef_[0, 0] <= 0:
            raise ValueError(f"Temporal calibration inverted model ranking for {name}.")
        calibrated_oof = calibrator.predict_proba(
            oof_probabilities[valid_oof].reshape(-1, 1)
        )[:, 1]
        threshold, validation_f1 = _choose_threshold(
            train_y.to_numpy()[valid_oof], calibrated_oof,
        )
        final_estimator = _make_estimator(name, best_params, _positive_weight(train_y))
        final_estimator.fit(train_x, train_y)
        raw_test_probabilities = final_estimator.predict_proba(test_x)[:, 1]
        calibrated_estimator = CalibratedHotspotModel(final_estimator, calibrator)
        test_probabilities = calibrated_estimator.predict_proba(test_x)[:, 1]
        results[name] = {
            "best_params": best_params,
            "trials": int(n_trials),
            "cv_mean_pr_auc": float(study.best_value),
            "validation_f1_at_selected_threshold": validation_f1,
            "selected_threshold_from_temporal_oof": threshold,
            "test": _evaluate(test_y.to_numpy(), test_probabilities, threshold),
            "raw_test_brier_score": float(brier_score_loss(test_y, raw_test_probabilities)),
            "test_probabilities": test_probabilities,
        }
        fitted_models[name] = calibrated_estimator
        print(
            f"{name}: best temporal CV PR-AUC={study.best_value:.4f}; "
            f"holdout F1={results[name]['test']['f1']:.4f}"
        )

    best_name = max(
        results,
        key=lambda name: (
            results[name]["validation_f1_at_selected_threshold"],
            results[name]["cv_mean_pr_auc"],
        ),
    )
    best_result = results[best_name]
    best_model = fitted_models[best_name]
    if figures_dir is None:
        figures_dir = metrics_path.parent / "figures"
    _save_figures(
        frame,
        results,
        best_name,
        best_model,
        train_x,
        train_y,
        test_x,
        test_y,
        best_result["selected_threshold_from_temporal_oof"],
        figures_dir,
    )
    serializable_results = {}
    for name, result in results.items():
        serializable_results[name] = {
            key: value for key, value in result.items() if key != "test_probabilities"
        }
    metrics = {
        "task": "spatiotemporal grid-cell FIRMS hotspot classification; not a fire forecast",
        "data_source": "firms_open_meteo",
        "training_region": training_region,
        "weather_sampling": weather_sampling,
        "dataset": str(input_path),
        "rows": int(len(frame)),
        "date_start": frame["date"].min().date().isoformat(),
        "date_end": frame["date"].max().date().isoformat(),
        "grid_cells": int(frame["cell_id"].nunique()),
        "positive_grid_days": int(frame["label"].sum()),
        "negative_grid_days": int((frame["label"] == 0).sum()),
        "positive_rate": float(frame["label"].mean()),
        "detection_count_in_retained_examples": int(frame["fire_count"].sum()),
        "train_rows": int(len(train)),
        "train_positive_rows": int(train_y.sum()),
        "test_rows": int(len(test)),
        "test_positive_rows": int(test_y.sum()),
        "test_negative_rows": int((test_y == 0).sum()),
        "test_date_start": test["date"].min().date().isoformat(),
        "test_date_end": test["date"].max().date().isoformat(),
        "temporal_split": "80/20 by ascending distinct active date; no date appears in both partitions",
        "tuning": {
            "method": "Optuna TPE optimizing average precision across 3 expanding temporal folds",
            "trials_per_model": n_trials,
            "model_selection": "best temporal OOF F1, tie-broken by CV average precision; test set not used",
        },
        "calibration": (
            "Platt logistic calibration fitted on temporal out-of-fold training predictions; "
            "the holdout is used only for evaluation. Reported probabilities estimate the "
            "chance of a recorded FIRMS detection under this dataset's sampling scheme, "
            "not the physical chance that a cell will burn."
        ),
        "negative_definition": (
            "No cell-level FIRMS detection on a day when at least one detection occurred "
            "somewhere in the region. This is a satellite-activity proxy, not verified "
            "absence of fire or guaranteed cell-level overpass."
        ),
        "selected_model": best_name,
        "selected_threshold": best_result["selected_threshold_from_temporal_oof"],
        "test_metrics": best_result["test"],
        "regional_test_metrics": _regional_holdout(
            test,
            best_result["test_probabilities"],
            best_result["selected_threshold_from_temporal_oof"],
        ) if training_region == "peru" else None,
        "regional_assignment": (
            "Each holdout grid cell is assigned by its center coordinate; border cells whose "
            "centers fall outside Peru are excluded from regional subsets. Regional scores "
            "use the single national threshold and are descriptive, not independently tuned."
        ) if training_region == "peru" else None,
        "models": serializable_results,
        "features": GRID_FEATURES,
        "figures": [path.name for path in sorted(figures_dir.glob("*_real.png"))],
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": best_model,
            "features": GRID_FEATURES,
            "threshold": metrics["selected_threshold"],
            "selected_model": best_name,
            "data_source": "firms_open_meteo",
            "training_region": training_region,
        },
        model_path,
    )
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def predict_latest(
    model_path: Path,
    input_path: Path,
    *,
    allow_demo: bool = False,
) -> dict:
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}. Run `make train` first.")
    frame = load_training_data(input_path, allow_demo=allow_demo)
    bundle = joblib.load(model_path)
    latest_frame = frame.iloc[[-1]]
    latest = latest_frame.iloc[0]
    model = bundle["model"]
    features = bundle["features"]
    latest_features = latest_frame[features].astype("float64")
    probability = float(model.predict_proba(latest_features)[0, 1])
    threshold = float(bundle["threshold"])
    return {
        "date": latest["date"].date().isoformat(),
        "cell_id": latest["cell_id"] if "cell_id" in latest else None,
        "probability": probability,
        "threshold": threshold,
        "predicted_hotspot": int(probability >= threshold),
        "observed_hotspot": int(latest["label"]),
        "note": "Retrospective FIRMS cell-day classification; not a future fire forecast.",
    }
