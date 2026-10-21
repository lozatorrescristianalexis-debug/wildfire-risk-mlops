from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import requests
from shapely import covers, points
from shapely.geometry import mapping, shape

from .config import ROOT, get_settings
from .demo import save_demo_dataset
from .features import create_grid, engineer_grid_daily
from .geography import region_data
from .ingest import (
    fetch_boundary_geojson,
    fetch_firms_history,
    fetch_weather_grid_history,
    save_dataset,
)
from .model import predict_latest, train_model
from .scenarios import build_region_weather_profiles
from .observations import fetch_availability
from .training_sources import sensor_windows
from .weather_sampling import national_weather_locations

DATA_PATH = ROOT / "data" / "processed" / "real_daily.csv"
DEMO_DATA_PATH = ROOT / "data" / "demo" / "daily.csv"
MODEL_PATH = ROOT / "models" / "wildfire_real.joblib"
METRICS_PATH = ROOT / "reports" / "real_metrics.json"


def ingest_data(
    firms_csv: Path | None = None,
    region: str | None = None,
    boundary_file: Path | None = None,
    output_root: Path = ROOT,
) -> Path:
    settings = get_settings(region_override=region)
    if (settings.end_date - settings.start_date).days < 364:
        raise ValueError("Final data ingestion requires at least one year of dates.")
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for directory in ("data/processed", "data/raw", "reports", "web"):
        (output_root / directory).mkdir(parents=True, exist_ok=True)
    source_coverage = {}
    source_frames = []
    if firms_csv is None:
        with requests.Session() as client:
            availability = fetch_availability(settings.firms_key, client)
        windows = sensor_windows(settings.firms_source, availability, settings.start_date, settings.end_date)
        for source, first, last in windows:
            frame = fetch_firms_history(
                settings.firms_key, source, settings.area, first, last,
                settings.request_timeout, raw_dir=raw_dir,
            )
            frame["firms_source"] = source
            source_frames.append(frame)
            source_coverage[source] = {
                **_source_summary(frame),
                "requested_start_date": first.isoformat(),
                "requested_end_date": last.isoformat(),
            }

        identity_columns = [
            column
            for column in ("acq_date", "acq_time", "latitude", "longitude", "satellite", "instrument")
            if any(column in frame.columns for frame in source_frames)
        ]
        source_frames = [frame for frame in source_frames if not frame.empty]
        if not source_frames:
            raise ValueError("FIRMS returned no detections from any requested real source.")
        fires = pd.concat(source_frames, ignore_index=True)
        if identity_columns:
            source_attribution = (
                fires.groupby(identity_columns, dropna=False)["firms_source"]
                .agg(lambda values: "|".join(sorted(set(values.astype(str)))))
                .rename("firms_source")
                .reset_index()
            )
            fires = (
                fires.drop_duplicates(subset=identity_columns, keep="first")
                .drop(columns=["firms_source"])
                .merge(source_attribution, on=identity_columns, how="left", validate="one_to_one")
                .reset_index(drop=True)
            )
    else:
        fires = pd.read_csv(firms_csv)
        if "firms_source" not in fires or fires["firms_source"].isna().any():
            raise ValueError("Training CSV must identify firms_source for every detection.")
        sensors = set(fires["firms_source"].astype(str).str.replace(r"_(SP|NRT)$", "", regex=True))
        if len(sensors) != 1:
            raise ValueError("Training CSV must use one consistent satellite throughout the period.")
        source_frames = [part.copy() for _, part in fires.groupby("firms_source")]
        source_coverage = {str(part["firms_source"].iloc[0]): _source_summary(part) for part in source_frames}

    if boundary_file is not None:
        boundary_path = boundary_file
    elif settings.region == "peru":
        # Use the same fixed national geometry that powers the region selector.
        boundary_path = raw_dir / "peru_local_boundary.geojson"
        _, _, country = region_data()
        boundary_path.write_text(
            json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"name": "Perú"},
                    "geometry": mapping(country),
                }],
            }),
            encoding="utf-8",
        )
    else:
        boundary_filename = f"{settings.region}_boundary.geojson"
        boundary_path = fetch_boundary_geojson(
            raw_dir / boundary_filename,
            state=settings.region_state,
            country=settings.region_country,
            timeout=settings.request_timeout,
        )
    boundary_data = json.loads(boundary_path.read_text(encoding="utf-8"))
    boundary = shape(boundary_data["features"][0]["geometry"])
    regional_firms_detections = None
    if settings.region == "peru":
        _, regions, _ = region_data()
        latitude = pd.to_numeric(fires["latitude"], errors="coerce")
        longitude = pd.to_numeric(fires["longitude"], errors="coerce")
        valid = latitude.notna() & longitude.notna()
        fire_points = points(longitude.loc[valid].to_numpy(), latitude.loc[valid].to_numpy())
        regional_firms_detections = {
            region_id: int(covers(region["geometry"], fire_points).sum())
            for region_id, region in regions.items()
        }
    for source_frame in source_frames:
        source = source_frame["firms_source"].iloc[0]
        source_coverage[source].update(_source_summary(source_frame, boundary))
    # Preserve the existing workflow artifact name, now documenting a stable sensor.
    (output_root / "reports" / "firms_gap_alternative_sources.json").write_text(
        json.dumps({"policy": "same_satellite_sp_then_nrt", "sources": source_coverage,
                    "note": "No alternate satellite is inserted to fill a temporal gap."}, indent=2) + "\n",
        encoding="utf-8",
    )
    grid = create_grid(
        settings.area,
        settings.grid_cell_degrees,
        boundary_path,
    )
    if settings.region == "peru":
        locations, assignments = national_weather_locations(grid)
        regional_points = locations.iloc[:25]
        regional_weather = fetch_weather_grid_history(
            regional_points, settings.start_date, settings.end_date, settings.request_timeout,
            batch_size=25, chunk_days=(settings.end_date - settings.start_date).days + 1,
            cache_dir=raw_dir,
        )
        local_weather = fetch_weather_grid_history(
            locations.iloc[25:], settings.start_date, settings.end_date, settings.request_timeout,
            batch_size=14, chunk_days=180, cache_dir=raw_dir,
        )
        sampled_weather = pd.concat([regional_weather, local_weather], ignore_index=True)
        profiles = build_region_weather_profiles(sampled_weather)
        profiles["weather_cells"] = assignments
        profiles["local_locations"] = [
            {"id": row.cell_id, "center": [row.latitude, row.longitude]}
            for row in locations.iloc[25:].itertuples()
        ]
        (output_root / "web" / "region_weather.json").write_text(
            json.dumps(profiles, indent=2) + "\n", encoding="utf-8",
        )
        weather = sampled_weather.rename(columns={"cell_id": "weather_id"}).merge(
            pd.DataFrame(assignments)[["cell_id", "weather_id"]],
            on="weather_id", how="inner", validate="many_to_many",
        ).drop(columns="weather_id")
        weather_sampling = (
            f"Open-Meteo UTC daily history: {len(locations) - 25} Puno grid-cell centers; "
            "25 regional representative points elsewhere, assigned by greatest cell overlap."
        )
    else:
        weather = fetch_weather_grid_history(
            grid,
            settings.start_date,
            settings.end_date,
            settings.request_timeout,
            batch_size=settings.weather_batch_size,
            chunk_days=settings.weather_chunk_days,
            cache_dir=raw_dir,
        )
        weather_sampling = "Open-Meteo historical series at each grid-cell center."
    weather_path = output_root / "data" / "raw" / "open_meteo_daily.csv"
    weather.to_csv(weather_path, index=False)
    dataset, feature_stats = engineer_grid_daily(
        fires,
        weather,
        grid,
        settings.start_date.isoformat(),
        settings.end_date.isoformat(),
        boundary_path,
    )
    save_dataset(dataset, output_root / "data/processed/real_daily.csv")
    (output_root / "data/raw/firms_source_coverage.json").write_text(
        json.dumps(source_coverage, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_root / "reports" / "real_ingestion.json").write_text(
        json.dumps(
            {
                "requested_start_date": settings.start_date.isoformat(),
                "requested_end_date": settings.end_date.isoformat(),
                "region": settings.region,
                "area": settings.area,
                "weather_sampling": weather_sampling,
                "regional_firms_detections": regional_firms_detections,
                "firms_sources": source_coverage,
                "source_sensor_note": (
                    "One satellite throughout: standard processing followed by its NRT product. "
                    "Map observations may include other sensors; training labels do not mix them."
                ),
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
    return output_root / "data/processed/real_daily.csv"


def _source_summary(frame: pd.DataFrame, boundary=None) -> dict:
    if frame.empty:
        summary = {"detections": 0, "first_detection": None, "last_detection": None}
        if boundary is not None:
            summary.update(
                {
                    "detections_in_administrative_boundary": 0,
                    "active_dates_in_administrative_boundary": 0,
                    "first_boundary_detection": None,
                    "last_boundary_detection": None,
                }
            )
        return summary
    dates = pd.to_datetime(frame["acq_date"], errors="coerce").dropna()
    result = {
        "detections": int(len(frame)),
        "first_detection": dates.min().date().isoformat() if not dates.empty else None,
        "last_detection": dates.max().date().isoformat() if not dates.empty else None,
    }
    if boundary is not None and {"latitude", "longitude"}.issubset(frame.columns):
        latitude = pd.to_numeric(frame["latitude"], errors="coerce")
        longitude = pd.to_numeric(frame["longitude"], errors="coerce")
        valid = latitude.notna() & longitude.notna()
        inside = pd.Series(False, index=frame.index)
        inside.loc[valid] = covers(
            boundary,
            points(longitude.loc[valid].to_numpy(), latitude.loc[valid].to_numpy()),
        )
        inside_frame = frame.loc[inside]
        inside_dates = pd.to_datetime(inside_frame["acq_date"], errors="coerce").dropna()
        result["detections_in_administrative_boundary"] = int(len(inside_frame))
        result["active_dates_in_administrative_boundary"] = int(inside_dates.nunique())
        result["first_boundary_detection"] = (
            inside_dates.min().date().isoformat() if not inside_dates.empty else None
        )
        result["last_boundary_detection"] = (
            inside_dates.max().date().isoformat() if not inside_dates.empty else None
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Wildfire risk FIRMS/Open-Meteo pipeline")
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data", help="Fetch FIRMS and Open-Meteo data")
    data.add_argument("--firms-csv", type=Path, help="Use a locally downloaded FIRMS CSV instead of the API")
    data.add_argument(
        "--region",
        choices=["madre_de_dios", "peru"],
        default=None,
        help="Target geographic region (default: from .env or madre_de_dios)",
    )
    data.add_argument(
        "--boundary",
        type=Path,
        default=None,
        help="Path to custom GeoJSON boundary file",
    )
    data.add_argument("--output-root", type=Path, default=ROOT, help="Isolate a candidate dataset and weather profiles")
    demo = commands.add_parser("data-demo", help="Create a deterministic synthetic training dataset")
    demo.add_argument("--days", type=int, default=1095)
    demo.add_argument("--seed", type=int, default=42)
    train = commands.add_parser("train", help="Train model and save holdout metrics")
    train.add_argument("--input", type=Path, default=DATA_PATH)
    train.add_argument("--trials", type=int, default=10, help="Optuna trials per model")
    train.add_argument("--region", choices=["madre_de_dios", "peru"], default=None,
                       help="Geographic scope of the ingested training dataset")
    predict = commands.add_parser("run", help="Score the latest row in the dataset")
    predict.add_argument("--input", type=Path, default=DATA_PATH)
    predict.add_argument("--model", type=Path, default=MODEL_PATH)
    args = parser.parse_args()
    if args.command == "data":
        path = ingest_data(
            firms_csv=args.firms_csv,
            region=args.region,
            boundary_file=args.boundary,
            output_root=args.output_root,
        )
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
        training_region = args.region
        weather_sampling = None
        ingestion_report = ROOT / "reports" / "real_ingestion.json"
        if args.input.resolve() == DATA_PATH.resolve() and ingestion_report.exists():
            ingestion_metadata = json.loads(ingestion_report.read_text(encoding="utf-8"))
            ingested_region = ingestion_metadata.get("region")
            weather_sampling = ingestion_metadata.get("weather_sampling")
            if ingested_region in {"madre_de_dios", "peru"}:
                if training_region and training_region != ingested_region:
                    raise ValueError(
                        f"Training region {training_region} disagrees with ingested dataset region {ingested_region}."
                    )
                training_region = ingested_region
        training_region = training_region or get_settings().region
        print(
            json.dumps(
                train_model(args.input, MODEL_PATH, METRICS_PATH,
                            n_trials=args.trials,
                            training_region=training_region,
                            weather_sampling=weather_sampling),
                indent=2,
            )
        )
    elif args.command == "run":
        print(json.dumps(predict_latest(args.model, args.input), indent=2))


if __name__ == "__main__":
    main()
