from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

FEATURES = [
    "temperature_2m_max",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
    "latitude",
    "longitude",
]
REQUIRED_COLUMNS = ["date", "label", *FEATURES]


def load_training_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}. Run `make data-demo` first.")
    frame = pd.read_csv(path)
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Dataset is missing required column(s): {', '.join(missing)}")
    if frame.empty:
        raise ValueError("Dataset is empty.")
    frame = frame[REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("Dataset contains invalid dates.")
    for column in ["label", *FEATURES]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"Dataset contains missing or non-numeric values in {column}.")
    if not set(frame["label"].unique()).issubset({0, 1}):
        raise ValueError("label must contain only binary values 0 and 1.")
    return frame.sort_values("date").reset_index(drop=True)


def train_model(input_path: Path, model_path: Path, metrics_path: Path) -> dict:
    frame = load_training_data(input_path)
    split = int(len(frame) * 0.8)
    if split < 10 or frame["label"].nunique() != 2:
        raise ValueError("Training requires at least 10 training rows and both label classes.")
    train, test = frame.iloc[:split], frame.iloc[split:]
    if train["label"].nunique() != 2 or test["label"].nunique() != 2:
        raise ValueError(
            "Chronological 80/20 split must contain both classes in train and test; "
            "use a longer dataset or a different date range."
        )
    classifier = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=3,
        class_weight="balanced",
        random_state=42,
        n_jobs=1,
    )
    classifier.fit(train[FEATURES], train["label"].astype(int))
    predictions = classifier.predict(test[FEATURES])
    probabilities = classifier.predict_proba(test[FEATURES])[:, 1]
    metrics = {
        "task": "same-day retrospective FIRMS hotspot classification (not a forecast)",
        "dataset": str(input_path),
        "rows": int(len(frame)),
        "positive_rows": int(frame["label"].sum()),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "test_start_date": test["date"].min().date().isoformat(),
        "test_end_date": test["date"].max().date().isoformat(),
        "accuracy": float(accuracy_score(test["label"], predictions)),
        "precision": float(precision_score(test["label"], predictions, zero_division=0)),
        "recall": float(recall_score(test["label"], predictions, zero_division=0)),
        "f1": float(f1_score(test["label"], predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(test["label"], probabilities)),
        "confusion_matrix": confusion_matrix(test["label"], predictions).tolist(),
        "features": FEATURES,
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, model_path)
    metrics_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    return metrics


def predict_latest(model_path: Path, input_path: Path) -> dict:
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}. Run `make train` first.")
    frame = load_training_data(input_path)
    classifier = joblib.load(model_path)
    latest = frame.iloc[-1]
    probability = float(classifier.predict_proba(latest[FEATURES].to_frame().T)[0, 1])
    return {
        "date": latest["date"].date().isoformat(),
        "probability": probability,
        "predicted_hotspot": int(probability >= 0.5),
        "observed_hotspot": int(latest["label"]),
        "note": "Retrospective same-day demonstration only; not a future fire forecast.",
    }
