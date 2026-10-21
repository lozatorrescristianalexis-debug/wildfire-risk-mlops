from __future__ import annotations

import json
from datetime import date, timedelta
from io import StringIO
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import threading
import time

import pandas as pd
import requests

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
WEATHER_COLUMNS = (
    "temperature_2m_max",
    "relative_humidity_2m_mean",
    "precipitation_sum",
    "wind_speed_10m_max",
)
FIRMS_MAX_DAYS_PER_REQUEST = 5
FIRMS_REQUIRED_COLUMNS = {"acq_date", "latitude", "longitude"}
FIRMS_RETRY_ATTEMPTS = 5
FIRMS_MIN_REQUEST_INTERVAL = 1.0
FIRMS_REQUEST_TIMEOUT = 120
FIRMS_MAX_WORKERS = 4
WEATHER_MIN_REQUEST_INTERVAL = 4.0
WEATHER_RETRY_ATTEMPTS = 5
_LAST_FIRMS_REQUEST = 0.0
_FIRMS_RATE_LOCK = threading.Lock()
_LAST_WEATHER_REQUEST = 0.0
_WEATHER_RATE_LOCK = threading.Lock()


def _safe_firms_error(exc: Exception, api_key: str) -> str:
    message = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
    message = re.sub(
        r"https?://firms\.modaps\.eosdis\.nasa\.gov/\S+",
        "https://firms.modaps.eosdis.nasa.gov/[REDACTED]",
        message,
    )
    return message


def _request_firms_csv(
    client: requests.Session,
    url: str,
    api_key: str,
    timeout: int,
) -> str:
    global _LAST_FIRMS_REQUEST
    last_error: Exception | None = None
    for attempt in range(FIRMS_RETRY_ATTEMPTS):
        with _FIRMS_RATE_LOCK:
            wait_for = FIRMS_MIN_REQUEST_INTERVAL - (time.monotonic() - _LAST_FIRMS_REQUEST)
            if wait_for > 0:
                time.sleep(wait_for)
            _LAST_FIRMS_REQUEST = time.monotonic()
        try:
            response = client.get(url, timeout=timeout)
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                body = response.text.strip()
                detail = _safe_firms_error(body, api_key) if body else str(exc)
                raise requests.HTTPError(
                    f"HTTP {response.status_code} {response.reason}: {detail}",
                    response=response,
                ) from None
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                status = exc.response.status_code
                if status != 429 and status < 500:
                    break
            if attempt + 1 < FIRMS_RETRY_ATTEMPTS:
                time.sleep(min(2**attempt, 30))
    assert last_error is not None
    raise RuntimeError(_safe_firms_error(last_error, api_key)) from None


def _parse_firms_response(text: str) -> pd.DataFrame:
    if not text.strip():
        raise ValueError("FIRMS returned an empty response.")
    try:
        frame = pd.read_csv(StringIO(text))
    except pd.errors.ParserError as exc:
        raise ValueError("FIRMS response is not valid CSV.") from exc
    if not FIRMS_REQUIRED_COLUMNS.issubset(frame.columns):
        missing = ", ".join(sorted(FIRMS_REQUIRED_COLUMNS - set(frame.columns)))
        raise ValueError(f"FIRMS response is missing required CSV column(s): {missing}.")
    return frame


def fetch_firms(
    api_key: str,
    source: str,
    area: str,
    timeout: int = FIRMS_REQUEST_TIMEOUT,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("MAP_KEY is missing; add your NASA FIRMS key to the local .env file.")
    client = session or requests.Session()
    try:
        text = _request_firms_csv(
            client,
            f"{FIRMS_URL}/{api_key}/{source}/{area}/{FIRMS_MAX_DAYS_PER_REQUEST}",
            api_key,
            timeout,
        )
    except RuntimeError as exc:
        raise RuntimeError(f"FIRMS request failed: {exc}") from None
    return _parse_firms_response(text)


def fetch_firms_history(
    api_key: str,
    source: str,
    area: str,
    start_date: date,
    end_date: date,
    timeout: int = FIRMS_REQUEST_TIMEOUT,
    session: requests.Session | None = None,
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    if not api_key:
        raise ValueError("MAP_KEY is missing; add your NASA FIRMS key to the local .env file.")
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    frames_by_chunk: dict[tuple[date, date], pd.DataFrame] = {}
    bbox_id = hashlib.sha256(area.encode("utf-8")).hexdigest()[:8]
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(
            chunk_start + timedelta(days=FIRMS_MAX_DAYS_PER_REQUEST - 1),
            end_date,
        )
        day_count = (chunk_end - chunk_start).days + 1
        raw_path = (
            raw_dir / f"firms_{source.lower()}_{bbox_id}_{chunk_start}_{chunk_end}.csv"
            if raw_dir is not None
            else None
        )
        if raw_path is not None and raw_path.exists():
            frame = _parse_firms_response(raw_path.read_text(encoding="utf-8"))
            frames_by_chunk[(chunk_start, chunk_end)] = frame
        else:
            chunks.append((chunk_start, chunk_end, day_count, raw_path))
        chunk_start = chunk_end + timedelta(days=1)

    def download_chunk(chunk):
        start, end, days, destination = chunk
        url = f"{FIRMS_URL}/{api_key}/{source}/{area}/{days}/{start.isoformat()}"
        request_session = session or requests.Session()
        try:
            text = _request_firms_csv(request_session, url, api_key, timeout)
            frame = _parse_firms_response(text)
        except ValueError as exc:
            raise ValueError(
                f"FIRMS historical response for {start} to {end} "
                f"was invalid: {exc}"
            ) from exc
        except RuntimeError as exc:
            raise RuntimeError(
                f"FIRMS historical request failed for {start} to {end}: {exc}"
            ) from None
        finally:
            if session is None:
                request_session.close()
        if destination is not None:
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(destination)
        return (start, end), frame

    total_chunks = len(chunks) + len(frames_by_chunk)
    completed = len(frames_by_chunk)
    with ThreadPoolExecutor(max_workers=FIRMS_MAX_WORKERS) as executor:
        futures = [executor.submit(download_chunk, chunk) for chunk in chunks]
        for future in as_completed(futures):
            chunk_key, frame = future.result()
            frames_by_chunk[chunk_key] = frame
            completed += 1
            if completed % 10 == 0 or completed == total_chunks:
                print(f"FIRMS {source}: bloque {completed}/{total_chunks} ({chunk_key[1]})")

    frames = [
        frames_by_chunk[key]
        for key in sorted(frames_by_chunk)
        if not frames_by_chunk[key].empty
    ]
    detections = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if detections.empty:
        return pd.DataFrame(columns=sorted(FIRMS_REQUIRED_COLUMNS))
    parsed_dates = pd.to_datetime(detections["acq_date"], errors="coerce").dt.date
    within_period = parsed_dates.between(start_date, end_date)
    return detections.loc[within_period].drop_duplicates().reset_index(drop=True)


def normalize_firms(fires: pd.DataFrame) -> pd.DataFrame:
    date_column = next(
        (name for name in ("acq_date", "scan_date", "date") if name in fires.columns),
        None,
    )
    if date_column is None:
        raise ValueError("FIRMS CSV must contain acq_date, scan_date, or date.")
    parsed_dates = pd.to_datetime(fires[date_column], errors="coerce", utc=True)
    valid = fires.loc[parsed_dates.notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=["date", "fire_count"])
    valid["date"] = parsed_dates.loc[parsed_dates.notna()].dt.strftime("%Y-%m-%d")
    return (
        valid.groupby("date", as_index=False)
        .size()
        .rename(columns={"size": "fire_count"})
    )


def fetch_weather(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    client = session or requests.Session()
    response = client.get(
        WEATHER_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(WEATHER_COLUMNS),
            "timezone": "UTC",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if "daily" not in payload or "time" not in payload["daily"]:
        raise ValueError("Open-Meteo response is missing daily weather data.")
    daily = payload["daily"]
    frame = pd.DataFrame({"date": daily["time"]})
    for column in WEATHER_COLUMNS:
        if column not in daily:
            raise ValueError(f"Open-Meteo response is missing {column}.")
        frame[column] = daily[column]
    return frame


def fetch_weather_history(
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    timeout: int = 30,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    frames = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + timedelta(days=29), end_date)
        try:
            frames.append(
                fetch_weather(
                    latitude,
                    longitude,
                    chunk_start,
                    chunk_end,
                    timeout,
                    session,
                )
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Open-Meteo historical request failed ({type(exc).__name__}) for "
                f"{chunk_start} to {chunk_end}; check network and API settings."
            ) from None
        chunk_start = chunk_end + timedelta(days=1)
    weather = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["date"])
    return weather.sort_values("date").reset_index(drop=True)


def fetch_weather_grid_history(
    grid: pd.DataFrame,
    start_date: date,
    end_date: date,
    timeout: int = 60,
    batch_size: int = 50,
    chunk_days: int = 30,
    session: requests.Session | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    if chunk_days <= 0:
        raise ValueError("chunk_days must be greater than zero.")
    if grid.empty or not {"cell_id", "latitude", "longitude"}.issubset(grid.columns):
        raise ValueError("Grid must contain cell_id, latitude, and longitude.")
    client = session or requests.Session()
    frames = []
    for offset in range(0, len(grid), batch_size):
        batch = grid.iloc[offset : offset + batch_size]
        batch_identity = "|".join(
            f"{cell.cell_id}:{cell.latitude:.5f}:{cell.longitude:.5f}"
            for cell in batch.itertuples()
        )
        batch_id = hashlib.sha256(batch_identity.encode("utf-8")).hexdigest()[:12]
        coordinates = {
            "latitude": ",".join(batch["latitude"].map(lambda value: f"{value:.5f}")),
            "longitude": ",".join(batch["longitude"].map(lambda value: f"{value:.5f}")),
        }
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(chunk_start + timedelta(days=chunk_days - 1), end_date)
            cache_path = (
                cache_dir
                / f"open_meteo_grid_{batch_id}_{chunk_start}_{chunk_end}.csv"
                if cache_dir is not None
                else None
            )
            if cache_path is not None and cache_path.exists():
                cached = pd.read_csv(cache_path)
                expected_dates = set(
                    pd.date_range(chunk_start, chunk_end, freq="D").strftime("%Y-%m-%d")
                )
                if (
                    len(cached) != len(batch) * len(expected_dates)
                    or set(cached["cell_id"]) != set(batch["cell_id"])
                    or set(cached["date"]) != expected_dates
                    or cached.duplicated(["cell_id", "date"]).any()
                ):
                    raise ValueError(f"Open-Meteo cache is incomplete or invalid: {cache_path.name}")
                frames.append(cached)
            else:
                def download_window(window_start: date, window_end: date) -> pd.DataFrame:
                    params = {
                        **coordinates,
                        "start_date": window_start.isoformat(),
                        "end_date": window_end.isoformat(),
                        "daily": ",".join(WEATHER_COLUMNS),
                        "timezone": "UTC",
                    }
                    payload = None
                    last_error: requests.RequestException | None = None
                    for attempt in range(WEATHER_RETRY_ATTEMPTS):
                        global _LAST_WEATHER_REQUEST
                        with _WEATHER_RATE_LOCK:
                            wait_for = WEATHER_MIN_REQUEST_INTERVAL - (
                                time.monotonic() - _LAST_WEATHER_REQUEST
                            )
                            if wait_for > 0:
                                time.sleep(wait_for)
                            _LAST_WEATHER_REQUEST = time.monotonic()
                        try:
                            response = client.get(WEATHER_URL, params=params, timeout=timeout)
                            response.raise_for_status()
                            payload = response.json()
                            break
                        except requests.RequestException as exc:
                            last_error = exc
                            status = exc.response.status_code if exc.response is not None else None
                            days = (window_end - window_start).days + 1
                            if status == 429 and days > 30:
                                midpoint = window_start + timedelta(days=days // 2 - 1)
                                print(f"Open-Meteo limit: dividiendo {window_start} a {window_end}")
                                return pd.concat(
                                    [download_window(window_start, midpoint),
                                     download_window(midpoint + timedelta(days=1), window_end)],
                                    ignore_index=True,
                                )
                            if status is not None and status != 429 and status < 500:
                                break
                            if attempt + 1 < WEATHER_RETRY_ATTEMPTS:
                                retry_after = (
                                    exc.response.headers.get("Retry-After")
                                    if exc.response is not None
                                    else None
                                )
                                try:
                                    delay = float(retry_after) if retry_after else 2**attempt
                                except ValueError:
                                    try:
                                        retry_at = parsedate_to_datetime(retry_after)
                                        delay = max(0, retry_at.timestamp() - time.time())
                                    except (TypeError, ValueError, OverflowError):
                                        delay = 2**attempt
                                time.sleep(min(max(delay, 1), 60))
                    if payload is None:
                        status = last_error.response.status_code if last_error and last_error.response is not None else "network"
                        raise RuntimeError(
                            f"Open-Meteo grid request failed for {window_start} to {window_end} "
                            f"(status {status})."
                        ) from None
                    if not isinstance(payload, list) or len(payload) != len(batch):
                        raise ValueError("Open-Meteo multi-location response did not match the grid batch.")
                    chunk_frames = []
                    for (_, cell), location in zip(batch.iterrows(), payload, strict=True):
                        if "daily" not in location or "time" not in location["daily"]:
                            raise ValueError(f"Open-Meteo response missing daily values for {cell.cell_id}.")
                        daily = location["daily"]
                        frame = pd.DataFrame({"date": daily["time"], "cell_id": cell.cell_id})
                        for column in WEATHER_COLUMNS:
                            if column not in daily:
                                raise ValueError(f"Open-Meteo response is missing {column}.")
                            frame[column] = daily[column]
                        chunk_frames.append(frame)
                    return pd.concat(chunk_frames, ignore_index=True)

                chunk_frame = download_window(chunk_start, chunk_end)
                if cache_path is not None:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
                    chunk_frame.to_csv(temporary, index=False)
                    temporary.replace(cache_path)
                frames.append(chunk_frame)
            chunk_start = chunk_end + timedelta(days=1)
        print(f"Open-Meteo grid: ubicaciones {min(offset + len(batch), len(grid))}/{len(grid)}")
    return pd.concat(frames, ignore_index=True).drop_duplicates(
        ["cell_id", "date"]
    ).sort_values(["cell_id", "date"]).reset_index(drop=True)


def fetch_boundary_geojson(
    output: Path,
    state: str | None = "Madre de Dios",
    country: str = "Peru",
    timeout: int = 60,
) -> Path:
    if output.exists():
        return output
    params = {
        "country": country,
        "format": "geojson",
        "polygon_geojson": 1,
        "limit": 1,
    }
    if state:
        params["state"] = state
    response = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers={"User-Agent": "wildfire-final-project/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if len(payload.get("features", [])) != 1:
        target = f"{state}, {country}" if state else country
        raise ValueError(f"Nominatim did not return exactly one {target} boundary.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload), encoding="utf-8")
    return output


def build_daily_dataset(
    fires: pd.DataFrame,
    weather: pd.DataFrame,
    start_date: date,
    end_date: date,
    latitude: float,
    longitude: float,
) -> pd.DataFrame:
    if start_date > end_date:
        raise ValueError("START_DATE must be on or before END_DATE.")
    dates = pd.DataFrame(
        {"date": pd.date_range(start_date, end_date, freq="D").strftime("%Y-%m-%d")}
    )
    fire_counts = normalize_firms(fires)
    merged = dates.merge(fire_counts, on="date", how="left")
    merged["fire_count"] = merged["fire_count"].astype("float64").fillna(0).astype("int64")
    merged = merged.merge(weather, on="date", how="left", validate="one_to_one")
    missing_weather = merged[list(WEATHER_COLUMNS)].isna().any(axis=1)
    if missing_weather.any():
        days = ", ".join(merged.loc[missing_weather, "date"].tolist())
        raise ValueError(f"Weather is missing for date(s): {days}")
    merged["latitude"] = latitude
    merged["longitude"] = longitude
    merged["label"] = (merged["fire_count"] > 0).astype("int64")
    merged["data_source"] = "firms_open_meteo"
    return merged


def save_dataset(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False)
