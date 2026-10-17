from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


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


def get_settings() -> Settings:
    return Settings(
        firms_key=os.getenv("MAP_KEY", "").strip(),
        firms_source=os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_SP").strip(),
        area=os.getenv("FIRMS_AREA", "-72.4287387,-13.3413977,-68.6519906,-9.9069082").strip(),
        latitude=float(os.getenv("METEO_LATITUDE", "-12.0")),
        longitude=float(os.getenv("METEO_LONGITUDE", "-70.25")),
        start_date=date.fromisoformat(os.getenv("START_DATE", "2024-10-10")),
        end_date=date.fromisoformat(os.getenv("END_DATE", "2026-10-10")),
        grid_cell_degrees=float(os.getenv("GRID_CELL_DEGREES", "0.25")),
    )
