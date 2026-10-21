"""Observed regional weather profiles for the retrospective map."""

from __future__ import annotations

import pandas as pd

from .features import LAG_FEATURES, add_lagged_weather
from .geography import region_catalog


def build_region_weather_profiles(weather: pd.DataFrame) -> dict:
    history = add_lagged_weather(weather).dropna(subset=LAG_FEATURES)
    if history.empty:
        raise ValueError("Regional weather has no complete lagged observations.")
    profiles = {key: {} for key in ("observed", "dry", "wet")}
    latest_date = str(history["date"].max())

    for region in region_catalog()[1:]:
        rows = history.loc[history["cell_id"].eq(region["id"])].copy()
        if rows.empty or latest_date not in set(rows["date"].astype(str)):
            raise ValueError(f"Regional weather is incomplete for {region['id']}.")
        temperature_rank = rows["temperature_2m_max_lag1"].rank(pct=True)
        humidity_rank = rows["relative_humidity_2m_mean_lag1"].rank(pct=True)
        rainfall_rank = rows["precipitation_sum_sum_30d"].rank(pct=True)
        rows["dryness"] = temperature_rank - humidity_rank - rainfall_rank
        ordered = rows.sort_values("dryness").reset_index(drop=True)
        choices = {
            "observed": rows.loc[rows["date"].astype(str).eq(latest_date)].iloc[0],
            "dry": ordered.iloc[round((len(ordered) - 1) * 0.90)],
            "wet": ordered.iloc[round((len(ordered) - 1) * 0.10)],
        }
        for key, row in choices.items():
            profiles[key][region["id"]] = {
                "date": str(row["date"]),
                "features": {name: round(float(row[name]), 4) for name in LAG_FEATURES},
            }

    return {
        "observed_date": latest_date,
        "description": (
            "Historical Open-Meteo weather at 25 regional representative points. "
            "Dry and wet profiles use observed dates near each region's 90th and 10th "
            "dryness percentile; regions may use different dates. These are not forecasts."
        ),
        "profiles": profiles,
    }
