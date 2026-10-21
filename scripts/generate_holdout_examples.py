"""Create real positive/negative UI examples from the deployed model's temporal holdout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
from src.wildfire.config import ROOT
from src.wildfire.geography import region_at
from src.wildfire.model import load_training_data


def generate(model_path: Path, metrics_path: Path, data_path: Path, output_path: Path) -> dict:
    bundle = joblib.load(model_path)
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if bundle.get("training_region") != metrics.get("training_region"):
        raise ValueError("Model and metrics must describe the same training region.")
    frame = load_training_data(data_path)
    test = frame.loc[
        frame["date"].between(metrics["test_date_start"], metrics["test_date_end"])
    ].copy()
    if len(test) != metrics["test_rows"]:
        raise ValueError("The dataset does not match the model's temporal holdout.")
    probabilities = bundle["model"].predict_proba(test[bundle["features"]])[:, 1]
    threshold = float(bundle["threshold"])
    test["probability"] = probabilities
    test["mapped_region"] = [
        region_at(float(lat), float(lon))
        for lat, lon in zip(test["latitude"], test["longitude"], strict=True)
    ]
    positive = test.loc[test["label"].eq(1) & test["probability"].ge(threshold)]
    negative = test.loc[test["label"].eq(0) & test["probability"].lt(threshold)]
    if metrics["training_region"] == "peru":
        positive = positive.loc[positive["mapped_region"].ne("madre_de_dios")]
    if positive.empty or negative.empty:
        raise ValueError("The holdout needs one correctly classified example of each class.")
    positive_row = positive.sort_values("probability", ascending=False).iloc[0]
    other_region = negative.loc[negative["mapped_region"].ne(positive_row["mapped_region"])]
    negative_row = (other_region if not other_region.empty else negative).sort_values("probability").iloc[0]

    def as_example(row) -> dict:
        return {
            "cell_id": row["cell_id"],
            "date": row["date"].date().isoformat(),
            "region": row["mapped_region"],
            "observed_hotspot": bool(row["label"]),
            "fire_count": int(row["fire_count"]),
            "expected_probability": float(row["probability"]),
            "threshold": threshold,
            "features": {name: float(row[name]) for name in bundle["features"]},
        }

    examples = {"positive": as_example(positive_row), "negative": as_example(negative_row)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(examples, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return examples


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "models/wildfire_real.joblib")
    parser.add_argument("--metrics", type=Path, default=ROOT / "reports/real_metrics.json")
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/real_daily.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "web/real_examples.json")
    args = parser.parse_args()
    examples = generate(args.model, args.metrics, args.data, args.output)
    print({kind: {key: item[key] for key in ("date", "region", "observed_hotspot")}
           for kind, item in examples.items()})
