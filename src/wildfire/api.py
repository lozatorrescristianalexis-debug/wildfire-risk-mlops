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

MODEL_PATH = ROOT / "models" / "wildfire_real.joblib"
METRICS_PATH = ROOT / "reports" / "real_metrics.json"
WEB_PATH = ROOT / "web" / "index.html"
EXAMPLES_PATH = ROOT / "web" / "real_examples.json"
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
    return bundle, metadata


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
            "date_start": metadata["date_start"],
            "date_end": metadata["date_end"],
            "selected_threshold": float(bundle["threshold"]),
            "features": list(bundle["features"]),
            "test_metrics": metadata["test_metrics"],
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

    return app


app = create_app()
