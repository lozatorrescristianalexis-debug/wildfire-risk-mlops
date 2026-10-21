"""Recent Open-Meteo weather and transparent next-day comparison profiles."""

from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta
from functools import lru_cache
from datetime import timezone

import requests

from .config import ROOT
from .features import LAG_FEATURES
from .geography import region_catalog

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = (
    "temperature_2m_max",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
)
CURRENT_FIELDS = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
)


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Open-Meteo returned invalid {field}.")
    return float(value)


def features_from_previous_30_days(days: list[dict[str, float]]) -> dict[str, float]:
    """Match the training lag-1 and trailing windows for a target day."""
    if len(days) != 30:
        raise ValueError("A next-day profile needs 30 complete previous days.")
    values = {field: [_finite_number(day[field], field) for day in days] for field in DAILY_FIELDS}
    temp = values["temperature_2m_max"]
    humidity = values["relative_humidity_2m_mean"]
    rain = values["precipitation_sum"]
    wind = values["wind_speed_10m_max"]
    features = {
        "temperature_2m_max_lag1": temp[-1],
        "relative_humidity_2m_mean_lag1": humidity[-1],
        "precipitation_sum_lag1": rain[-1],
        "wind_speed_10m_max_lag1": wind[-1],
        "temperature_2m_max_mean_3d": sum(temp[-3:]) / 3,
        "temperature_2m_max_mean_7d": sum(temp[-7:]) / 7,
        "relative_humidity_2m_mean_mean_7d": sum(humidity[-7:]) / 7,
        "wind_speed_10m_max_mean_7d": sum(wind[-7:]) / 7,
        "precipitation_sum_sum_3d": sum(rain[-3:]),
        "precipitation_sum_sum_7d": sum(rain[-7:]),
        "precipitation_sum_sum_30d": sum(rain),
    }
    return {field: round(features[field], 4) for field in LAG_FEATURES}


def _scenario_day(today: dict[str, float], scenario: str) -> dict[str, float]:
    day = today.copy()
    if scenario == "rainy":
        day["temperature_2m_max"] = round(day["temperature_2m_max"] - 2, 1)
        day["relative_humidity_2m_mean"] = max(day["relative_humidity_2m_mean"], 85.0)
        day["precipitation_sum"] = max(day["precipitation_sum"], 20.0)
    elif scenario == "hot":
        day["temperature_2m_max"] = round(day["temperature_2m_max"] + 4, 1)
        day["relative_humidity_2m_mean"] = max(10.0, day["relative_humidity_2m_mean"] - 15)
        day["precipitation_sum"] = 0.0
    return day


def build_live_profiles(payload: list[dict], *, today: str, retrieved_at: str, locations: list[dict] | None = None) -> dict:
    """Validate every training weather location and build next-day profiles."""
    regions = locations if locations is not None else region_catalog()[1:]
    if not isinstance(payload, list) or len(payload) != len(regions):
        raise ValueError("Open-Meteo did not return all requested weather locations.")
    target_date = (datetime.fromisoformat(today).date() + timedelta(days=1)).isoformat()
    profiles: dict[str, dict] = {key: {} for key in ("today", "rainy", "hot")}
    current: dict[str, dict] = {}

    for region, response in zip(regions, payload, strict=True):
        if not isinstance(response, dict):
            raise ValueError(f"Open-Meteo returned invalid data for {region['id']}.")
        daily = response.get("daily", {})
        if not isinstance(daily, dict):
            raise ValueError(f"Open-Meteo returned invalid daily values for {region['id']}.")
        dates = daily.get("time", [])
        if not isinstance(dates, list) or len(dates) != len(set(dates)) or today not in dates:
            raise ValueError(f"Open-Meteo returned incomplete dates for {region['id']}.")
        today_index = dates.index(today)
        if today_index < 29:
            raise ValueError(f"Open-Meteo needs 30 days through today for {region['id']}.")
        selected_dates = dates[today_index - 29:today_index + 1]
        expected_dates = [
            (datetime.fromisoformat(today).date() - timedelta(days=29 - offset)).isoformat()
            for offset in range(30)
        ]
        if selected_dates != expected_dates:
            raise ValueError(f"Open-Meteo returned a weather gap for {region['id']}.")
        if any(len(daily.get(field, [])) != len(dates) for field in DAILY_FIELDS):
            raise ValueError(f"Open-Meteo returned incomplete daily values for {region['id']}.")
        days = [
            {field: _finite_number(daily[field][index], field) for field in DAILY_FIELDS}
            for index in range(today_index - 29, today_index + 1)
        ]
        live = response.get("current", {})
        if not isinstance(live, dict):
            raise ValueError(f"Open-Meteo returned invalid current conditions for {region['id']}.")
        current_time = str(live.get("time", ""))
        if not current_time.startswith(today):
            raise ValueError(f"Open-Meteo current conditions are stale for {region['id']}.")
        current[region["id"]] = {
            "time": current_time,
            **{field: round(_finite_number(live.get(field), field), 2) for field in CURRENT_FIELDS},
        }
        for key in profiles:
            scenario_day = _scenario_day(days[-1], key)
            features = features_from_previous_30_days([*days[:-1], scenario_day])
            profiles[key][region["id"]] = {
                "date": target_date,
                "features": features,
                "today_daily": {field: round(scenario_day[field], 2) for field in DAILY_FIELDS},
            }

    return {
        "source": "Open-Meteo Forecast API",
        "timezone": "UTC",
        "source_url": "https://open-meteo.com/en/docs",
        "retrieved_at": retrieved_at,
        "weather_date": today,
        "target_date": target_date,
        "description": (
            "Current conditions are weather-model estimates; today's daily totals include the "
            "remaining-day forecast. The next-day model estimate uses today and 29 earlier days. "
            "Rainy and hot profiles modify today's values only and are hypothetical. "
            "This use has not been prospectively validated as a fire forecast."
        ),
        "current": current,
        "profiles": profiles,
    }


@lru_cache(maxsize=2)
def _load_live_weather_bucket(bucket: int) -> dict:
    snapshot = json.loads((ROOT / "web" / "region_weather.json").read_text(encoding="utf-8"))
    regions = [*region_catalog()[1:], *snapshot.get("local_locations", [])]
    params = {
        "latitude": ",".join(str(region["center"][0]) for region in regions),
        "longitude": ",".join(str(region["center"][1]) for region in regions),
        "daily": ",".join(DAILY_FIELDS),
        "current": ",".join(CURRENT_FIELDS),
        "timezone": "UTC",
        "past_days": 30,
        "forecast_days": 1,
    }
    response = requests.get(FORECAST_URL, params=params, timeout=25)
    response.raise_for_status()
    now = datetime.now(timezone.utc)
    return build_live_profiles(
        response.json(), today=now.date().isoformat(), retrieved_at=now.isoformat(timespec="seconds"),
        locations=regions
    )


def load_live_weather() -> dict:
    """Share one batched weather request per 15-minute cache interval."""
    return _load_live_weather_bucket(int(time.time() // 900))
