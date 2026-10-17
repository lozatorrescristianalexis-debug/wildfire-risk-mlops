from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import ROOT, get_settings
from .demo import save_demo_dataset
from .ingest import (
    build_daily_dataset,
    fetch_firms_history,
    fetch_weather_history,
    save_dataset,
)
from .model import predict_latest, train_model

DATA_PATH = ROOT / "data" / "processed" / "real_daily.csv"
DEMO_DATA_PATH = ROOT / "data" / "demo" / "daily.csv"
MODEL_PATH = ROOT / "models" / "wildfire_real.joblib"
METRICS_PATH = ROOT / "reports" / "real_metrics.json"


def ingest_data(firms_csv: Path | None = None) -> Path:
    settings = get_settings()
    if (settings.end_date - settings.start_date).days < 364:
        raise ValueError("Final data ingestion requires at least one year of dates.")
    fires = (
        fetch_firms_history(
            settings.firms_key,
            settings.firms_source,
            settings.area,
            settings.start_date,
            settings.end_date,
            settings.request_timeout,
        )
        if firms_csv is None
        else pd.read_csv(firms_csv)
    )
    raw_firms_path = ROOT / "data" / "raw" / "firms_detections.csv"
    raw_firms_path.parent.mkdir(parents=True, exist_ok=True)
    fires.to_csv(raw_firms_path, index=False)
    weather = fetch_weather_history(
        settings.latitude,
        settings.longitude,
        settings.start_date,
        settings.end_date,
        settings.request_timeout,
    )
    weather_path = ROOT / "data" / "raw" / "open_meteo_daily.csv"
    weather.to_csv(weather_path, index=False)
    dataset = build_daily_dataset(
        fires,
        weather,
        settings.start_date,
        settings.end_date,
        settings.latitude,
        settings.longitude,
    )
    save_dataset(dataset, DATA_PATH)
    return DATA_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Madre de Dios FIRMS/Open-Meteo pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data", help="Fetch FIRMS and Open-Meteo data")
    data.add_argument("--firms-csv", type=Path, help="Use a locally downloaded FIRMS CSV instead of the API")
    demo = commands.add_parser("data-demo", help="Create a deterministic synthetic training dataset")
    demo.add_argument("--days", type=int, default=1095)
    demo.add_argument("--seed", type=int, default=42)
    train = commands.add_parser("train", help="Train model and save holdout metrics")
    train.add_argument("--input", type=Path, default=DATA_PATH)
    predict = commands.add_parser("run", help="Score the latest row in the dataset")
    predict.add_argument("--input", type=Path, default=DATA_PATH)
    predict.add_argument("--model", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    if args.command == "data":
        path = ingest_data(args.firms_csv)
        frame = pd.read_csv(path)
        print(
            json.dumps(
                {
                    "dataset": str(path),
                    "source": "firms_open_meteo",
                    "rows": int(len(frame)),
                    "start_date": frame["date"].min(),
                    "end_date": frame["date"].max(),
                    "positive_days": int(frame["label"].sum()),
                    "negative_days": int((frame["label"] == 0).sum()),
                    "positive_rate": float(frame["label"].mean()),
                    "firms_detections": int(frame["fire_count"].sum()),
                },
                indent=2,
            )
        )
    elif args.command == "data-demo":
        frame = save_demo_dataset(DEMO_DATA_PATH, days=args.days, seed=args.seed)
        print(f"Saved {len(frame)} synthetic rows ({int(frame['label'].sum())} positive): {DEMO_DATA_PATH}")
    elif args.command == "train":
        print(json.dumps(train_model(args.input, MODEL_PATH, METRICS_PATH), indent=2))
    elif args.command == "run":
        print(json.dumps(predict_latest(args.model, args.input), indent=2))


if __name__ == "__main__":
    main()
