import math
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point, shape

from src.wildfire.api import FEATURES, app

client = TestClient(app)


def test_health_and_model_info_use_real_model_artifacts():
    health = client.get("/health")
    info = client.get("/model-info")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "model_loaded": True}
    assert info.status_code == 200
    assert info.json()["data_source"] == "firms_open_meteo"
    assert info.json()["model"] == json.loads(
        Path("reports/real_metrics.json").read_text(encoding="utf-8")
    )["selected_model"]
    assert info.json()["training_region"] == "peru"
    assert info.json()["regional_test_metrics"]["ucayali"]["test_rows"] > 0
    assert "callao" in info.json()["regional_test_metrics"]
    if info.json()["regional_test_metrics"]["callao"]["grid_cells"] == 0:
        assert info.json()["regional_test_metrics"]["callao"]["metrics"] is None
    assert info.json()["features"] == list(FEATURES)


def test_prediction_returns_probability_threshold_and_cell():
    response = client.post(
        "/predict",
        json={
            "cell_id": "r013_c007",
            "date": "2026-10-10",
            "features": {feature: 0.0 for feature in FEATURES},
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["cell_id"] == "r013_c007"
    assert result["date"] == "2026-10-10"
    assert 0 <= result["probability"] <= 1
    assert result["threshold"] == client.get("/model-info").json()["selected_threshold"]
    assert isinstance(result["predicted_hotspot"], bool)


def test_real_holdout_examples_match_api_predictions():
    examples_response = client.get("/examples/real")

    assert examples_response.status_code == 200
    examples = examples_response.json()
    threshold = client.get("/model-info").json()["selected_threshold"]
    assert examples["positive"]["observed_hotspot"] is True
    assert examples["negative"]["observed_hotspot"] is False

    for kind, example in examples.items():
        response = client.post(
            "/predict",
            json={
                "cell_id": example["cell_id"],
                "date": example["date"],
                "features": example["features"],
            },
        )

        assert response.status_code == 200
        prediction = response.json()
        assert prediction["probability"] == pytest.approx(example["expected_probability"])
        assert prediction["threshold"] == threshold
        assert prediction["predicted_hotspot"] is example["observed_hotspot"]
        assert prediction["predicted_hotspot"] is (kind == "positive")


def test_prediction_rejects_missing_or_nonfinite_features():
    incomplete = client.post(
        "/predict",
        json={
            "cell_id": "r013_c007",
            "date": "2026-10-10",
            "features": {},
        },
    )
    nonfinite = client.post(
        "/predict",
        json={
            "cell_id": "r013_c007",
            "date": "2026-10-10",
            "features": {
                **{feature: 0.0 for feature in FEATURES},
                "latitude": "Infinity",
            },
        },
    )

    assert incomplete.status_code == 422
    assert nonfinite.status_code == 422


def test_frontend_and_its_assets_are_served():
    response = client.get("/")

    assert response.status_code == 200
    assert '<html lang="es">' in response.text
    assert "Vigía Fuego" in response.text
    assert "No es un pronóstico" in response.text
    assert client.get("/app.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_grid_prediction_matches_point_prediction_and_rejects_missing_weather():
    example = client.get("/examples/real").json()["positive"]
    features = example["features"]
    cell = {
        "cell_id": example["cell_id"],
        "latitude": features["latitude"],
        "longitude": features["longitude"],
    }
    weather = {name: value for name, value in features.items() if name not in ("latitude", "longitude")}
    grid = client.post("/api/predict-grid", json={"cells": [cell], "base_features": weather})
    point = client.post(
        "/predict",
        json={"cell_id": example["cell_id"], "date": example["date"], "features": features},
    )

    assert grid.status_code == 200
    assert grid.json()["results"][0]["probability"] == pytest.approx(
        point.json()["probability"], abs=0.00005
    )
    assert grid.json()["results"][0]["predicted_hotspot"] == point.json()["predicted_hotspot"]
    assert client.post(
        "/api/predict-grid", json={"cells": [cell], "base_features": {}}
    ).status_code == 422
    assert client.post(
        "/api/predict-grid", json={"cells": [{**cell, "latitude": 91}], "base_features": weather}
    ).status_code == 422


def test_regional_weather_grid_uses_cell_specific_historical_conditions():
    profile_response = client.get("/api/region-weather")
    assert profile_response.status_code == 200
    data = profile_response.json()
    regions = {region["id"]: region for region in client.get("/api/regions").json()[1:]}
    observed = data["profiles"]["observed"]
    assert set(observed) == set(regions)
    assert all(item["date"] == data["observed_date"] for item in observed.values())
    assert len({tuple(item["features"].values()) for item in observed.values()}) > 1

    cells = []
    for region_id in ("madre_de_dios", "piura"):
        latitude, longitude = regions[region_id]["center"]
        cells.append({
            "cell_id": region_id,
            "latitude": latitude,
            "longitude": longitude,
            "features": observed[region_id]["features"],
        })
    response = client.post("/api/predict-grid", json={"cells": cells})
    assert response.status_code == 200
    for cell, result in zip(cells, response.json()["results"], strict=True):
        point = client.post("/predict", json={
            "cell_id": cell["cell_id"],
            "date": data["observed_date"],
            "features": {
                **cell["features"],
                "latitude": cell["latitude"],
                "longitude": cell["longitude"],
            },
        })
        assert point.status_code == 200
        assert result["probability"] == pytest.approx(point.json()["probability"], abs=0.00005)
    assert client.post("/api/predict-grid", json={"cells": [{**cells[0], "features": {}}]}).status_code == 422


def test_region_catalog_is_complete_and_archive_points_follow_coordinates():
    regions = client.get("/api/regions").json()
    collection = client.get("/api/regions-geojson").json()
    by_id = {feature["properties"]["id"]: shape(feature["geometry"]) for feature in collection["features"]}

    assert len(regions) == 26  # Peru + 25 first-level regions, including Callao
    assert len(by_id) == 25
    assert {region["id"] for region in regions[1:]} == set(by_id)
    assert regions[0]["id"] == "peru"
    assert all(
        math.ceil((region["bbox"][2] - region["bbox"][0]) / region["grid_step"]) *
        math.ceil((region["bbox"][3] - region["bbox"][1]) / region["grid_step"]) <= 2000
        for region in regions
    )
    assert all(
        by_id[region["id"]].covers(Point(region["center"][1], region["center"][0]))
        for region in regions[1:]
    )
    callao = by_id["callao"]
    main_callao = max(callao.geoms, key=lambda part: part.area)
    callao_meta = next(region for region in regions if region["id"] == "callao")
    assert main_callao.covers(Point(callao_meta["center"][1], callao_meta["center"][0]))

    positive = client.get("/examples/real").json()["positive"]
    latitude = positive["features"]["latitude"]
    longitude = positive["features"]["longitude"]
    assert by_id[positive["region"]].covers(Point(longitude, latitude))
    assert not by_id[positive["region"]].covers(Point(latitude, longitude))

    archive = client.get("/api/historical-fires").json()
    assert any(point["coordinate_issue"] == "label_mismatch" for point in archive)
    assert any(point["coordinate_issue"] == "outside_peru" for point in archive)
    for point in archive:
        mapped = point["mapped_region"]
        if mapped:
            assert by_id[mapped].covers(Point(point["longitude"], point["latitude"]))
    madre_de_dios = client.get("/api/historical-fires?region=madre_de_dios").json()
    assert madre_de_dios
    assert all(point["mapped_region"] == "madre_de_dios" for point in madre_de_dios)

    country_points = client.get("/api/historical-fires?region=peru").json()
    assert len(country_points) == sum(point["mapped_region"] is not None for point in archive)
    assert all(point["mapped_region"] for point in country_points)


def test_swagger_openapi_exposes_requested_routes():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert set(response.json()["paths"]) == {
        "/health",
        "/model-info",
        "/examples/real",
        "/predict",
    }
