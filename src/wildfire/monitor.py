from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .features import GRID_FEATURES


def monitor_drift(
    input_path: Path,
    *,
    recent_days: int = 30,
    reference_days: int = 90,
) -> dict:
    if recent_days < 1 or reference_days < 1:
        raise ValueError("recent_days and reference_days must be positive.")
    frame = pd.read_csv(input_path)
    if frame.empty or "data_source" not in frame:
        raise ValueError("Drift monitoring requires a non-empty real-data dataset.")
    if set(frame["data_source"].dropna().unique()) != {"firms_open_meteo"}:
        raise ValueError("Drift monitoring refuses non-real or mixed-source datasets.")
    required = {"date", "label", *GRID_FEATURES}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Drift dataset is missing columns: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].isna().any():
        raise ValueError("Drift dataset contains invalid dates.")
    for feature in GRID_FEATURES:
        frame[feature] = pd.to_numeric(frame[feature], errors="coerce")
    if frame[GRID_FEATURES].isna().any().any():
        raise ValueError("Drift dataset contains missing or non-numeric features.")

    latest = frame["date"].max().normalize()
    recent_start = latest - pd.Timedelta(days=recent_days - 1)
    reference_end = recent_start - pd.Timedelta(days=1)
    reference_start = reference_end - pd.Timedelta(days=reference_days - 1)
    recent = frame.loc[frame["date"].between(recent_start, latest)]
    reference = frame.loc[frame["date"].between(reference_start, reference_end)]
    if recent.empty or reference.empty:
        raise ValueError("Not enough temporal data for the requested drift windows.")

    feature_drift = {}
    for feature in GRID_FEATURES:
        reference_values = reference[feature].to_numpy(dtype=float)
        recent_values = recent[feature].to_numpy(dtype=float)
        edges = np.unique(np.quantile(reference_values, np.linspace(0, 1, 11)))
        if len(edges) < 2:
            continue
        edges[0], edges[-1] = -np.inf, np.inf
        reference_counts = np.histogram(reference_values, bins=edges)[0].astype(float)
        recent_counts = np.histogram(recent_values, bins=edges)[0].astype(float)
        reference_share = (reference_counts + 1e-6) / (
            reference_counts.sum() + 1e-6 * len(reference_counts)
        )
        recent_share = (recent_counts + 1e-6) / (
            recent_counts.sum() + 1e-6 * len(recent_counts)
        )
        psi = float(
            np.sum((recent_share - reference_share) * np.log(recent_share / reference_share))
        )
        feature_drift[feature] = {
            "psi": psi,
            "reference_mean": float(reference_values.mean()),
            "recent_mean": float(recent_values.mean()),
            "drift_detected": psi >= 0.2,
        }

    reference_rate = float(reference["label"].mean())
    recent_rate = float(recent["label"].mean())
    return {
        "data_source": "firms_open_meteo",
        "reference_window": {
            "start": reference_start.date().isoformat(),
            "end": reference_end.date().isoformat(),
            "rows": int(len(reference)),
        },
        "recent_window": {
            "start": recent_start.date().isoformat(),
            "end": latest.date().isoformat(),
            "rows": int(len(recent)),
        },
        "label_rate": {
            "reference": reference_rate,
            "recent": recent_rate,
            "absolute_change": recent_rate - reference_rate,
        },
        "features": feature_drift,
        "drifted_features": sorted(
            name for name, result in feature_drift.items() if result["drift_detected"]
        ),
        "threshold": "PSI >= 0.20 indicates a monitoring flag, not a model-failure diagnosis",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare recent real-data features with a prior window.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--reference-days", type=int, default=90)
    args = parser.parse_args()
    result = monitor_drift(
        args.input,
        recent_days=args.recent_days,
        reference_days=args.reference_days,
    )
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
