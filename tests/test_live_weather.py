"""Guard the daily feature window and live-weather API contract."""

from datetime import date, timedelta
import importlib

import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient

from src.wildfire.features import LAG_FEATURES, add_lagged_weather
from src.wildfire.geography import region_catalog
from src.wildfire.live_weather import (
    DAILY_FIELDS,
    build_live_profiles,
    features_from_previous_30_days,
)


def _weather_payload(today: date) -> list[dict]:
    dates = [(today - timedelta(days=30 - offset)).isoformat() for offset in range(31)]
    result = []
    for number, _ in enumerate(region_catalog()[1:]):
        result.append({
            "daily": {
                "time": dates,
                "temperature_2m_max": [23.0 + number / 10 + offset / 20 for offset in range(31)],
                "relative_humidity_2m_mean": [70.0 - offset / 10 for offset in range(31)],
                "precipitation_sum": [float(offset % 5) for offset in range(31)],
                "wind_speed_10m_max": [10.0 + offset / 10 for offset in range(31)],
            },
            "current": {
                "time": f"{today.isoformat()}T12:00",
                "temperature_2m": 24.0,
                "relative_humidity_2m": 66,
                "precipitation": 0.0,
                "wind_speed_10m": 11.0,
            },
        })
    return result


def test_next_day_features_match_training_windows():
    today = date(2026, 10, 21)
    source = _weather_payload(today)[0]["daily"]
    days = [
        {field: source[field][index] for field in DAILY_FIELDS}
        for index in range(1, 31)
    ]
    frame = pd.DataFrame([
        {"cell_id": "region", "date": (today - timedelta(days=29 - index)).isoformat(), **day}
        for index, day in enumerate(days)
    ] + [{"cell_id": "region", "date": (today + timedelta(days=1)).isoformat(),
          **{field: 0.0 for field in DAILY_FIELDS}}])
    expected = add_lagged_weather(frame).iloc[-1]
    actual = features_from_previous_30_days(days)
    assert set(actual) == set(LAG_FEATURES)
    for feature in LAG_FEATURES:
        assert actual[feature] == pytest.approx(expected[feature], abs=0.00005)


def test_live_weather_scenarios_change_only_today_and_target_tomorrow():
    today = date(2026, 10, 21)
    payload = _weather_payload(today)
    profiles = build_live_profiles(payload, today=today.isoformat(), retrieved_at=f"{today}T12:00:00-05:00")
    region = region_catalog()[1]["id"]
    assert profiles["weather_date"] == today.isoformat()
    assert profiles["target_date"] == (today + timedelta(days=1)).isoformat()
    assert len(profiles["profiles"]["today"]) == 25
    assert profiles["current"][region]["temperature_2m"] == 24.0

    normal = profiles["profiles"]["today"][region]
    rainy = profiles["profiles"]["rainy"][region]
    hot = profiles["profiles"]["hot"][region]
    assert normal["date"] == rainy["date"] == hot["date"] == profiles["target_date"]
    assert rainy["today_daily"]["precipitation_sum"] >= 20
    assert rainy["features"]["precipitation_sum_sum_30d"] > normal["features"]["precipitation_sum_sum_30d"]
    assert hot["today_daily"]["temperature_2m_max"] == pytest.approx(normal["today_daily"]["temperature_2m_max"] + 4)
    assert hot["features"]["temperature_2m_max_mean_7d"] > normal["features"]["temperature_2m_max_mean_7d"]
    assert hot["today_daily"]["precipitation_sum"] == 0

    payload[0]["daily"]["time"][-2] = "2026-10-31"
    with pytest.raises(ValueError, match="weather gap"):
        build_live_profiles(payload, today=today.isoformat(), retrieved_at=f"{today}T12:00:00-05:00")


def test_live_weather_endpoint_returns_profiles_and_handles_provider_failure(monkeypatch):
    api = importlib.import_module("src.wildfire.api")
    client = TestClient(api.app)
    payload = build_live_profiles(
        _weather_payload(date(2026, 10, 21)),
        today="2026-10-21",
        retrieved_at="2026-10-21T12:00:00-05:00",
    )
    monkeypatch.setattr(api, "load_live_weather", lambda: payload)
    response = client.get("/api/live-weather")
    assert response.status_code == 200
    assert response.json()["profiles"]["today"].keys() == payload["profiles"]["today"].keys()

    def unavailable():
        raise requests.Timeout("upstream timed out")

    monkeypatch.setattr(api, "load_live_weather", unavailable)
    assert client.get("/api/live-weather").status_code == 503


def test_local_cell_profiles_are_required_and_have_their_own_weather():
    today = date(2026, 10, 21)
    payload = _weather_payload(today)
    from copy import deepcopy
    local = deepcopy(payload[0])
    local["daily"]["temperature_2m_max"] = [8.0] * 31
    locations = [*region_catalog()[1:], {"id": "r008_c020", "center": [-14.1, -71.08]}]
    result = build_live_profiles([*payload, local], today=str(today), retrieved_at=str(today), locations=locations)
    assert result["profiles"]["today"]["r008_c020"]["features"]["temperature_2m_max_lag1"] == 8.0
    assert result["timezone"] == "UTC"
    with pytest.raises(ValueError, match="all requested"):
        build_live_profiles(payload, today=str(today), retrieved_at=str(today), locations=locations)
