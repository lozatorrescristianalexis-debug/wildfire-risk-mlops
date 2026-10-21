"""Lossless map observations, independent from the cell-day training dataset.

A published, compressed snapshot is immutable to readers. Updates are atomic;
network failures never replace the last valid observations with an empty file.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import gzip
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

import numpy as np
import pandas as pd
import requests
from shapely import covers, points

from .config import ROOT, get_settings
from .geography import region_data
from .ingest import _parse_firms_response, _request_firms_csv, fetch_firms_history

BUNDLED_PATH = ROOT / "web" / "fire_observations.json.gz"
SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
IDENTITY = ["acq_date", "acq_time", "latitude", "longitude", "satellite", "instrument"]
_SNAPSHOT_LOCK = threading.RLock()
PUBLIC_CSV = {
    "VIIRS_SNPP_NRT": ("suomi-npp-viirs-c2", "SUOMI_VIIRS_C2"),
    "VIIRS_NOAA20_NRT": ("noaa-20-viirs-c2", "J1_VIIRS_C2"),
    "VIIRS_NOAA21_NRT": ("noaa-21-viirs-c2", "J2_VIIRS_C2"),
    "MODIS_NRT": ("modis-c6.1", "MODIS_C6_1"),
}


def snapshot_path() -> Path:
    return Path(os.getenv("WILDFIRE_OBSERVATIONS_PATH", str(BUNDLED_PATH)))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_observations(frames: list[pd.DataFrame]) -> tuple[list[dict], dict]:
    """Keep exact coordinates and overpass time; never snap points to a grid."""
    nonempty = [f for f in frames if not f.empty]
    if not nonempty:
        return [], {"input_rows": 0, "invalid_rows": 0, "outside_peru": 0, "duplicates_removed": 0}
    data = pd.concat(nonempty, ignore_index=True).copy()
    input_rows = len(data)
    for required in ("latitude", "longitude", "acq_date"):
        if required not in data:
            raise ValueError(f"Missing observation column: {required}")
    for column in ("latitude", "longitude"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    dates = pd.to_datetime(data.acq_date, errors="coerce", utc=True)
    valid = (data.latitude.between(-90, 90) & data.longitude.between(-180, 180)
             & dates.notna() & (dates.dt.date <= datetime.now(timezone.utc).date()))
    invalid_rows = int((~valid).sum())
    data = data.loc[valid].copy()
    data["acq_date"] = dates.loc[valid].dt.strftime("%Y-%m-%d")
    defaults = {"acq_time": "", "satellite": "unknown", "instrument": "unknown",
                "confidence": "unknown", "source": "local_csv", "frp": None}
    for key, default in defaults.items():
        if key not in data:
            data[key] = default
    for key in ("satellite", "instrument", "source"):
        data[key] = data[key].fillna(defaults[key]).astype(str)
    data["instrument"] = data.instrument.str.upper()
    data["satellite"] = data.satellite.str.strip().replace({"Suomi NPP": "N", "SNPP": "N", "NOAA-20": "N20", "NOAA-21": "N21"})
    # Missing time remains unknown, never fabricated as a midnight pass.
    times = pd.to_numeric(data.acq_time, errors="coerce")
    valid_time = times.notna() & (times % 1 == 0) & times.between(0, 2359) & (times % 100 < 60)
    data["acq_time"] = ""
    data.loc[valid_time, "acq_time"] = times[valid_time].astype(int).astype(str).str.zfill(4)
    raw_conf = data.confidence.fillna("unknown").astype(str).str.lower().str.strip()
    numeric = pd.to_numeric(raw_conf, errors="coerce")
    conf = raw_conf.replace({"h": "high", "n": "nominal", "l": "low"})
    modis = (data.instrument == "MODIS") & numeric.between(0, 100)
    conf.loc[modis] = np.where(numeric[modis] >= 80, "high", np.where(numeric[modis] >= 30, "nominal", "low"))
    data["confidence"] = conf.where(conf.isin(["high", "nominal", "low"]), "unknown")
    data["frp"] = pd.to_numeric(data.frp, errors="coerce")
    data.loc[~np.isfinite(data.frp) | (data.frp < 0), "frp"] = np.nan
    # Prefer standard processing for identical observations, preserving attribution.
    data["_priority"] = ~data.source.str.contains("_SP", regex=False)
    data = data.sort_values("_priority", kind="stable")
    duplicates = int(data.duplicated(IDENTITY).sum())
    if duplicates:
        attributions = data.groupby(IDENTITY, dropna=False, sort=False).source.agg(
            lambda values: "|".join(sorted({s for value in values for s in value.split("|")})))
        unique = data.drop_duplicates(IDENTITY).drop(columns=["source", "_priority"])
        data = unique.merge(attributions.rename("source"), on=IDENTITY, how="left", validate="one_to_one")
    else:
        data = data.drop(columns="_priority")
    _, regions, _ = region_data()
    geometry = points(data.longitude.to_numpy(), data.latitude.to_numpy())
    data["mapped_region"] = None
    data["mapped_region_name"] = None
    for region_id, region in regions.items():
        mask = covers(region["geometry"], geometry) & data.mapped_region.isna().to_numpy()
        data.loc[mask, "mapped_region"] = region_id
        data.loc[mask, "mapped_region_name"] = region["name"]
    outside = int(data.mapped_region.isna().sum())
    # Preserve outside points for explicit inspection (region=all); default UI is Peru.
    data["id"] = [hashlib.sha256(json.dumps(row, separators=(",", ":")).encode()).hexdigest()[:24]
                  for row in data[IDENTITY].itertuples(index=False, name=None)]
    data = data.sort_values(["acq_date", "acq_time", "id"], ascending=[False, False, True])
    columns = ["id", *IDENTITY, "confidence", "frp", "source", "mapped_region", "mapped_region_name"]
    records = json.loads(data[columns].to_json(orient="records", double_precision=15))
    return records, {"input_rows": input_rows, "invalid_rows": invalid_rows,
                     "outside_peru": outside, "duplicates_removed": duplicates}


def build_snapshot(frames: list[pd.DataFrame], *, source_kind: str, refresh: dict | None = None) -> dict:
    records, audit = normalize_observations(frames)
    dates = [row["acq_date"] for row in records]
    source_counts = Counter(source for row in records for source in row["source"].split("|"))
    generated_at = utc_now()
    metadata = {**audit, "total_records": len(records), "date_start": min(dates, default=None),
                "date_end": max(dates, default=None), "last_detection": max(dates, default=None),
                "generated_at": generated_at, "source_kind": source_kind, "source_counts": dict(source_counts),
                "status": "archive", "refresh": refresh or {},
                "coverage_note": "Counts describe returned observations, not satellite coverage or absence of fire."}
    return {"schema_version": 1,
            "snapshot_id": hashlib.sha256((generated_at + json.dumps(records)).encode()).hexdigest()[:20],
            "metadata": metadata, "items": records}


def _atomic_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.chmod(name, 0o644)  # Public data must remain readable by the Docker runtime user.
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def publish_snapshot(snapshot: dict, path: Path) -> None:
    if not snapshot["items"]:
        raise ValueError("Refusing to replace the last valid snapshot with an empty archive.")
    encoded = gzip.compress(json.dumps(snapshot, separators=(",", ":"), allow_nan=False).encode(), mtime=0)
    # Back up only a readable, valid snapshot, not a corrupted current file.
    if path.is_file():
        try:
            _read_snapshot(path, path.stat().st_mtime_ns, path.stat().st_size)
        except (ValueError, OSError, EOFError, KeyError):
            pass
        else:
            _atomic_bytes(path.with_suffix(path.suffix + ".previous"), path.read_bytes())
    _atomic_bytes(path, encoded)


def _compact_record(record: dict) -> dict:
    # Hundreds of thousands of observations share the same dates, sensors and
    # regions. Share those strings during decoding, before retaining the archive.
    if "acq_date" in record:
        for key in ("acq_date", "acq_time", "satellite", "instrument", "confidence",
                    "source", "mapped_region", "mapped_region_name"):
            if isinstance(record.get(key), str):
                record[key] = sys.intern(record[key])
    return record


@lru_cache(maxsize=1)
def _read_snapshot(path: Path, mtime: int, size: int) -> dict:
    # On a version change release the former large archive before decoding.
    _read_snapshot.cache_clear()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle, object_hook=_compact_record)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("snapshot_id"), str)
            or not isinstance(data.get("metadata"), dict)
            or not isinstance(data.get("items"), list)
            or not data["items"] or data["metadata"]["total_records"] != len(data["items"])):
        raise ValueError("Invalid observations snapshot")
    return data


def load_snapshot(path: Path | None = None) -> dict:
    path = path or snapshot_path()
    candidates = [path, path.with_suffix(path.suffix + ".previous")]
    if path != BUNDLED_PATH:
        candidates.append(BUNDLED_PATH)
    for candidate in candidates:
        try:
            stat = candidate.stat()
            with _SNAPSHOT_LOCK:
                data = _read_snapshot(candidate, stat.st_mtime_ns, stat.st_size)
        except (ValueError, OSError, EOFError, KeyError):
            continue
        metadata = dict(data["metadata"])
        metadata["serving_fallback"] = candidate != path
        try:
            metadata["refresh"] = json.loads(path.with_suffix(path.suffix + ".status.json").read_text())
        except (ValueError, OSError):
            pass
        latest = metadata.get("last_detection")
        metadata["age_days"] = (datetime.now(timezone.utc).date() - date.fromisoformat(latest)).days if latest else None
        metadata["status"] = "fallback" if candidate != path else (
            "stale" if metadata["age_days"] is None or metadata["age_days"] > 2 else "recent")
        return {**data, "metadata": metadata}
    raise FileNotFoundError("No valid observations snapshot. Run python -m src.wildfire.observations build-local.")


def fetch_availability(api_key: str, session: requests.Session) -> dict:
    text = _request_firms_csv(session,
        f"https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{api_key}/ALL", api_key, 30)
    frame = pd.read_csv(StringIO(text))
    if not {"data_id", "min_date", "max_date"}.issubset(frame.columns):
        raise ValueError("Invalid FIRMS availability response")
    return {str(row.data_id).upper(): (date.fromisoformat(str(row.min_date)[:10]), date.fromisoformat(str(row.max_date)[:10]))
            for row in frame.itertuples()}


def fetch_public_csv(source: str, session: requests.Session) -> pd.DataFrame:
    product, prefix = PUBLIC_CSV[source]
    url = f"https://firms.modaps.eosdis.nasa.gov/data/active_fire/{product}/csv/{prefix}_South_America_7d.csv"
    return _parse_firms_response(_request_firms_csv(session, url, "", 45))


def refresh_observations(path: Path, *, api_key: str, days: int = 7, session=None) -> dict:
    """Query every sensor, use official regional CSV on failure, retain archive.

    Empty validated responses are successful queries; they are never interpreted
    as missing coverage. Neither sensor failure nor a short window erases history.
    """
    client = session or requests.Session()
    report = {"attempted_at": utc_now(), "status": "offline", "sources": {}, "requested_days": days}
    frames = []
    try:
        previous = load_snapshot(path)
        frames.append(pd.DataFrame(previous["items"]))
    except FileNotFoundError:
        previous = None
    try:
        availability = fetch_availability(api_key, client) if api_key else {}
    except (ValueError, RuntimeError, requests.RequestException):
        availability = {}
        report["availability_error"] = "Availability service unavailable; using bounded recent queries."
    today = datetime.now(timezone.utc).date()
    bbox = ",".join(str(v) for v in region_data()[2].bounds)
    successful = 0
    added = 0
    try:
        for source in SOURCES:
            entry = {"status": "failed", "method": None, "rows": 0}
            end = min(today, availability.get(source, (today - timedelta(days=days-1), today))[1])
            start = max(end - timedelta(days=days-1), availability.get(source, (end - timedelta(days=days-1), end))[0])
            entry.update(requested_start=start.isoformat(), requested_end=end.isoformat())
            frame = None
            if api_key:
                try:
                    frame = fetch_firms_history(api_key, source, bbox, start, end, timeout=30, session=client)
                    entry["method"] = "area_api"
                except (ValueError, RuntimeError, requests.RequestException):
                    entry["api_error"] = "Area API unavailable or invalid response."
            if frame is None:
                try:
                    frame = fetch_public_csv(source, client)
                    entry["method"] = "official_csv_7d"
                    # Public feed is rolling; never label it as an older API interval.
                    entry.update(requested_start=(today - timedelta(days=6)).isoformat(), requested_end=today.isoformat())
                except (ValueError, RuntimeError, requests.RequestException):
                    entry["fallback_error"] = "Official regional CSV unavailable or invalid response."
            if frame is not None:
                frame = frame.copy()
                west, south, east, north = region_data()[2].bounds
                lat = pd.to_numeric(frame.latitude, errors="coerce")
                lon = pd.to_numeric(frame.longitude, errors="coerce")
                dates = pd.to_datetime(frame.acq_date, errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
                valid = lat.between(-90, 90) & lon.between(-180, 180) & dates.notna()
                if len(frame) and not valid.any():
                    entry["fallback_error"] = "All returned observations failed coordinate/date validation."
                    report["sources"][source] = entry
                    continue
                frame = frame.loc[lat.between(south, north) & lon.between(west, east)
                                  & dates.between(entry["requested_start"], entry["requested_end"])].copy()
                frame["source"] = source
                if "instrument" not in frame:
                    frame["instrument"] = "MODIS" if source.startswith("MODIS") else "VIIRS"
                normalized, audit = normalize_observations([frame])
                # Malformed non-empty data must not be counted as a successful empty query.
                if len(frame) and not normalized:
                    entry["fallback_error"] = "All returned observations failed validation."
                else:
                    successful += 1
                    added += len(normalized)
                    frames.append(pd.DataFrame(normalized))
                    entry.update(status="ok" if normalized else "empty", rows=len(normalized),
                                 latest_detection=max((row["acq_date"] for row in normalized), default=None),
                                 invalid_rows=audit["invalid_rows"])
            report["sources"][source] = entry
        report["status"] = "ok" if successful == len(SOURCES) else "partial" if successful else "offline"
        report["completed_at"] = utc_now()
        report["retained_previous"] = previous is not None
        if added:
            snapshot = build_snapshot(frames, source_kind="firms_multisource", refresh=report)
            if previous:
                snapshot["metadata"]["imports"] = previous["metadata"].get("imports", [])
                snapshot["metadata"]["previous_import_audit"] = {
                    key: previous["metadata"].get(key) for key in ("input_rows", "invalid_rows", "duplicates_removed")}
            publish_snapshot(snapshot, path)
        _atomic_bytes(path.with_suffix(path.suffix + ".status.json"), json.dumps(report, indent=2).encode())
    finally:
        if session is None:
            client.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and refresh exact FIRMS observations for the map")
    parser.add_argument("command", choices=["build-local", "refresh", "watch"])
    parser.add_argument("--output", type=Path, default=snapshot_path())
    parser.add_argument("--csv", type=Path, action="append", help="Explicit CSV import; repeat for multiple files")
    parser.add_argument("--days", type=int, choices=range(1, 15), default=7)
    parser.add_argument("--interval-seconds", type=int, default=3600,
                        help="Refresh interval for the optional independent worker (minimum 300)")
    args = parser.parse_args()
    if args.interval_seconds < 300:
        parser.error("--interval-seconds must be at least 300")
    if args.command in ("refresh", "watch"):
        while True:
            try:
                report = refresh_observations(args.output, api_key=get_settings().firms_key, days=args.days)
                print(json.dumps(report, indent=2), flush=True)
            except (OSError, ValueError, RuntimeError) as exc:
                if args.command == "refresh":
                    raise
                # No raw network exception/URL or secret in worker logs.
                print(f"Refresh failed ({type(exc).__name__}); keeping the previous snapshot.", flush=True)
                report = {"status": "offline"}
            if args.command == "refresh":
                if report["status"] == "offline":
                    raise SystemExit(1)
                break
            time.sleep(args.interval_seconds)
        return
    paths = args.csv or [ROOT / "data" / "raw" / name for name in (
        "firms_viirs_snpp_sp.csv", "firms_viirs_snpp_nrt.csv", "firms_viirs_noaa20_sp_gap.csv",
        "firms_viirs_noaa20_nrt_gap.csv", "firms_viirs_noaa21_nrt_gap.csv", "firms_modis_sp_gap.csv", "firms_modis_nrt_gap.csv")]
    frames, imports = [], []
    for path in paths:
        if not path.is_file():
            if args.csv:
                raise FileNotFoundError(path)
            continue
        frame = pd.read_csv(path)
        frame["source"] = "local_csv" if args.csv else path.stem.removeprefix("firms_").removesuffix("_gap").upper()
        imports.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "rows": len(frame)})
        frames.append(frame)
    snapshot = build_snapshot(frames, source_kind="local_csv_import" if args.csv else "local_firms_archive")
    snapshot["metadata"]["imports"] = imports
    publish_snapshot(snapshot, args.output)
    # A manual rebuild starts a new archive, invalidating a former refresh report.
    args.output.with_suffix(args.output.suffix + ".status.json").unlink(missing_ok=True)
    print(json.dumps(snapshot["metadata"], indent=2))


if __name__ == "__main__":
    main()
