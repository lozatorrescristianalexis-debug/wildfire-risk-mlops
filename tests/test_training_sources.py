from datetime import date

import pytest

from src.wildfire.training_sources import sensor_windows


def test_standard_precedence_and_same_sensor_nrt_cover_entire_period():
    availability = {
        "VIIRS_SNPP_SP": (date(2012, 1, 1), date(2026, 6, 30)),
        "VIIRS_SNPP_NRT": (date(2026, 6, 1), date(2026, 10, 21)),
        "VIIRS_NOAA21_NRT": (date(2024, 1, 1), date(2026, 10, 21)),
    }
    assert sensor_windows("VIIRS_SNPP_SP", availability, date(2024, 10, 10), date(2026, 10, 10)) == [
        ("VIIRS_SNPP_SP", date(2024, 10, 10), date(2026, 6, 30)),
        ("VIIRS_SNPP_NRT", date(2026, 7, 1), date(2026, 10, 10)),
    ]
    availability["VIIRS_SNPP_NRT"] = (date(2026, 7, 5), date(2026, 10, 21))
    with pytest.raises(ValueError, match="Incomplete VIIRS_SNPP"):
        sensor_windows("VIIRS_SNPP_SP", availability, date(2024, 10, 10), date(2026, 10, 10))


def test_nrt_only_period_and_missing_availability():
    availability = {"MODIS_NRT": (date(2026, 8, 1), date(2026, 10, 21))}
    assert sensor_windows("MODIS_NRT", availability, date(2026, 9, 1), date(2026, 9, 4)) == [
        ("MODIS_NRT", date(2026, 9, 1), date(2026, 9, 4)),
    ]
    with pytest.raises(ValueError, match="Incomplete"):
        sensor_windows("MODIS_SP", {}, date(2026, 9, 1), date(2026, 9, 4))
