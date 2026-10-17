from datetime import date

import pandas as pd
import pytest
import requests

from src.wildfire.ingest import build_daily_dataset, fetch_firms, fetch_weather, normalize_firms


class Response:
    def __init__(self, text="", payload=None):
        self.text = text
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_firms_requires_api_key():
    with pytest.raises(ValueError, match="MAP_KEY"):
        fetch_firms("", "VIIRS_SNPP_NRT", "-5,36,4,44")


def test_fetch_firms_parses_csv_and_uses_timeout():
    session = Session(Response("acq_date,latitude\n2025-01-01,40.0\n"))
    result = fetch_firms("test-key", "VIIRS_SNPP_NRT", "-5,36,4,44", session=session)
    assert result.loc[0, "acq_date"] == "2025-01-01"
    assert session.calls[0][1]["timeout"] == 30
    assert "test-key" in session.calls[0][0]


def test_firms_request_errors_do_not_expose_api_key():
    class FailingResponse(Response):
        def raise_for_status(self):
            raise requests.ConnectionError("failed for https://example.invalid/test-key")

    with pytest.raises(RuntimeError, match="FIRMS request failed") as error:
        fetch_firms("test-key", "VIIRS_SNPP_NRT", "-5,36,4,44", session=Session(FailingResponse()))
    assert "test-key" not in str(error.value)


def test_normalize_firms_counts_observations_per_day():
    fires = pd.DataFrame({"acq_date": ["2025-01-01", "2025-01-01", "2025-01-03"]})
    result = normalize_firms(fires)
    assert result.to_dict("records") == [
        {"date": "2025-01-01", "fire_count": 2},
        {"date": "2025-01-03", "fire_count": 1},
    ]


def test_build_daily_dataset_labels_observed_and_unobserved_days():
    fires = pd.DataFrame({"acq_date": ["2025-01-02"]})
    weather = pd.DataFrame(
        {
            "date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "temperature_2m_max": [20, 21, 22],
            "relative_humidity_2m_mean": [50, 45, 40],
            "precipitation_sum": [0, 1, 0],
            "wind_speed_10m_max": [10, 11, 12],
        }
    )
    result = build_daily_dataset(fires, weather, date(2025, 1, 1), date(2025, 1, 3), 40, -3)
    assert result["label"].tolist() == [0, 1, 0]
    assert result["fire_count"].tolist() == [0, 1, 0]
    assert result.loc[0, "latitude"] == 40


def test_build_daily_dataset_rejects_missing_weather():
    weather = pd.DataFrame(
        {
            "date": ["2025-01-01"],
            "temperature_2m_max": [20],
            "relative_humidity_2m_mean": [50],
            "precipitation_sum": [0],
            "wind_speed_10m_max": [10],
        }
    )
    with pytest.raises(ValueError, match="Weather is missing"):
        build_daily_dataset(
            pd.DataFrame(columns=["acq_date"]),
            weather,
            date(2025, 1, 1),
            date(2025, 1, 2),
            40,
            -3,
        )


def test_fetch_weather_calls_archive_api():
    session = Session(
        Response(
            payload={
                "daily": {
                    "time": ["2025-01-01"],
                    "temperature_2m_max": [20],
                    "relative_humidity_2m_mean": [50],
                    "precipitation_sum": [0],
                    "wind_speed_10m_max": [10],
                }
            }
        )
    )
    result = fetch_weather(40, -3, date(2025, 1, 1), date(2025, 1, 1), session=session)
    assert len(result) == 1
    assert session.calls[0][1]["params"]["latitude"] == 40
