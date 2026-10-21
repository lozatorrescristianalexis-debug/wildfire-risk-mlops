"""Reproducible regional challenger evaluation; never overwrites production.

All candidate/threshold selection uses temporal out-of-fold predictions before
an explicit, frozen test cutoff. Only the selected challenger is evaluated on
the already-known holdout; that evaluation is a retrospective comparison, not
a fresh prospective claim.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from threadpoolctl import threadpool_limits

from .config import ROOT
from .features import GRID_FEATURES
from .geography import region_at
from .model import (CalibratedHotspotModel, _choose_threshold, _evaluate,
                    _make_estimator, _positive_weight, _temporal_splits, load_training_data)


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_partitions(frame: pd.DataFrame, cutoff: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff_date = pd.Timestamp(cutoff)
    train = frame.loc[frame.date < cutoff_date].reset_index(drop=True)
    test = frame.loc[frame.date >= cutoff_date].reset_index(drop=True)
    if train.empty or test.empty or train.date.max() >= test.date.min():
        raise ValueError("The frozen temporal cutoff must separate nonempty chronological partitions.")
    return train, test


def select_candidate(results: dict) -> str:
    """Selection is intentionally unable to inspect test metrics."""
    return max(results, key=lambda name: (results[name]["selection"]["f1"],
                                         results[name]["selection"]["pr_auc"]))


def summarize_data(frame: pd.DataFrame, train: pd.DataFrame, test: pd.DataFrame, region: str) -> dict:
    regional = frame.loc[frame.region == region]
    return {
        "dataset_rows": len(frame), "training_rows": len(train), "test_rows": len(test),
        "training_date_start": train.date.min().date().isoformat(),
        "training_date_end": train.date.max().date().isoformat(),
        "test_date_start": test.date.min().date().isoformat(),
        "test_date_end": test.date.max().date().isoformat(),
        "regional_rows": len(regional), "regional_cells": int(regional.cell_id.nunique()),
        "regional_train_rows": int((train.region == region).sum()),
        "regional_train_positive_rows": int(train.loc[train.region == region, "label"].sum()),
        "regional_test_rows": int((test.region == region).sum()),
        "regional_test_positive_rows": int(test.loc[test.region == region, "label"].sum()),
        "retained_detection_count": int(frame.fire_count.sum()),
        "all_eligible_rows_used": True,
        "note": "All eligible CSV rows are assigned to development or test; no row subsampling. Raw detections are aggregated into cell-days, with weather warm-up and coverage filters.",
    }


def run_experiment(input_path: Path, model_path: Path, metrics_path: Path,
                   output_path: Path, candidate_path: Path, region: str = "puno") -> dict:
    for output in (output_path, candidate_path):
        if output.resolve() in {model_path.resolve(), metrics_path.resolve(), input_path.resolve()}:
            raise ValueError("Experimental outputs must not overwrite production artifacts or training data.")
    if output_path.resolve() == candidate_path.resolve():
        raise ValueError("Report and candidate must have distinct output paths.")
    metadata = json.loads(metrics_path.read_text())
    bundle = joblib.load(model_path)
    original_hash = file_digest(model_path)
    frame = load_training_data(input_path)
    if metadata.get("dataset_sha256") and metadata["dataset_sha256"] != file_digest(input_path):
        raise ValueError("Training dataset hash differs from the model's recorded input.")
    centers = frame[["cell_id", "latitude", "longitude"]].drop_duplicates("cell_id")
    mapping = {r.cell_id: region_at(r.latitude, r.longitude) for r in centers.itertuples()}
    frame["region"] = frame.cell_id.map(mapping)
    train, test = frozen_partitions(frame, metadata["test_date_start"])
    if len(train) != metadata["train_rows"] or len(test) != metadata["test_rows"]:
        raise ValueError("Dataset differs from production evaluation; do not compare changed cohorts.")
    if (int(train.label.sum()) != metadata["train_positive_rows"]
            or int(test.label.sum()) != metadata["test_positive_rows"]
            or frame.date.max().date().isoformat() != metadata["date_end"]):
        raise ValueError("Dataset labels or dates differ from the production evaluation cohort.")
    regional_train = train.loc[train.region == region].reset_index(drop=True)
    regional_test = test.loc[test.region == region].reset_index(drop=True)
    if regional_train.label.nunique() != 2 or regional_test.label.nunique() != 2:
        raise ValueError("The target region needs both classes in development and test.")
    selected_model = bundle["selected_model"]
    params = metadata["models"][selected_model]["best_params"]
    definitions = {
        "national_regional_threshold": (selected_model, params, train),
        "regional_logistic": ("logistic", {"C": 1.0}, regional_train),
        "regional_hist_gradient_boosting": ("hist_gradient_boosting", {
            "max_iter": 150, "learning_rate": 0.05, "max_leaf_nodes": 15,
            "l2_regularization": 5.0}, regional_train),
    }
    results = {}
    calibrators = {}
    for name, (estimator_name, config, development) in definitions.items():
        predictions = np.full(len(development), np.nan)
        folds = []
        for number, (fit_idx, valid_idx) in enumerate(_temporal_splits(development, 3), start=1):
            fit, valid = development.iloc[fit_idx], development.iloc[valid_idx]
            if fit.label.nunique() != 2:
                raise ValueError("A development fold does not contain both classes.")
            model = _make_estimator(estimator_name, config, _positive_weight(fit.label))
            model.fit(fit[GRID_FEATURES], fit.label.astype(int))
            predictions[valid_idx] = model.predict_proba(valid[GRID_FEATURES])[:, 1]
            folds.append({"fit_end": fit.date.max().date().isoformat(),
                          "validation_start": valid.date.min().date().isoformat(),
                          "validation_end": valid.date.max().date().isoformat()})
            print(f"{name}: fold {number}/3 completed", flush=True)
        valid_mask = np.isfinite(predictions)
        if name == "national_regional_threshold":
            # Reuse exactly the incumbent probability scale. Only its regional
            # decision threshold is a candidate, not a probability rescaling.
            calibrator = bundle["model"].calibrator
        else:
            calibrator = LogisticRegression(max_iter=1000, solver="lbfgs")
            calibrator.fit(predictions[valid_mask, None], development.label.to_numpy()[valid_mask])
            if calibrator.coef_[0, 0] <= 0:
                raise ValueError("Regional calibration inverted the ranking.")
        mask = valid_mask & (development.region.to_numpy() == region)
        probabilities = calibrator.predict_proba(predictions[mask, None])[:, 1]
        labels = development.label.to_numpy()[mask]
        threshold, _ = _choose_threshold(labels, probabilities)
        results[name] = {"threshold": threshold, "selection": _evaluate(labels, probabilities, threshold),
                         "selection_rows": int(mask.sum()), "folds": folds,
                         "estimator": estimator_name, "params": config}
        calibrators[name] = calibrator
    winner = select_candidate(results)
    print(f"Selected using development data only: {winner}", flush=True)
    # Freeze and persist selection BEFORE any challenger holdout prediction.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"region": region, "created_at": datetime.now(timezone.utc).isoformat(),
              "dataset_sha256": file_digest(input_path), "incumbent_sha256": original_hash,
              "data_usage": summarize_data(frame, train, test, region),
              "protocol": {"selection": "Highest regional temporal OOF F1, tie-break average precision; fixed candidates, no holdout tuning.",
                           "holdout": "Already-inspected historical holdout; exploratory comparison, not new independent validation.",
                           "probability_features": list(GRID_FEATURES),
                           "promotion": "Candidate only. Production model and thresholds remain unchanged."},
              "candidates": results, "selected_candidate": winner}
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    if winner == "national_regional_threshold":
        challenger = bundle["model"]
    else:
        estimator_name, config, development = definitions[winner]
        estimator = _make_estimator(estimator_name, config, _positive_weight(development.label))
        estimator.fit(development[GRID_FEATURES], development.label.astype(int))
        challenger = CalibratedHotspotModel(estimator, calibrators[winner])
    labels = regional_test.label.to_numpy()
    incumbent_prob = bundle["model"].predict_proba(regional_test[GRID_FEATURES])[:, 1]
    challenger_prob = challenger.predict_proba(regional_test[GRID_FEATURES])[:, 1]
    report["holdout_comparison"] = {
        "incumbent": _evaluate(labels, incumbent_prob, float(bundle["threshold"])),
        "selected_challenger": _evaluate(labels, challenger_prob, results[winner]["threshold"]),
        "positive_rate_baseline": float(labels.mean()),
    }
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": challenger, "features": list(GRID_FEATURES),
                 "threshold": results[winner]["threshold"], "region": region,
                 "status": "experimental_not_promoted", "selected_model": winner,
                 "test_cutoff": metadata["test_date_start"], "dataset_sha256": report["dataset_sha256"]}, candidate_path)
    report["candidate_artifact"] = str(candidate_path)
    report["production_unchanged"] = file_digest(model_path) == original_hash
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="puno")
    parser.add_argument("--input", type=Path, default=ROOT / "data/processed/real_daily.csv")
    parser.add_argument("--model", type=Path, default=ROOT / "models/wildfire_real.joblib")
    parser.add_argument("--metrics", type=Path, default=ROOT / "reports/real_metrics.json")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/puno_experiment.json")
    parser.add_argument("--candidate", type=Path, default=ROOT / "models/puno_candidate.joblib")
    args = parser.parse_args()
    with threadpool_limits(limits=4):
        report = run_experiment(args.input, args.model, args.metrics, args.output, args.candidate, args.region)
    print(json.dumps(report["holdout_comparison"], indent=2))


if __name__ == "__main__":
    main()
