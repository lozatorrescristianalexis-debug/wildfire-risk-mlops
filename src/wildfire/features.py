from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import covers, points
from shapely.geometry import box, shape

from .ingest import WEATHER_COLUMNS

LAG_FEATURES = [
    "temperature_2m_max_lag1",
    "relative_humidity_2m_mean_lag1",
    "precipitation_sum_lag1",
    "wind_speed_10m_max_lag1",
    "temperature_2m_max_mean_3d",
    "temperature_2m_max_mean_7d",
    "relative_humidity_2m_mean_mean_7d",
    "wind_speed_10m_max_mean_7d",
    "precipitation_sum_sum_3d",
    "precipitation_sum_sum_7d",
    "precipitation_sum_sum_30d",
]
GRID_FEATURES = [*LAG_FEATURES, "latitude", "longitude"]


def add_lagged_weather(frame: pd.DataFrame) -> pd.DataFrame:
    """Use the same past-only weather features for training and map scenarios."""
    data = frame.sort_values(["cell_id", "date"]).reset_index(drop=True).copy()
    grouped = data.groupby("cell_id", sort=False)
    for column in WEATHER_COLUMNS:
        data[f"{column}_lag1"] = grouped[column].shift(1)
    for column, window in (
        ("temperature_2m_max", 3),
        ("temperature_2m_max", 7),
        ("relative_humidity_2m_mean", 7),
        ("wind_speed_10m_max", 7),
    ):
        data[f"{column}_mean_{window}d"] = grouped[column].transform(
            lambda values: values.shift(1).rolling(window, min_periods=window).mean()
        )
    for window in (3, 7, 30):
        data[f"precipitation_sum_sum_{window}d"] = grouped["precipitation_sum"].transform(
            lambda values: values.shift(1).rolling(window, min_periods=window).sum()
        )
    return data


def create_grid(area: str, cell_degrees: float, boundary_path: Path) -> pd.DataFrame:
    if cell_degrees <= 0:
        raise ValueError("GRID_CELL_DEGREES must be greater than zero.")
    west, south, east, north = (float(value) for value in area.split(","))
    if not (west < east and south < north):
        raise ValueError("FIRMS_AREA must be west,south,east,north.")
    if not boundary_path.exists():
        raise FileNotFoundError(f"Administrative boundary file not found: {boundary_path}")
    boundary_data = json.loads(boundary_path.read_text(encoding="utf-8"))
    if boundary_data.get("type") == "FeatureCollection":
        if len(boundary_data.get("features", [])) != 1:
            raise ValueError("Boundary GeoJSON must contain exactly one feature.")
        polygon = shape(boundary_data["features"][0]["geometry"])
    else:
        polygon = shape(boundary_data)
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError("Administrative boundary geometry is empty or invalid.")

    columns = math.ceil((east - west) / cell_degrees)
    rows = math.ceil((north - south) / cell_degrees)
    cells = []
    for row in range(rows):
        for column in range(columns):
            cell = box(
                west + column * cell_degrees,
                south + row * cell_degrees,
                min(west + (column + 1) * cell_degrees, east),
                min(south + (row + 1) * cell_degrees, north),
            )
            covered_part = polygon.intersection(cell)
            if covered_part.area > 0:
                sample_point = cell.centroid
                if not polygon.covers(sample_point):
                    sample_point = covered_part.representative_point()
                cells.append(
                    {
                        "cell_id": f"r{row:03d}_c{column:03d}",
                        "grid_row": row,
                        "grid_column": column,
                        "latitude": sample_point.y,
                        "longitude": sample_point.x,
                        "cell_degrees": cell_degrees,
                        "bbox_west": west,
                        "bbox_south": south,
                    }
                )
    if not cells:
        raise ValueError("No grid-cell centers fall inside the administrative boundary.")
    return pd.DataFrame(cells)


def engineer_grid_daily(
    fires: pd.DataFrame,
    weather: pd.DataFrame,
    grid: pd.DataFrame,
    start_date: str,
    end_date: str,
    boundary_path: Path,
) -> tuple[pd.DataFrame, dict]:
    required_fires = {"acq_date", "latitude", "longitude"}
    if not required_fires.issubset(fires.columns):
        raise ValueError(f"FIRMS data must contain {', '.join(sorted(required_fires))}.")
    required_weather = {"cell_id", "date", *WEATHER_COLUMNS}
    if not required_weather.issubset(weather.columns):
        raise ValueError(f"Weather data must contain {', '.join(sorted(required_weather))}.")

    observations = fires.copy()
    if "firms_source" not in observations:
        observations["firms_source"] = "unknown_firms_product"
    observations["acq_date"] = pd.to_datetime(observations["acq_date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    observations["latitude"] = pd.to_numeric(observations["latitude"], errors="coerce")
    observations["longitude"] = pd.to_numeric(observations["longitude"], errors="coerce")
    observations = observations.dropna(subset=["acq_date", "latitude", "longitude"])
    valid_coordinate_count = len(observations)
    boundary_data = json.loads(boundary_path.read_text(encoding="utf-8"))
    polygon = shape(boundary_data["features"][0]["geometry"])
    in_boundary = covers(
        polygon,
        points(observations["longitude"].to_numpy(), observations["latitude"].to_numpy()),
    )
    observations = observations.loc[
        observations["acq_date"].between(start_date, end_date)
        & in_boundary
    ].copy()

    step = float(grid["cell_degrees"].iloc[0])
    if not step or step <= 0:
        raise ValueError("Unable to determine grid cell resolution.")
    west_edge = float(grid["bbox_west"].iloc[0])
    south_edge = float(grid["bbox_south"].iloc[0])
    observations["grid_column"] = np.floor(
        (observations["longitude"] - west_edge) / step
    ).astype(int)
    observations["grid_row"] = np.floor((observations["latitude"] - south_edge) / step).astype(int)
    cell_lookup = grid.set_index(["grid_row", "grid_column"])["cell_id"]
    observation_keys = pd.MultiIndex.from_frame(observations[["grid_row", "grid_column"]])
    observations["cell_id"] = cell_lookup.reindex(observation_keys).to_numpy()
    observations = observations.dropna(subset=["cell_id"])
    fire_groups = observations.groupby(["cell_id", "acq_date"])
    fires_by_cell_day = fire_groups.size().rename("fire_count").to_frame()
    fires_by_cell_day["firms_sources"] = fire_groups["firms_source"].agg(
        lambda values: "|".join(sorted(set(values.astype(str))))
    )
    fires_by_cell_day = fires_by_cell_day.reset_index().rename(
        columns={"acq_date": "date"}
    )
    total_detections = int(len(observations))

    dates = pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d")
    calendar = pd.MultiIndex.from_product(
        [grid["cell_id"].tolist(), dates], names=["cell_id", "date"]
    ).to_frame(index=False)
    weather_frame = weather.copy()
    weather_frame["date"] = pd.to_datetime(weather_frame["date"], errors="coerce").dt.strftime(
        "%Y-%m-%d"
    )
    for column in WEATHER_COLUMNS:
        weather_frame[column] = pd.to_numeric(weather_frame[column], errors="coerce")
    raw_weather_missing = int(weather_frame[list(WEATHER_COLUMNS)].isna().any(axis=1).sum())
    data = (
        calendar.merge(weather_frame, on=["cell_id", "date"], how="left", validate="one_to_one")
        .merge(fires_by_cell_day, on=["cell_id", "date"], how="left", validate="one_to_one")
        .merge(grid, on="cell_id", how="left", validate="many_to_one")
    )
    data["fire_count"] = data["fire_count"].fillna(0).astype("int64")
    data["firms_sources"] = data["firms_sources"].fillna("none")
    data["label"] = data["fire_count"].gt(0).astype("int64")
    data = add_lagged_weather(data)

    daily_detection_counts = data.groupby("date")["fire_count"].sum()
    date_activity = data["date"].map(daily_detection_counts)
    data["area_detection_count"] = date_activity
    eligible = date_activity.gt(0)
    missing_before_filter = int(data[GRID_FEATURES].isna().any(axis=1).sum())
    warmup_or_weather_rows = int((eligible & data[GRID_FEATURES].isna().any(axis=1)).sum())
    data = data.loc[eligible].dropna(subset=GRID_FEATURES).copy()
    data["data_source"] = "firms_open_meteo"
    data["negative_basis"] = np.where(
        data["label"].eq(0),
        "no_cell_detection_on_day_with_area_detections",
        "firms_hotspot_detection",
    )
    if data.empty:
        raise ValueError(
            "No grid-day examples remain after requiring actual FIRMS detections and "
            "complete lagged weather; no synthetic fallback is permitted."
        )
    stats = {
        "input_firms_rows": int(len(fires)),
        "firms_rows_with_valid_dates_and_coordinates": int(valid_coordinate_count),
        "firms_detections_outside_boundary_or_grid": int(
            valid_coordinate_count - total_detections
        ),
        "firms_detections_in_region_and_period": total_detections,
        "grid_cells": int(len(grid)),
        "grid_cell_degrees": float(step),
        "calendar_grid_rows": int(len(calendar)),
        "dates_with_area_detections": int(daily_detection_counts.gt(0).sum()),
        "weather_rows": int(len(weather_frame)),
        "weather_rows_with_missing_values": raw_weather_missing,
        "rows_with_missing_features_before_filter": missing_before_filter,
        "rows_removed_for_lag_warmup_or_weather_missing": warmup_or_weather_rows,
        "rows_after_filters": int(len(data)),
        "positive_grid_days": int(data["label"].sum()),
        "negative_grid_days": int((data["label"] == 0).sum()),
        "null_cells_after_filter": int(data[GRID_FEATURES].isna().sum().sum()),
        "negative_definition": (
            "A grid cell with no FIRMS detection on a date with at least one detection "
            "somewhere in the region; this is a coverage proxy, not proof of no fire."
        ),
    }
    return data, stats
