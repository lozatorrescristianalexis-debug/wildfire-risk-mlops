from datetime import date

import pandas as pd
import pytest
import requests

from src.wildfire.config import get_settings
from src.wildfire.ingest import (
    FIRMS_MAX_DAYS_PER_REQUEST,
    build_daily_dataset,
    fetch_boundary_geojson,
    fetch_firms,
    fetch_firms_history,
    fetch_weather,
    fetch_weather_history,
    fetch_weather_grid_history,
    normalize_firms,
)
from src.wildfire.features import create_grid, engineer_grid_daily


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
    session = Session(Response("acq_date,latitude,longitude\n2025-01-01,-12,-70\n"))
    result = fetch_firms("test-key", "VIIRS_SNPP_SP", "-72,-13,-68,-9", session=session)
    assert result.loc[0, "acq_date"] == "2025-01-01"
    assert session.calls[0][1]["timeout"] == 120
    assert "test-key" in session.calls[0][0]


def test_firms_request_errors_do_not_expose_api_key():
    class FailingResponse(Response):
        def raise_for_status(self):
            raise requests.ConnectionError("failed for https://example.invalid/test-key")

    with pytest.raises(RuntimeError, match="FIRMS request failed") as error:
        fetch_firms("test-key", "VIIRS_SNPP_SP", "-72,-13,-68,-9", session=Session(FailingResponse()))
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
    assert set(result["data_source"]) == {"firms_open_meteo"}
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


def test_firms_historical_requests_are_chunked_to_api_limit():
    class DatedSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            chunk_date = url.rsplit("/", 1)[-1]
            return Response(f"acq_date,latitude,longitude\n{chunk_date},-12,-70\n")

    session = DatedSession()
    result = fetch_firms_history(
        "test-key",
        "VIIRS_SNPP_SP",
        "-72,-13,-68,-9",
        date(2024, 1, 1),
        date(2024, 1, 11),
        session=session,
    )
    assert FIRMS_MAX_DAYS_PER_REQUEST == 5
    assert len(session.calls) == 3
    assert [call[0].rsplit("/", 2)[-2] for call in session.calls] == ["5", "5", "1"]
    assert result["acq_date"].tolist() == ["2024-01-01", "2024-01-06", "2024-01-11"]


def test_weather_history_uses_bounded_requests():
    class DatedWeatherSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(kwargs["params"])
            start = pd.Timestamp(kwargs["params"]["start_date"])
            end = pd.Timestamp(kwargs["params"]["end_date"])
            dates = pd.date_range(start, end).strftime("%Y-%m-%d").tolist()
            return Response(
                payload={
                    "daily": {
                        "time": dates,
                        "temperature_2m_max": [20] * len(dates),
                        "relative_humidity_2m_mean": [50] * len(dates),
                        "precipitation_sum": [0] * len(dates),
                        "wind_speed_10m_max": [10] * len(dates),
                    }
                }
            )

    session = DatedWeatherSession()
    weather = fetch_weather_history(40, -3, date(2024, 1, 1), date(2024, 2, 1), session=session)
    assert len(session.calls) == 2
    assert [len(pd.date_range(call["start_date"], call["end_date"])) for call in session.calls] == [
        30,
        2,
    ]
    assert len(weather) == 32


def test_weather_grid_history_caches_completed_batches(tmp_path):
    class MultiLocationSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            params = kwargs["params"]
            self.calls.append(params)
            dates = pd.date_range(params["start_date"], params["end_date"]).strftime(
                "%Y-%m-%d"
            ).tolist()
            count = len(params["latitude"].split(","))
            return Response(
                payload=[
                    {
                        "daily": {
                            "time": dates,
                            "temperature_2m_max": [20] * len(dates),
                            "relative_humidity_2m_mean": [50] * len(dates),
                            "precipitation_sum": [0] * len(dates),
                            "wind_speed_10m_max": [10] * len(dates),
                        }
                    }
                    for _ in range(count)
                ]
            )

    grid = pd.DataFrame(
        {
            "cell_id": ["cell_a", "cell_b"],
            "latitude": [-12.0, -12.25],
            "longitude": [-70.0, -70.25],
        }
    )
    first_session = MultiLocationSession()
    first = fetch_weather_grid_history(
        grid,
        date(2025, 1, 1),
        date(2025, 1, 2),
        session=first_session,
        cache_dir=tmp_path,
    )
    second_session = MultiLocationSession()
    second = fetch_weather_grid_history(
        grid,
        date(2025, 1, 1),
        date(2025, 1, 2),
        session=second_session,
        cache_dir=tmp_path,
    )
    assert len(first_session.calls) == 1
    assert second_session.calls == []
    pd.testing.assert_frame_equal(first, second)


def test_grid_daily_features_are_lagged_and_negatives_require_area_activity(tmp_path):
    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
        '{"type":"Polygon","coordinates":[[[-72,-13],[-71,-13],[-71,-12],'
        '[-72,-12],[-72,-13]]]},"properties":{}}]}',
        encoding="utf-8",
    )
    grid = create_grid("-72,-13,-71,-12", 0.5, boundary)
    assert len(grid) == 4
    dates = pd.date_range("2024-01-01", periods=40).strftime("%Y-%m-%d")
    weather = pd.concat(
        [
            pd.DataFrame(
                {
                    "cell_id": cell.cell_id,
                    "date": dates,
                    "temperature_2m_max": range(40),
                    "relative_humidity_2m_mean": [50] * 40,
                    "precipitation_sum": [1] * 40,
                    "wind_speed_10m_max": [10] * 40,
                }
            )
            for cell in grid.itertuples()
        ],
        ignore_index=True,
    )
    cell = grid.iloc[0]
    fires = pd.DataFrame(
        {
            "acq_date": ["2024-02-05"],
            "latitude": [cell.latitude],
            "longitude": [cell.longitude],
            "firms_source": ["VIIRS_SNPP_SP"],
        }
    )
    dataset, stats = engineer_grid_daily(
        fires, weather, grid, "2024-01-01", "2024-02-09", boundary
    )
    assert set(dataset["date"]) == {"2024-02-05"}
    assert dataset["label"].sum() == 1
    assert (dataset["label"] == 0).sum() == 3
    assert dataset["temperature_2m_max_lag1"].eq(34).all()
    assert dataset["precipitation_sum_sum_30d"].eq(30).all()
    assert dataset["data_source"].eq("firms_open_meteo").all()
    assert dataset.loc[dataset["label"].eq(1), "firms_sources"].eq("VIIRS_SNPP_SP").all()
    assert stats["null_cells_after_filter"] == 0


def test_grid_daily_records_sensor_provenance_for_positive_and_negative_rows(tmp_path):
    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
        '{"type":"Polygon","coordinates":[[[-72,-13],[-71,-13],[-71,-12],'
        '[-72,-12],[-72,-13]]]},"properties":{}}]}',
        encoding="utf-8",
    )
    grid = create_grid("-72,-13,-71,-12", 0.5, boundary)
    dates = pd.date_range("2024-01-01", periods=40).strftime("%Y-%m-%d")
    weather = pd.concat(
        [
            pd.DataFrame(
                {
                    "cell_id": cell.cell_id,
                    "date": dates,
                    "temperature_2m_max": [20] * 40,
                    "relative_humidity_2m_mean": [50] * 40,
                    "precipitation_sum": [0] * 40,
                    "wind_speed_10m_max": [10] * 40,
                }
            )
            for cell in grid.itertuples()
        ],
        ignore_index=True,
    )
    cell = grid.iloc[0]
    fires = pd.DataFrame(
        {
            "acq_date": ["2024-02-05", "2024-02-05"],
            "latitude": [cell.latitude, cell.latitude],
            "longitude": [cell.longitude, cell.longitude],
            "firms_source": ["VIIRS_NOAA21_NRT", "MODIS_NRT"],
        }
    )

    dataset, _ = engineer_grid_daily(
        fires, weather, grid, "2024-01-01", "2024-02-09", boundary
    )

    positive_sources = dataset.loc[dataset["label"].eq(1), "firms_sources"]
    negative_sources = dataset.loc[dataset["label"].eq(0), "firms_sources"]
    assert positive_sources.eq("MODIS_NRT|VIIRS_NOAA21_NRT").sum() == 1
    assert negative_sources.eq("none").all()


def test_get_settings_region_presets(monkeypatch):
    monkeypatch.delenv("REGION", raising=False)
    monkeypatch.delenv("REGION_NAME", raising=False)
    monkeypatch.delenv("FIRMS_AREA", raising=False)
    monkeypatch.delenv("GRID_CELL_DEGREES", raising=False)
    default_settings = get_settings()
    assert default_settings.region == "madre_de_dios"
    assert default_settings.grid_cell_degrees == 0.25

    peru_settings = get_settings(region_override="peru")
    assert peru_settings.region == "peru"
    assert peru_settings.grid_cell_degrees == 0.5
    assert "-81.33" in peru_settings.area
    assert peru_settings.weather_batch_size == 25
    assert peru_settings.weather_chunk_days == 180


def test_border_grid_sample_is_inside_boundary(tmp_path):
    from shapely.geometry import Point, box, mapping
    import json

    boundary = box(-72, -13, -71.9, -12.9)
    path = tmp_path / "edge.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(boundary)}
    ]}))
    grid = create_grid("-72,-13,-71,-12", 0.5, path)
    assert len(grid) == 1
    assert boundary.covers(Point(grid.iloc[0]["longitude"], grid.iloc[0]["latitude"]))


def test_explicit_peru_region_ignores_madre_de_dios_geometry_in_env(monkeypatch):
    monkeypatch.setenv("REGION", "madre_de_dios")
    monkeypatch.setenv("FIRMS_AREA", "-72.4,-13.3,-68.7,-9.9")
    monkeypatch.setenv("GRID_CELL_DEGREES", "0.25")
    monkeypatch.setenv("METEO_LATITUDE", "-12")
    monkeypatch.setenv("METEO_LONGITUDE", "-70")

    settings = get_settings(region_override="peru")
    assert settings.area == "-81.33,-18.35,-68.65,-0.038"
    assert settings.grid_cell_degrees == 0.5
    assert settings.latitude == -9.19
    assert settings.longitude == -75.015

    monkeypatch.setenv("REGION", "peru")
    assert get_settings(region_override="peru").area == settings.area


def test_fetch_boundary_geojson_queries_country(tmp_path):
    class CountryResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-80, -15], [-70, -15], [-70, -5], [-80, -5], [-80, -15]]],
                        },
                    }
                ],
            }

    out_file = tmp_path / "peru_boundary.geojson"
    from unittest.mock import patch
    with patch("requests.get", return_value=CountryResponse()):
        path = fetch_boundary_geojson(out_file, state=None, country="Peru")
        assert path.exists()


def test_weather_grid_history_chunk_days_large_block(tmp_path):
    class LongChunkSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            params = kwargs["params"]
            self.calls.append(params)
            dates = pd.date_range(params["start_date"], params["end_date"]).strftime("%Y-%m-%d").tolist()
            count = len(params["latitude"].split(","))
            return Response(
                payload=[
                    {
                        "daily": {
                            "time": dates,
                            "temperature_2m_max": [20] * len(dates),
                            "relative_humidity_2m_mean": [50] * len(dates),
                            "precipitation_sum": [0] * len(dates),
                            "wind_speed_10m_max": [10] * len(dates),
                        }
                    }
                    for _ in range(count)
                ]
            )

    grid = pd.DataFrame(
        {
            "cell_id": ["c1", "c2"],
            "latitude": [-10.0, -11.0],
            "longitude": [-75.0, -76.0],
        }
    )
    session = LongChunkSession()
    # 60 days with chunk_days=90 should be 1 call instead of 2!
    result = fetch_weather_grid_history(
        grid,
        date(2025, 1, 1),
        date(2025, 3, 1),
        session=session,
        batch_size=10,
        chunk_days=90,
        cache_dir=tmp_path,
    )
    assert len(session.calls) == 1
    assert len(result) == 60 * 2


def test_weather_grid_splits_rate_limited_block_and_caches_result(tmp_path, monkeypatch):
    monkeypatch.setattr("src.wildfire.ingest.WEATHER_MIN_REQUEST_INTERVAL", 0)

    class AdaptiveSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            params = kwargs["params"]
            self.calls.append((params["start_date"], params["end_date"]))
            dates = pd.date_range(params["start_date"], params["end_date"])
            if len(dates) > 30:
                response = requests.Response()
                response.status_code = 429
                return response
            return Response(payload=[{"daily": {
                "time": dates.strftime("%Y-%m-%d").tolist(),
                "temperature_2m_max": [20] * len(dates),
                "relative_humidity_2m_mean": [50] * len(dates),
                "precipitation_sum": [0] * len(dates),
                "wind_speed_10m_max": [10] * len(dates),
            }}])

    grid = pd.DataFrame({"cell_id": ["c1"], "latitude": [-12.0], "longitude": [-70.0]})
    session = AdaptiveSession()
    first = fetch_weather_grid_history(
        grid, date(2025, 1, 1), date(2025, 3, 1),
        session=session, chunk_days=90, cache_dir=tmp_path,
    )
    assert len(first) == 60
    assert len(session.calls) == 3
    second = fetch_weather_grid_history(
        grid, date(2025, 1, 1), date(2025, 3, 1),
        session=session, chunk_days=90, cache_dir=tmp_path,
    )
    assert len(session.calls) == 3
    pd.testing.assert_frame_equal(first, second)
