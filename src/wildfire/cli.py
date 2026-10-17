from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import ROOT, get_settings, latest_firms_dates
from .demo import save_demo_dataset
from .ingest import build_daily_dataset, fetch_firms, fetch_weather, save_dataset
from .model import predict_latest, train_model

DATA_PATH = ROOT / "data" / "processed" / "daily.csv"
MODEL_PATH = ROOT / "models" / "wildfire.joblib"
METRICS_PATH = ROOT / "reports" / "metrics.json"


def ingest_data(firms_csv: Path | None = None) -> Path:
    settings = get_settings()
    if (settings.end_date - settings.start_date).days > 9:
        raise ValueError("FIRMS area API supports at most 10 days per request; adjust START_DATE.")
    if firms_csv is None:
        if (settings.start_date, settings.end_date) != latest_firms_dates():
            raise ValueError(
                "FIRMS area API only returns the latest 10 days. Use the default date "
                "window or pass --firms-csv for a historical FIRMS file."
            )
    fires = (
        fetch_firms(settings.firms_key, settings.firms_source, settings.area, settings.request_timeout)
        if firms_csv is None
        else pd.read_csv(firms_csv)
    )
    weather = fetch_weather(
        settings.latitude,
        settings.longitude,
        settings.start_date,
        settings.end_date,
        settings.request_timeout,
    )
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
    parser = argparse.ArgumentParser(description="Wildfire FIRMS/Open-Meteo demo pipeline")
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
        print(f"Saved dataset: {ingest_data(args.firms_csv)}")
    elif args.command == "data-demo":
        frame = save_demo_dataset(DATA_PATH, days=args.days, seed=args.seed)
        print(f"Saved {len(frame)} synthetic rows ({int(frame['label'].sum())} positive): {DATA_PATH}")
    elif args.command == "train":
        print(json.dumps(train_model(args.input, MODEL_PATH, METRICS_PATH), indent=2))
    elif args.command == "run":
        print(json.dumps(predict_latest(args.model, args.input), indent=2))


if __name__ == "__main__":
    main()
