from fastapi.testclient import TestClient

from src.wildfire.api import FEATURES, app

client = TestClient(app)


def test_health_and_model_info_use_real_model_artifacts():
    health = client.get("/health")
    info = client.get("/model-info")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "model_loaded": True}
    assert info.status_code == 200
    assert info.json()["data_source"] == "firms_open_meteo"
    assert info.json()["model"] == "xgboost"
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


def test_frontend_is_served_in_english():
    response = client.get("/")

    assert response.status_code == 200
    assert "Wildfire Hotspot Classifier" in response.text
    assert "Get prediction" in response.text


def test_swagger_openapi_exposes_requested_routes():
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert set(response.json()["paths"]) == {"/health", "/model-info", "/predict"}
