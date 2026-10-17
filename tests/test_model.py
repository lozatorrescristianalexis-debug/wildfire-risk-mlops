import json

import pandas as pd
import pytest

from src.wildfire.demo import make_demo_dataset, save_demo_dataset
from src.wildfire.model import load_training_data, predict_latest, train_model


def test_demo_data_is_reproducible_and_has_both_classes():
    first = make_demo_dataset(days=300, seed=11)
    second = make_demo_dataset(days=300, seed=11)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["label"]) == {0, 1}
    assert len(first) == 300


def test_training_saves_model_metrics_and_prediction(tmp_path):
    data_path = tmp_path / "daily.csv"
    model_path = tmp_path / "model.joblib"
    metrics_path = tmp_path / "metrics.json"
    save_demo_dataset(data_path, days=400, seed=42)

    metrics = train_model(data_path, model_path, metrics_path, allow_demo=True)
    prediction = predict_latest(model_path, data_path, allow_demo=True)

    assert model_path.exists()
    assert json.loads(metrics_path.read_text(encoding="utf-8"))["rows"] == 400
    assert metrics["test_rows"] == 80
    assert metrics["data_source"] == "synthetic_demo"
    assert 0 <= metrics["roc_auc"] <= 1
    assert prediction["predicted_hotspot"] in (0, 1)
    assert prediction["observed_hotspot"] in (0, 1)
    assert "not a future fire forecast" in prediction["note"]


def test_training_rejects_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="Run `make data`"):
        load_training_data(tmp_path / "missing.csv")


def test_demo_data_cannot_be_used_for_final_training(tmp_path):
    path = tmp_path / "demo.csv"
    save_demo_dataset(path, days=50)
    with pytest.raises(ValueError, match="cannot be used for final training"):
        train_model(path, tmp_path / "model.joblib", tmp_path / "metrics.json")


def test_cli_defaults_to_real_paths_separate_from_demo():
    from src.wildfire.cli import DATA_PATH, DEMO_DATA_PATH, METRICS_PATH, MODEL_PATH

    assert DATA_PATH.parts[-3:] == ("data", "processed", "real_daily.csv")
    assert DEMO_DATA_PATH.parts[-3:] == ("data", "demo", "daily.csv")
    assert DATA_PATH != DEMO_DATA_PATH
    assert MODEL_PATH.name == "wildfire_real.joblib"
    assert METRICS_PATH.name == "real_metrics.json"


def test_training_requires_both_classes_in_chronological_split(tmp_path):
    path = tmp_path / "invalid.csv"
    frame = make_demo_dataset(days=40, seed=42)
    frame["label"] = 0
    frame["fire_count"] = 0
    frame.loc[0, "label"] = 1
    frame.loc[0, "fire_count"] = 1
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="both classes"):
        train_model(path, tmp_path / "model.joblib", tmp_path / "metrics.json", allow_demo=True)
