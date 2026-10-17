import pandas as pd
import pytest

from src.wildfire.features import GRID_FEATURES
from src.wildfire.monitor import monitor_drift


def test_monitor_reports_shifted_recent_features(tmp_path):
    rows = []
    for day in range(120):
        shift = 10.0 if day >= 90 else 0.0
        for cell in ("cell_a", "cell_b"):
            rows.append(
                {
                    "date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=day),
                    "label": int(day % 10 == 0),
                    "data_source": "firms_open_meteo",
                    "cell_id": cell,
                    **{feature: shift + (day % 10) + 1.0 for feature in GRID_FEATURES},
                }
            )
    path = tmp_path / "real.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    report = monitor_drift(path)

    assert report["recent_window"]["rows"] == 60
    assert report["reference_window"]["rows"] == 180
    assert "temperature_2m_max_lag1" in report["drifted_features"]


def test_monitor_rejects_synthetic_input(tmp_path):
    path = tmp_path / "demo.csv"
    pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "label": 0,
                "data_source": "synthetic_demo",
            }
        ]
    ).to_csv(path, index=False)

    with pytest.raises(ValueError, match="refuses non-real"):
        monitor_drift(path)
