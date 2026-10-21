"""Stable sensor identity across standard and near-real-time FIRMS archives."""
from datetime import date, timedelta


def sensor_windows(source: str, availability: dict, start: date, end: date) -> list[tuple[str, date, date]]:
    """Prefer standard processing, then NRT of the SAME satellite; fail on gaps.

    Availability means a product can be queried, not that every cell was observed.
    A different satellite must never silently change the training target mid-period.
    """
    if start > end:
        raise ValueError("Training start must precede end.")
    if not source.endswith(("_SP", "_NRT")):
        raise ValueError("Choose a FIRMS satellite product ending in _SP or _NRT.")
    sensor = source.rsplit("_", 1)[0]
    cursor = start
    windows = []
    for product in (f"{sensor}_SP", f"{sensor}_NRT"):
        if product not in availability:
            continue
        first, last = availability[product]
        if first <= cursor <= last:
            stop = min(end, last)
            windows.append((product, cursor, stop))
            cursor = stop + timedelta(days=1)
        if cursor > end:
            return windows
    raise ValueError(f"Incomplete {sensor} product availability from {cursor} through {end}; training aborted.")
