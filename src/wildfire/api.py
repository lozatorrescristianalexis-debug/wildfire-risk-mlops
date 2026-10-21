from __future__ import annotations

import json
import logging
import math
from datetime import date
from functools import lru_cache
from typing import Annotated

import joblib
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import ROOT
from .features import GRID_FEATURES
from .geography import REGIONS_PATH, region_at, region_catalog, region_data

MODEL_PATH = ROOT / "models" / "wildfire_real.joblib"
METRICS_PATH = ROOT / "reports" / "real_metrics.json"
WEB_PATH = ROOT / "web" / "index.html"
EXAMPLES_PATH = ROOT / "web" / "real_examples.json"
HISTORICAL_PATH = ROOT / "web" / "historical_fires.json"
REGION_WEATHER_PATH = ROOT / "web" / "region_weather.json"
logger = logging.getLogger("wildfire.api")
FEATURES = tuple(GRID_FEATURES)


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    date: date
    features: dict[str, Annotated[float, Field(allow_inf_nan=False)]]

    @model_validator(mode="after")
    def validate_feature_set(self) -> PredictRequest:
        missing = sorted(set(FEATURES) - self.features.keys())
        extra = sorted(self.features.keys() - set(FEATURES))
        if missing or extra:
            raise ValueError(
                f"features must match model inputs; missing={missing}, extra={extra}"
            )
        if any(not math.isfinite(value) for value in self.features.values()):
            raise ValueError("feature values must be finite numbers")
        return self


class Prediction(BaseModel):
    cell_id: str
    date: date
    probability: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    predicted_hotspot: bool
    model: str


class GridCellRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    latitude: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    longitude: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
    features: dict[str, Annotated[float, Field(allow_inf_nan=False)]] | None = None


class GridRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cells: list[GridCellRequest] = Field(max_length=2000)
    base_features: dict[str, Annotated[float, Field(allow_inf_nan=False)]] | None = None

    @model_validator(mode="after")
    def validate_weather_features(self) -> GridRequest:
        expected = set(FEATURES) - {"latitude", "longitude"}
        if self.base_features is not None:
            if set(self.base_features) != expected or any(cell.features is not None for cell in self.cells):
                raise ValueError("base_features must contain every weather feature and no cell overrides")
        elif any(cell.features is None or set(cell.features) != expected for cell in self.cells):
            raise ValueError("each cell must contain every weather feature exactly once")
        return self


@lru_cache(maxsize=1)
def _load_artifacts():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model artifact is missing: {MODEL_PATH}")
    if not METRICS_PATH.is_file():
        raise FileNotFoundError(f"Model metadata is missing: {METRICS_PATH}")
    bundle = joblib.load(MODEL_PATH)
    metadata = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    if bundle.get("data_source") != "firms_open_meteo":
        raise ValueError("The API requires a model trained on real FIRMS/Open-Meteo data.")
    if bundle.get("features") != list(FEATURES):
        raise ValueError("Model feature metadata does not match the API schema.")
    if bundle.get("training_region", "madre_de_dios") != metadata.get("training_region", "madre_de_dios"):
        raise ValueError("Model and metrics disagree about the training region.")
    return bundle, metadata


@lru_cache(maxsize=1)
def _historical_points() -> list[dict]:
    if not HISTORICAL_PATH.is_file():
        return []
    _, regions, _ = region_data()
    name_to_id = {item["name"].casefold(): key for key, item in regions.items()}
    points = json.loads(HISTORICAL_PATH.read_text(encoding="utf-8"))
    for item in points:
        original = item.get("region", "")
        preferred = name_to_id.get(original.casefold())
        mapped = region_at(item["latitude"], item["longitude"], preferred)
        item["mapped_region"] = mapped
        item["mapped_region_name"] = regions[mapped]["name"] if mapped else None
        item["coordinate_issue"] = "outside_peru" if mapped is None else (
            "label_mismatch" if mapped != preferred else None
        )
    return points


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wildfire Hotspot Classifier",
        description=(
            "Retrospective FIRMS cell-day classification from lagged weather. "
            "This API is not a fire forecast or operational alert."
        ),
        version="1.0.0",
    )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_PATH)

    @app.get("/health")
    def health():
        _load_artifacts()
        return {"status": "ok", "model_loaded": True}

    @app.get("/model-info")
    def model_info():
        bundle, metadata = _load_artifacts()
        return {
            "model": bundle["selected_model"],
            "data_source": metadata["data_source"],
            "training_region": metadata.get("training_region", "madre_de_dios"),
            "weather_sampling": metadata.get("weather_sampling"),
            "date_start": metadata["date_start"],
            "date_end": metadata["date_end"],
            "selected_threshold": float(bundle["threshold"]),
            "features": list(bundle["features"]),
            "test_metrics": metadata["test_metrics"],
            "calibration": metadata.get("calibration"),
            "regional_test_metrics": metadata.get("regional_test_metrics"),
            "regional_assignment": metadata.get("regional_assignment"),
        }

    @app.get("/examples/real")
    def real_examples():
        return json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))

    @app.post("/predict", response_model=Prediction)
    def predict(request: PredictRequest):
        bundle, _ = _load_artifacts()
        values = pd.DataFrame(
            [[request.features[name] for name in bundle["features"]]],
            columns=bundle["features"],
            dtype="float64",
        )
        probability = float(bundle["model"].predict_proba(values)[0, 1])
        threshold = float(bundle["threshold"])
        result = Prediction(
            cell_id=request.cell_id,
            date=request.date,
            probability=probability,
            threshold=threshold,
            predicted_hotspot=probability >= threshold,
            model=bundle["selected_model"],
        )
        logger.info(
            "prediction_completed cell_id=%s date=%s probability=%.6f threshold=%.6f",
            result.cell_id,
            result.date,
            result.probability,
            result.threshold,
        )
        return result

    @app.get("/app.css", include_in_schema=False)
    def app_css():
        css_file = ROOT / "web" / "app.css"
        if css_file.is_file():
            return FileResponse(css_file, media_type="text/css")
        return FileResponse(WEB_PATH)

    @app.get("/app.js", include_in_schema=False)
    def app_js():
        js_file = ROOT / "web" / "app.js"
        if js_file.is_file():
            return FileResponse(js_file, media_type="application/javascript")
        return FileResponse(WEB_PATH)

    @app.get("/api/regions", include_in_schema=False)
    def list_regions():
        return region_catalog()

    @app.get("/api/regions-geojson", include_in_schema=False)
    def region_geometries():
        return FileResponse(REGIONS_PATH, media_type="application/geo+json")

    @app.get("/api/region-weather", include_in_schema=False)
    def regional_weather_profiles():
        return FileResponse(REGION_WEATHER_PATH, media_type="application/json")

    @app.get("/api/historical-fires", include_in_schema=False)
    def historical_fires(region: str | None = None, min_confidence: str | None = None):
        data = _historical_points()
        selected = region.strip().lower() if region else None
        if selected == "peru":
            data = [item for item in data if item["mapped_region"] is not None]
        elif selected and selected != "all":
            data = [item for item in data if item["mapped_region"] == selected]
        if min_confidence:
            level = min_confidence.strip().lower()
            if level == "high":
                data = [item for item in data if item.get("confidence") == "high"]
            elif level == "nominal":
                data = [item for item in data if item.get("confidence") in ("high", "nominal")]
        return data

    @app.post("/api/predict-grid", include_in_schema=False)
    def predict_grid(payload: GridRequest):
        bundle, _ = _load_artifacts()
        cells = payload.cells
        base_features = payload.base_features
        if not cells:
            return {"results": [], "threshold": float(bundle["threshold"]), "model": bundle["selected_model"]}

        rows = []
        for cell in cells:
            row = {}
            for feat in bundle["features"]:
                if feat == "latitude":
                    row[feat] = cell.latitude
                elif feat == "longitude":
                    row[feat] = cell.longitude
                else:
                    weather = cell.features if cell.features is not None else base_features
                    row[feat] = weather[feat]
            rows.append(row)

        df = pd.DataFrame(rows, columns=bundle["features"], dtype="float64")
        probabilities = bundle["model"].predict_proba(df)[:, 1]
        threshold = float(bundle["threshold"])

        results = []
        for cell, prob in zip(cells, probabilities, strict=True):
            prob_float = float(prob)
            if prob_float >= 0.30:
                risk = "extreme"
            elif prob_float >= 0.15:
                risk = "high"
            elif prob_float >= 0.05:
                risk = "moderate"
            else:
                risk = "low"

            results.append({
                "cell_id": cell.cell_id,
                "latitude": cell.latitude,
                "longitude": cell.longitude,
                "probability": round(prob_float, 4),
                "threshold": threshold,
                "predicted_hotspot": bool(prob_float >= threshold),
                "risk_level": risk,
            })

        return {"results": results, "threshold": threshold, "model": bundle["selected_model"]}

    return app


app = create_app()
