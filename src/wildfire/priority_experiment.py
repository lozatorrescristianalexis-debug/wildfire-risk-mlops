"""Rebuild consistent labels/local Puno weather, train, and compare on matched days.

This is a regression comparison on an already-inspected historical holdout, not
an independent prospective validation. It never changes the deployed artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import joblib
import pandas as pd
from shapely import covers, points
from threadpoolctl import threadpool_limits

from .cli import ingest_data
from .config import ROOT
from .geography import region_data
from .model import _evaluate, load_training_data, train_model

ARTIFACTS = (
    "models/wildfire_real.joblib", "reports/real_metrics.json",
    "data/processed/real_daily.csv", "web/region_weather.json", "web/real_examples.json",
    "reports/real_ingestion.json",
)


def compare(baseline_root: Path, candidate_root: Path) -> dict:
    baseline_metrics = json.loads((baseline_root / "reports/real_metrics.json").read_text())
    baseline = joblib.load(baseline_root / "models/wildfire_real.joblib")
    candidate = joblib.load(candidate_root / "models/wildfire_real.joblib")
    old = load_training_data(baseline_root / "data/processed/real_daily.csv")
    new = load_training_data(candidate_root / "data/processed/real_daily.csv")
    keys = ["cell_id", "date"]
    old = old.set_index(keys)
    new = new.loc[new.date.ge(baseline_metrics["test_date_start"])].set_index(keys)
    matched = new.index.intersection(old.index).sort_values()
    new = new.loc[matched]
    old = old.loc[matched]
    labels = new.label.to_numpy(dtype=int)
    old_prob = baseline["model"].predict_proba(old[baseline["features"]])[:, 1]
    new_prob = candidate["model"].predict_proba(new[candidate["features"]])[:, 1]
    _, regions, _ = region_data()
    puno = covers(regions["puno"]["geometry"], points(new.longitude, new.latitude))
    comparison = {}
    for name, mask in (("peru", pd.Series(True, index=new.index).to_numpy()), ("puno", puno)):
        comparison[name] = {
            "rows": int(mask.sum()), "positive_rows": int(labels[mask].sum()),
            "baseline": _evaluate(labels[mask], old_prob[mask], baseline["threshold"]),
            "candidate": _evaluate(labels[mask], new_prob[mask], candidate["threshold"]),
        }
    return {
        "comparison_basis": "Same cell-days and corrected single-satellite labels; each model receives its own training weather policy.",
        "interpretation": "Exploratory regression check on an already-inspected holdout, not independent validation.",
        "test_date_start": baseline_metrics["test_date_start"],
        "matched_rows": len(matched),
        "labels_changed_on_matched_rows": int((old.label.to_numpy() != labels).sum()),
        "baseline_sha256": hashlib.sha256((baseline_root / ARTIFACTS[0]).read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256((candidate_root / ARTIFACTS[0]).read_bytes()).hexdigest(),
        "regions": comparison,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--trials", type=int, default=5)
    args = parser.parse_args()
    candidate_root = ROOT / "data/experiments/consistent_puno"
    baseline_root = ROOT / "data/experiments/priority_baseline"
    if not baseline_root.exists():
        baseline_root.mkdir(parents=True)
        for artifact in ARTIFACTS:
            target = baseline_root / artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / artifact, target)
    baseline_metrics = json.loads((baseline_root / "reports/real_metrics.json").read_text())
    if not args.skip_ingest:
        ingest_data(region="peru", output_root=candidate_root)
    ingestion = json.loads((candidate_root / "reports/real_ingestion.json").read_text())
    with threadpool_limits(limits=4):
        metrics = train_model(
            candidate_root / "data/processed/real_daily.csv",
            candidate_root / "models/wildfire_real.joblib",
            candidate_root / "reports/real_metrics.json",
            n_trials=args.trials, training_region="peru",
            weather_sampling=ingestion["weather_sampling"],
            holdout_start=baseline_metrics["test_date_start"],
        )
        report = compare(baseline_root, candidate_root)
    report["candidate_model"] = metrics["selected_model"]
    report["dataset_rows"] = metrics["rows"]
    report["train_rows"] = metrics["train_rows"]
    report["test_rows"] = metrics["test_rows"]
    report["activation_gate"] = {
        "rule": "National and Puno average precision and F1 must not decrease on matched corrected labels.",
        "passed": all(item["candidate"][metric] >= item["baseline"][metric]
                      for item in report["regions"].values() for metric in ("pr_auc", "f1")),
    }
    report["activated"] = False
    (ROOT / "reports/priority_improvement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
