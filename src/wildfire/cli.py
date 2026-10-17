from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import ROOT, get_settings
from .demo import save_demo_dataset
from .features import create_grid, engineer_grid_daily
from .ingest import (
    fetch_boundary_geojson,
    fetch_firms_history,
    fetch_weather_grid_history,
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
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_coverage = {}
    if firms_csv is None:
        standard = fetch_firms_history(
            settings.firms_key,
            settings.firms_source,
            settings.area,
            settings.start_date,
            settings.end_date,
            settings.request_timeout,
            raw_dir=raw_dir,
        )
        standard["firms_source"] = settings.firms_source
        (raw_dir / f"firms_{settings.firms_source.lower()}.csv").write_text(
            standard.drop(columns=["firms_source"]).to_csv(index=False),
            encoding="utf-8",
        )
        source_frames = [standard]
        source_coverage[settings.firms_source] = {
            **_source_summary(standard),
            "requested_start_date": settings.start_date.isoformat(),
            "requested_end_date": settings.end_date.isoformat(),
        }

        utc_today = datetime.now(timezone.utc).date()
        nrt_start = max(
            settings.start_date,
            settings.end_date - timedelta(days=59),
            utc_today - timedelta(days=59),
        )
        if nrt_start <= settings.end_date:
            nrt_source = "VIIRS_SNPP_NRT"
            near_real_time = fetch_firms_history(
                settings.firms_key,
                nrt_source,
                settings.area,
                nrt_start,
                settings.end_date,
                settings.request_timeout,
                raw_dir=raw_dir,
            )
            near_real_time["firms_source"] = nrt_source
            (raw_dir / "firms_viirs_snpp_nrt.csv").write_text(
                near_real_time.drop(columns=["firms_source"]).to_csv(index=False),
                encoding="utf-8",
            )
            source_frames.append(near_real_time)
            source_coverage[nrt_source] = {
                **_source_summary(near_real_time),
                "requested_start_date": nrt_start.isoformat(),
                "requested_end_date": settings.end_date.isoformat(),
            }
        fires = pd.concat(source_frames, ignore_index=True)
        identity_columns = [
            column
            for column in ("acq_date", "latitude", "longitude", "satellite", "instrument")
            if column in fires.columns
        ]
        fires = fires.drop_duplicates(subset=identity_columns, keep="first").reset_index(drop=True)
    else:
        fires = pd.read_csv(firms_csv)
        fires["firms_source"] = "local_firms_csv"
        source_coverage["local_firms_csv"] = _source_summary(fires)

    boundary_path = fetch_boundary_geojson(raw_dir / "madre_de_dios_boundary.geojson")
    grid = create_grid(
        settings.area,
        settings.grid_cell_degrees,
        boundary_path,
    )
    weather = fetch_weather_grid_history(
        grid,
        settings.start_date,
        settings.end_date,
        settings.request_timeout,
        cache_dir=raw_dir,
    )
    weather_path = ROOT / "data" / "raw" / "open_meteo_daily.csv"
    weather.to_csv(weather_path, index=False)
    dataset, feature_stats = engineer_grid_daily(
        fires,
        weather,
        grid,
        settings.start_date.isoformat(),
        settings.end_date.isoformat(),
        boundary_path,
    )
    save_dataset(dataset, DATA_PATH)
    (raw_dir / "firms_source_coverage.json").write_text(
        json.dumps(source_coverage, indent=2) + "\n",
        encoding="utf-8",
    )
    (ROOT / "reports" / "real_ingestion.json").write_text(
        json.dumps(
            {
                "requested_start_date": settings.start_date.isoformat(),
                "requested_end_date": settings.end_date.isoformat(),
                "firms_sources": source_coverage,
                "features": feature_stats,
                "rows": int(len(dataset)),
                "positive_grid_days": int(dataset["label"].sum()),
                "negative_grid_days": int((dataset["label"] == 0).sum()),
                "positive_rate": float(dataset["label"].mean()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return DATA_PATH


def _source_summary(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"detections": 0, "first_detection": None, "last_detection": None}
    dates = pd.to_datetime(frame["acq_date"], errors="coerce").dropna()
    return {
        "detections": int(len(frame)),
        "first_detection": dates.min().date().isoformat() if not dates.empty else None,
        "last_detection": dates.max().date().isoformat() if not dates.empty else None,
    }


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
    train.add_argument("--trials", type=int, default=10, help="Optuna trials per model")
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
        print(
            json.dumps(
                train_model(args.input, MODEL_PATH, METRICS_PATH, n_trials=args.trials),
                indent=2,
            )
        )
    elif args.command == "run":
        print(json.dumps(predict_latest(args.model, args.input), indent=2))


if __name__ == "__main__":
    main()
