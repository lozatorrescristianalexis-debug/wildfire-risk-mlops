from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from shapely import covers, points
from shapely.geometry import box, mapping, shape

from .config import ROOT, get_settings
from .demo import save_demo_dataset
from .features import create_grid, engineer_grid_daily
from .geography import region_catalog, region_data
from .ingest import (
    fetch_boundary_geojson,
    fetch_firms_history,
    fetch_weather_grid_history,
    save_dataset,
)
from .model import predict_latest, train_model
from .scenarios import build_region_weather_profiles

DATA_PATH = ROOT / "data" / "processed" / "real_daily.csv"
DEMO_DATA_PATH = ROOT / "data" / "demo" / "daily.csv"
MODEL_PATH = ROOT / "models" / "wildfire_real.joblib"
METRICS_PATH = ROOT / "reports" / "real_metrics.json"
ALTERNATE_GAP_SOURCES = (
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_SP",
    "MODIS_NRT",
)
ALTERNATE_GAP_START = date(2026, 7, 1)
ALTERNATE_GAP_END = date(2026, 8, 20)


def ingest_data(
    firms_csv: Path | None = None,
    region: str | None = None,
    boundary_file: Path | None = None,
) -> Path:
    settings = get_settings(region_override=region)
    if (settings.end_date - settings.start_date).days < 364:
        raise ValueError("Final data ingestion requires at least one year of dates.")
    raw_dir = ROOT / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    source_coverage = {}
    source_frames = []
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
        gap_start = ALTERNATE_GAP_START
        gap_end = ALTERNATE_GAP_END
        if settings.start_date > gap_start or settings.end_date < gap_end:
            gap_sources = ()
        else:
            gap_sources = ALTERNATE_GAP_SOURCES
        for source in gap_sources:
            alternate = fetch_firms_history(
                settings.firms_key,
                source,
                settings.area,
                gap_start,
                gap_end,
                settings.request_timeout,
                raw_dir=raw_dir,
            )
            alternate["firms_source"] = source
            output = raw_dir / f"firms_{source.lower()}_gap.csv"
            output.write_text(
                alternate.drop(columns=["firms_source"]).to_csv(index=False),
                encoding="utf-8",
            )
            source_frames.append(alternate)
            source_coverage[source] = {
                **_source_summary(alternate),
                "requested_start_date": gap_start.isoformat(),
                "requested_end_date": gap_end.isoformat(),
            }

        identity_columns = [
            column
            for column in ("acq_date", "latitude", "longitude", "satellite", "instrument")
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
        fires["firms_source"] = "local_firms_csv"
        source_frames = [fires]
        source_coverage["local_firms_csv"] = _source_summary(fires)

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
    alternative_gap_dates = set()
    for source_frame in source_frames:
        source = source_frame["firms_source"].iloc[0]
        if source not in ALTERNATE_GAP_SOURCES:
            continue
        latitude = pd.to_numeric(source_frame["latitude"], errors="coerce")
        longitude = pd.to_numeric(source_frame["longitude"], errors="coerce")
        valid = latitude.notna() & longitude.notna()
        inside = pd.Series(False, index=source_frame.index)
        inside.loc[valid] = covers(
            boundary,
            points(longitude.loc[valid].to_numpy(), latitude.loc[valid].to_numpy()),
        )
        dates = pd.to_datetime(source_frame.loc[inside, "acq_date"], errors="coerce")
        alternative_gap_dates.update(
            dates.dropna()
            .loc[
                lambda values: values.between(
                    pd.Timestamp(gap_start), pd.Timestamp(gap_end)
                )
            ]
            .dt.strftime("%Y-%m-%d")
            .tolist()
        )
    gap_day_count = (gap_end - gap_start).days + 1
    (ROOT / "reports" / "firms_gap_alternative_sources.json").write_text(
        json.dumps(
            {
                "requested_start_date": gap_start.isoformat(),
                "requested_end_date": gap_end.isoformat(),
                "requested_days_inclusive": gap_day_count,
                "days_with_at_least_one_in_boundary_detection": len(alternative_gap_dates),
                "days_without_returned_in_boundary_detections": gap_day_count
                - len(alternative_gap_dates),
                "sources": {
                    source: source_coverage[source] for source in ALTERNATE_GAP_SOURCES
                },
                "note": (
                    "Products remain separately attributed; a day without a returned "
                    "detection is not evidence of no fire or satellite coverage."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    grid = create_grid(
        settings.area,
        settings.grid_cell_degrees,
        boundary_path,
    )
    if settings.region == "peru":
        # Regional weather samples keep the national backfill within the public
        # archive API's limits while retaining every grid cell and FIRMS event.
        _, regions, _ = region_data()
        regional_points = pd.DataFrame([
            {"cell_id": region["id"],
             "latitude": region["center"][0],
             "longitude": region["center"][1]}
            for region in region_catalog()[1:]
        ])
        regional_weather = fetch_weather_grid_history(
            regional_points,
            settings.start_date,
            settings.end_date,
            settings.request_timeout,
            batch_size=len(regional_points),
            chunk_days=(settings.end_date - settings.start_date).days + 1,
            cache_dir=raw_dir,
        )
        profile_path = ROOT / "web" / "region_weather.json"
        profile_path.write_text(
            json.dumps(build_region_weather_profiles(regional_weather), indent=2) + "\n",
            encoding="utf-8",
        )
        regional_weather = regional_weather.rename(columns={"cell_id": "weather_region"})
        assignments = []
        for cell in grid.itertuples():
            cell_geometry = box(
                cell.bbox_west + cell.grid_column * cell.cell_degrees,
                cell.bbox_south + cell.grid_row * cell.cell_degrees,
                cell.bbox_west + (cell.grid_column + 1) * cell.cell_degrees,
                cell.bbox_south + (cell.grid_row + 1) * cell.cell_degrees,
            )
            weather_region = max(
                regions,
                key=lambda region_id: regions[region_id]["geometry"].intersection(cell_geometry).area,
            )
            assignments.append({"cell_id": cell.cell_id, "weather_region": weather_region})
        weather = regional_weather.merge(
            pd.DataFrame(assignments), on="weather_region", how="inner", validate="many_to_many"
        ).drop(columns="weather_region")
        weather_sampling = (
            "One Open-Meteo historical series at a representative point per administrative "
            "region (25 sites); each 0.5-degree cell inherits the series of the region "
            "with the greatest overlap. Local weather variation within a region is not resolved."
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
                "region": settings.region,
                "area": settings.area,
                "weather_sampling": weather_sampling,
                "regional_firms_detections": regional_firms_detections,
                "firms_sources": source_coverage,
                "source_sensor_note": (
                    "SNPP labels are supplemented with separately attributed "
                    "NOAA20, NOAA21 and MODIS products only during the coverage gap."
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
    return DATA_PATH


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
