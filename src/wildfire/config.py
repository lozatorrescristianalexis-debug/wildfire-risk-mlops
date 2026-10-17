from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    firms_key: str
    firms_source: str
    area: str
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    request_timeout: int = 30


def get_settings() -> Settings:
    start, end = latest_firms_dates()
    return Settings(
        firms_key=os.getenv("MAP_KEY", "").strip(),
        firms_source=os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT").strip(),
        area=os.getenv("FIRMS_AREA", "-5,36,4,44").strip(),
        latitude=float(os.getenv("METEO_LATITUDE", "40.4168")),
        longitude=float(os.getenv("METEO_LONGITUDE", "-3.7038")),
        start_date=date.fromisoformat(os.getenv("START_DATE", start.isoformat())),
        end_date=date.fromisoformat(os.getenv("END_DATE", end.isoformat())),
    )


def latest_firms_dates() -> tuple[date, date]:
    end = datetime.now(timezone.utc).date()
    return end - timedelta(days=9), end
