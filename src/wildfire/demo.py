from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def make_demo_dataset(days: int = 1095, seed: int = 42) -> pd.DataFrame:
    if days < 20:
        raise ValueError("Demo data requires at least 20 days.")
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp("2025-12-31"), periods=days)
    day_of_year = dates.dayofyear.to_numpy()
    season = np.sin(2 * np.pi * (day_of_year - 105) / 365.25)
    temperature = 21 + 10 * season + rng.normal(0, 4, days)
    precipitation = np.maximum(0, rng.gamma(1.2, 2.0, days) - 1.5 * (season + 1))
    humidity = np.clip(66 - 16 * season + rng.normal(0, 10, days), 15, 100)
    wind = np.maximum(0, rng.normal(18, 7, days))
    logits = -3.5 + 0.12 * temperature - 0.055 * humidity - 0.16 * precipitation + 0.025 * wind
    probability = 1 / (1 + np.exp(-logits))
    label = rng.binomial(1, probability)
    if label.sum() < 5:
        hottest = np.argsort(temperature - humidity * 0.1)[-5:]
        label[hottest] = 1
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "temperature_2m_max": temperature.round(2),
            "relative_humidity_2m_mean": humidity.round(2),
            "precipitation_sum": precipitation.round(2),
            "wind_speed_10m_max": wind.round(2),
            "latitude": 40.4168,
            "longitude": -3.7038,
            "fire_count": label * rng.integers(1, 5, size=days),
            "label": label,
        }
    )


def save_demo_dataset(output: Path, days: int = 1095, seed: int = 42) -> pd.DataFrame:
    frame = make_demo_dataset(days=days, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
    return frame
