from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import requests

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_COLUMNS = (
    "temperature_2m_max",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
)


def fetch_firms(
    api_key: str,
    source: str,
    area: str,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("MAP_KEY is missing; add your NASA FIRMS key to the local .env file.")
    client = session or requests.Session()
    try:
        response = client.get(
            f"{FIRMS_URL}/{api_key}/{source}/{area}/10",
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise RuntimeError(
            f"FIRMS request failed with HTTP {status}; check the API key, source, and area."
        ) from None
    except requests.RequestException as exc:
        raise RuntimeError(
            f"FIRMS request failed ({type(exc).__name__}); check network and API settings."
        ) from None
    if not response.text.strip():
        raise ValueError("FIRMS returned an empty response.")
    from io import StringIO

    return pd.read_csv(StringIO(response.text))


def normalize_firms(fires: pd.DataFrame) -> pd.DataFrame:
    date_column = next(
        (name for name in ("acq_date", "scan_date", "date") if name in fires.columns),
        None,
    )
    if date_column is None:
        raise ValueError("FIRMS CSV must contain acq_date, scan_date, or date.")
    parsed_dates = pd.to_datetime(fires[date_column], errors="coerce", utc=True)
    valid = fires.loc[parsed_dates.notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["date", "fire_count"])
    valid["date"] = parsed_dates.loc[parsed_dates.notna()].dt.strftime("%Y-%m-%d")
    return (
        valid.groupby("date", as_index=False)
        .size()
        .rename(columns={"size": "fire_count"})
    )


def fetch_weather(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    client = session or requests.Session()
    response = client.get(
        WEATHER_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(WEATHER_COLUMNS),
            "timezone": "UTC",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "daily" not in payload or "time" not in payload["daily"]:
        raise ValueError("Open-Meteo response is missing daily weather data.")
    daily = payload["daily"]
    frame = pd.DataFrame({"date": daily["time"]})
    for column in WEATHER_COLUMNS:
        if column not in daily:
            raise ValueError(f"Open-Meteo response is missing {column}.")
        frame[column] = daily[column]
    return frame


def build_daily_dataset(
    fires: pd.DataFrame,
    weather: pd.DataFrame,
    start_date: date,
    end_date: date,
    latitude: float,
    longitude: float,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    dates = pd.DataFrame(
        {"date": pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d")}
    )
    fire_counts = normalize_firms(fires)
    merged = dates.merge(fire_counts, on="date", how="left")
    merged["fire_count"] = merged["fire_count"].astype("float64").fillna(0).astype("int64")
    merged = merged.merge(weather, on="date", how="left", validate="one_to_one")
    missing_weather = merged[list(WEATHER_COLUMNS)].isna().any(axis=1)
    if missing_weather.any():
        days = ", ".join(merged.loc[missing_weather, "date"].tolist())
        raise ValueError(f"Weather is missing for date(s): {days}")
    merged["latitude"] = latitude
    merged["longitude"] = longitude
    merged["label"] = (merged["fire_count"] > 0).astype("int64")
    return merged


def save_dataset(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
