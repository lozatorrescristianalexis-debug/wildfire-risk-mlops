from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


REGION_PRESETS = {
    "madre_de_dios": {
        "name": "Madre de Dios",
        "state": "Madre de Dios",
        "country": "Peru",
        "area": "-72.4287387,-13.3413977,-68.6519906,-9.9069082",
        "latitude": -12.0,
        "longitude": -70.25,
        "grid_cell_degrees": 0.25,
        "weather_batch_size": 50,
        "weather_chunk_days": 180,
    },
    "peru": {
        "name": "Peru",
        "state": None,
        "country": "Peru",
        "area": "-81.33,-18.35,-68.65,-0.038",
        "latitude": -9.19,
        "longitude": -75.015,
        "grid_cell_degrees": 0.5,
        "weather_batch_size": 25,
        "weather_chunk_days": 180,
    },
}


@dataclass(frozen=True)
class Settings:
    firms_key: str = field(repr=False)
    firms_source: str
    area: str
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    grid_cell_degrees: float = 0.25
    request_timeout: int = 180
    region: str = "madre_de_dios"
    region_name: str = "Madre de Dios"
    region_state: str | None = "Madre de Dios"
    region_country: str = "Peru"
    weather_batch_size: int = 100
    weather_chunk_days: int = 180


def get_settings(region_override: str | None = None) -> Settings:
    configured_region = (os.getenv("REGION", "") or os.getenv("REGION_NAME", "")).strip().lower().replace(" ", "_")
    region_key = (
        region_override
        or configured_region
    ).strip().lower().replace(" ", "_")

    if not region_key or region_key not in REGION_PRESETS:
        preset = REGION_PRESETS["madre_de_dios"]
    else:
        preset = REGION_PRESETS[region_key]

    default_area = preset["area"]
    default_lat = preset["latitude"]
    default_lon = preset["longitude"]
    default_grid = preset["grid_cell_degrees"]
    default_batch = preset.get("weather_batch_size", 100)
    default_chunk_days = preset.get("weather_chunk_days", 180)

    # A command-line region selection must use that region's geography even
    # when .env contains custom coordinates for the configured region.
    use_configured_geography = region_override is None
    area = (os.getenv("FIRMS_AREA", default_area) if use_configured_geography else default_area).strip()
    latitude = float(os.getenv("METEO_LATITUDE", str(default_lat)) if use_configured_geography else default_lat)
    longitude = float(os.getenv("METEO_LONGITUDE", str(default_lon)) if use_configured_geography else default_lon)
    grid_cell_degrees = float(os.getenv("GRID_CELL_DEGREES", str(default_grid)) if use_configured_geography else default_grid)
    weather_batch_size = int(os.getenv("WEATHER_BATCH_SIZE", str(default_batch)) if use_configured_geography else default_batch)
    weather_chunk_days = int(os.getenv("WEATHER_CHUNK_DAYS", str(default_chunk_days)))

    return Settings(
        firms_key=os.getenv("MAP_KEY", "").strip(),
        firms_source=os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_SP").strip(),
        area=area,
        latitude=latitude,
        longitude=longitude,
        start_date=date.fromisoformat(os.getenv("START_DATE", "2024-10-10")),
        end_date=date.fromisoformat(os.getenv("END_DATE", "2026-10-10")),
        grid_cell_degrees=grid_cell_degrees,
        region=preset["name"].lower().replace(" ", "_"),
        region_name=preset["name"],
        region_state=preset["state"],
        region_country=preset["country"],
        weather_batch_size=weather_batch_size,
        weather_chunk_days=weather_chunk_days,
    )
