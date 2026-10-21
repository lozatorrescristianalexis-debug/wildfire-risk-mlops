from datetime import date, datetime, timedelta, timezone
import gzip
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.wildfire import observations as obs
from src.wildfire.api import app


def row(**updates):
    return {"latitude": -12.0, "longitude": -70.25, "acq_date": "2025-01-02",
            "acq_time": 615, "satellite": "N", "instrument": "VIIRS",
            "confidence": "n", "source": "VIIRS_SNPP_NRT", "frp": 12.0, **updates}


def snapshot(tmp_path, rows=None):
    path = tmp_path / "observations.json.gz"
    data = obs.build_snapshot([pd.DataFrame(rows or [row()])], source_kind="test")
    obs.publish_snapshot(data, path)
    return path, data


def test_coordinates_time_confidence_and_deduplication_are_preserved():
    records, audit = obs.normalize_observations([pd.DataFrame([
        row(), row(source="VIIRS_SNPP_SP", confidence="h"),
        row(acq_time=1815), row(satellite="N20", source="VIIRS_NOAA20_NRT"),
        row(instrument="MODIS", satellite="Terra", confidence=85, source="MODIS_NRT"),
        row(instrument="MODIS", satellite="Terra", confidence=55, acq_time=720),
        row(latitude=200), row(latitude="bad"), row(acq_date="invalid"),
        row(latitude=0, longitude=0),
    ])])
    assert len(records) == 6
    assert audit == {"input_rows": 10, "invalid_rows": 3, "duplicates_removed": 1, "outside_peru": 1}
    merged = next(r for r in records if r["source"] == "VIIRS_SNPP_NRT|VIIRS_SNPP_SP")
    assert merged["confidence"] == "high"
    assert merged["acq_time"] == "0615"
    assert merged["latitude"] == -12.0 and merged["longitude"] == -70.25
    assert merged["mapped_region"] == "madre_de_dios"
    assert {r["confidence"] for r in records if r["instrument"] == "MODIS"} == {"high", "nominal"}
    assert len({r["id"] for r in records}) == 6


def test_corrupt_or_empty_snapshot_keeps_last_valid_and_cache_refreshes(tmp_path):
    path, first = snapshot(tmp_path)
    changed = obs.build_snapshot([pd.DataFrame([row(acq_date="2025-01-03")])], source_kind="test")
    obs.publish_snapshot(changed, path)
    assert obs.load_snapshot(path)["snapshot_id"] == changed["snapshot_id"]
    with pytest.raises(ValueError, match="empty"):
        obs.publish_snapshot(obs.build_snapshot([], source_kind="test"), path)
    path.write_bytes(b"truncated")
    fallback = obs.load_snapshot(path)
    assert fallback["snapshot_id"] == first["snapshot_id"]
    assert fallback["metadata"]["serving_fallback"] is True
    assert fallback["metadata"]["status"] == "fallback"


def test_pagination_filters_totals_and_snapshot_pin(tmp_path, monkeypatch):
    rows = [row(acq_time=100 + i) for i in range(9)] + [row(latitude=0, longitude=0)]
    path, data = snapshot(tmp_path, rows)
    monkeypatch.setenv("WILDFIRE_OBSERVATIONS_PATH", str(path))
    c = TestClient(app)
    all_ids = []
    offset = 0
    while offset is not None:
        response = c.get("/api/fire-observations", params={"limit": 2, "offset": offset, "snapshot_id": data["snapshot_id"]})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 9
        all_ids.extend(r["id"] for r in body["items"])
        offset = body["next_offset"]
    assert len(set(all_ids)) == 9
    assert c.get("/api/fire-observations?region=all").json()["total"] == 10
    assert c.get("/api/fire-observations?region=lima").json()["total"] == 0
    assert c.get("/api/fire-observations?start_date=2025-01-03").json()["total"] == 0
    assert c.get("/api/fire-observations?confidence=high").json()["total"] == 0
    assert c.get("/api/fire-observations?confidence=nominal").json()["total"] == 9
    assert c.get("/api/fire-observations?instrument=MODIS").json()["total"] == 0
    assert c.get("/api/fire-observations?bbox=-71,-13,-70,-11").json()["total"] == 9
    for query in ("region=bogus", "bbox=NaN,0,2,3", "bbox=1,2,3", "limit=0", "offset=-1", "start_date=2025-02-02&end_date=2025-01-01"):
        assert c.get("/api/fire-observations?" + query).status_code == 422
    assert c.get("/api/fire-observations?snapshot_id=old").status_code == 409
    assert c.get("/api/fire-observations/status").json()["snapshot_id"] == data["snapshot_id"]


def test_offline_refresh_never_overwrites_snapshot_or_leaks_secret(tmp_path, monkeypatch):
    path, _ = snapshot(tmp_path)
    before = path.read_bytes()
    def fail(*args, **kwargs):
        raise RuntimeError("https://example.org/private-secret")
    monkeypatch.setattr(obs, "fetch_availability", fail)
    monkeypatch.setattr(obs, "fetch_firms_history", fail)
    monkeypatch.setattr(obs, "fetch_public_csv", fail)
    report = obs.refresh_observations(path, api_key="private-secret")
    assert report["status"] == "offline"
    assert path.read_bytes() == before
    assert "private-secret" not in json.dumps(report)
    assert obs.load_snapshot(path)["metadata"]["refresh"]["status"] == "offline"


def test_latest_available_date_csv_fallback_and_partial_merge(tmp_path, monkeypatch):
    path, original = snapshot(tmp_path)
    today = datetime.now(timezone.utc).date()
    latest = today - timedelta(days=2)
    calls = []
    monkeypatch.setattr(obs, "fetch_availability", lambda *args: {s: (date(2025, 1, 1), latest) for s in obs.SOURCES})
    def area(key, source, bbox, start, end, **kwargs):
        calls.append((source, start, end))
        if source != obs.SOURCES[0]:
            raise RuntimeError("API failed")
        return pd.DataFrame([row(acq_date=latest.isoformat())])
    def public(source, session):
        if source != obs.SOURCES[1]:
            raise ValueError("Invalid CSV")
        # Official public CSV does not contain an instrument column.
        frame = pd.DataFrame([row(acq_date=today.isoformat(), satellite="N20")])
        return frame.drop(columns="instrument")
    monkeypatch.setattr(obs, "fetch_firms_history", area)
    monkeypatch.setattr(obs, "fetch_public_csv", public)
    report = obs.refresh_observations(path, api_key="test")
    assert report["status"] == "partial"
    assert all(end == latest and start == latest - timedelta(days=6) for _, start, end in calls)
    assert report["sources"][obs.SOURCES[1]]["method"] == "official_csv_7d"
    loaded = obs.load_snapshot(path)
    assert loaded["metadata"]["total_records"] == 3
    assert loaded["metadata"]["last_detection"] == today.isoformat()
    assert original["items"][0]["id"] in {r["id"] for r in loaded["items"]}
    assert all(r["instrument"] == "VIIRS" for r in loaded["items"])


def test_valid_empty_response_is_not_an_outage_or_absence_of_fire(tmp_path, monkeypatch):
    path, _ = snapshot(tmp_path)
    before = path.read_bytes()
    empty = pd.DataFrame(columns=["latitude", "longitude", "acq_date"])
    monkeypatch.setattr(obs, "fetch_public_csv", lambda *args: empty)
    report = obs.refresh_observations(path, api_key="")
    assert report["status"] == "ok"
    assert all(source["status"] == "empty" for source in report["sources"].values())
    assert path.read_bytes() == before


def test_invalid_nonempty_response_is_not_counted_as_success(tmp_path, monkeypatch):
    path, _ = snapshot(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(obs, "fetch_public_csv", lambda *args: pd.DataFrame([row(latitude="oops")]))
    report = obs.refresh_observations(path, api_key="")
    assert report["status"] == "offline"
    assert path.read_bytes() == before


def test_snapshot_is_strict_json_and_readable_for_docker_user(tmp_path):
    path, _ = snapshot(tmp_path, [row(frp=float("inf"))])
    data = json.loads(gzip.decompress(path.read_bytes()))
    assert data["items"][0]["frp"] is None
    assert path.stat().st_mode & 0o444 == 0o444
