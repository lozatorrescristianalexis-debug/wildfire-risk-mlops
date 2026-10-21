from pathlib import Path

import pandas as pd
import pytest

from src.wildfire.regional_experiment import frozen_partitions, run_experiment, select_candidate


def test_frozen_split_keeps_every_cell_of_a_day_on_one_side():
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-02", "2025-01-03"]),
        "cell_id": ["a", "b", "a", "b", "a"],
    })
    train, test = frozen_partitions(frame, "2025-01-02")
    assert len(train) == 2 and len(test) == 3
    assert train.date.max() < test.date.min()
    assert set(train.date).isdisjoint(test.date)
    with pytest.raises(ValueError, match="cutoff"):
        frozen_partitions(frame, "2026-01-01")


def test_selection_cannot_use_better_test_metrics_to_override_development():
    candidates = {
        "best_development": {"selection": {"f1": .4, "pr_auc": .3}, "test": {"f1": .1}},
        "better_test": {"selection": {"f1": .3, "pr_auc": .9}, "test": {"f1": .99}},
    }
    assert select_candidate(candidates) == "best_development"
    candidates["better_test"]["test"]["f1"] = 1.0
    assert select_candidate(candidates) == "best_development"


def test_experiment_refuses_to_overwrite_production_or_data(tmp_path):
    data, model, metrics = [tmp_path / name for name in ("data.csv", "model.joblib", "metrics.json")]
    for target in (data, model, metrics):
        with pytest.raises(ValueError, match="overwrite"):
            run_experiment(data, model, metrics, target, Path("candidate.joblib"))
        with pytest.raises(ValueError, match="overwrite"):
            run_experiment(data, model, metrics, tmp_path / "report.json", target)
