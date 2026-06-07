#!/usr/bin/env python3
__version__ = "1.0.0"

"""LibreLinkUp -> Nightscout uploader bridge.

Read-only bridge: pulls LibreLinkUp follower data and uploads SGV entries to Nightscout.
This is supplemental telemetry, not medical-control software.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests
from dateutil import parser as date_parser
from pylibrelinkup import PyLibreLinkUp
from pylibrelinkup.api_url import APIUrl

DEFAULT_DB = "/data/uploader.sqlite3"
DIRECTION_MAP = {
    1: "DoubleUp",
    2: "SingleUp",
    3: "FortyFiveUp",
    4: "Flat",
    5: "FortyFiveDown",
    6: "SingleDown",
    7: "DoubleDown",
    "1": "DoubleUp",
    "2": "SingleUp",
    "3": "FortyFiveUp",
    "4": "Flat",
    "5": "FortyFiveDown",
    "6": "SingleDown",
    "7": "DoubleDown",
}


def log(msg: str) -> None:
    print(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {msg}", flush=True)


def get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return {"value": obj}


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = dt.datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=dt.timezone.utc)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = date_parser.parse(text)
        except Exception:
            return None
    if parsed.tzinfo is None:
        # LibreLinkUp commonly returns local wall-clock timestamps with no timezone.
        # Interpret those in the user configured CGM timezone, then convert to UTC for Nightscout.
        local_tz = ZoneInfo(os.getenv("CGM_TIMEZONE", "America/Detroit"))
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(dt.timezone.utc)


def pick(d: dict[str, Any], *names: str) -> Any:
    lower = {str(k).lower(): k for k in d.keys()}
    for name in names:
        key = lower.get(name.lower())
        if key is not None:
            return d.get(key)
    for name in names:
        needle = name.lower()
        for k in d.keys():
            if needle in str(k).lower():
                return d.get(k)
    return None


def normalize_measurement(obj: Any, source: str) -> dict[str, Any] | None:
    raw = as_dict(obj)
    # Some pylibrelinkup models nest the measurement under glucose_measurement/current/measurement.
    for nested in ("glucose_measurement", "current", "measurement", "data"):
        nested_obj = raw.get(nested)
        if nested_obj:
            nested_dict = as_dict(nested_obj)
            if nested_dict:
                merged = dict(raw)
                merged.update(nested_dict)
                raw = merged
                break

    value = pick(raw, "value_in_mg_per_dl", "valueInMgPerDl", "ValueInMgPerDl", "mgdl", "mg/dL", "value")
    ts = pick(raw, "timestamp", "Timestamp", "factory_timestamp", "FactoryTimestamp", "date", "dateString", "created_at")
    trend = pick(raw, "trend", "Trend", "trend_arrow", "trendArrow", "direction")

    if value is None or ts is None:
        return None
    try:
        sgv = int(round(float(value)))
    except Exception:
        return None
    parsed = parse_timestamp(ts)
    if parsed is None:
        return None

    direction = DIRECTION_MAP.get(trend, str(trend) if trend else None)
    epoch_ms = int(parsed.timestamp() * 1000)
    entry = {
        "type": "sgv",
        "sgv": sgv,
        "date": epoch_ms,
        "dateString": parsed.isoformat().replace("+00:00", "Z"),
        "device": source,
        "rawbg": sgv,
        "direction": direction,
        "utcOffset": 0,
    }
    return {"id": f"{source}:{epoch_ms}:{sgv}", "entry": entry, "raw": raw}


def db_connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS uploaded (id TEXT PRIMARY KEY, uploaded_at TEXT NOT NULL, raw_json TEXT)")
    con.commit()
    return con


def already_uploaded(con: sqlite3.Connection, ident: str) -> bool:
    return con.execute("SELECT 1 FROM uploaded WHERE id = ?", (ident,)).fetchone() is not None


def mark_uploaded(con: sqlite3.Connection, ident: str, raw: Any) -> None:
    con.execute(
        "INSERT OR IGNORE INTO uploaded (id, uploaded_at, raw_json) VALUES (?, ?, ?)",
        (ident, dt.datetime.now(dt.timezone.utc).isoformat(), json.dumps(raw, default=str, sort_keys=True)),
    )
    con.commit()


def api_url(region: str) -> APIUrl:
    region = region.upper()
    if hasattr(APIUrl, region):
        return getattr(APIUrl, region)
    valid = ", ".join([x for x in dir(APIUrl) if x.isupper()])
    raise SystemExit(f"Invalid LIBRELINKUP_REGION={region}. Valid options include: {valid}")


def fetch_measurements() -> list[dict[str, Any]]:
    email = get_env("LIBRELINKUP_EMAIL", required=True)
    password = get_env("LIBRELINKUP_PASSWORD", required=True)
    region = get_env("LIBRELINKUP_REGION", "US") or "US"
    patient_id = get_env("LIBRELINKUP_PATIENT_ID")

    client = PyLibreLinkUp(email=email, password=password, api_url=api_url(region))
    client.authenticate()
    patients = client.get_patients()
    if not patients:
        raise RuntimeError("LibreLinkUp authenticated, but no shared patients were returned. Accept the LibreLinkUp invitation first.")

    patient = None
    for p in patients:
        pd = as_dict(p)
        pid = str(pick(pd, "patient_id", "patientId", "id", "UserID") or "")
        if not patient_id or pid == str(patient_id):
            patient = p
            break
    if patient is None:
        raise RuntimeError(f"Configured LIBRELINKUP_PATIENT_ID={patient_id} was not found")

    measurements: list[dict[str, Any]] = []
    for label, call in (
        ("librelinkup_latest", lambda: client.latest(patient)),
        ("librelinkup_graph", lambda: client.graph(patient)),
        ("librelinkup_logbook", lambda: client.logbook(patient)),
    ):
        try:
            data = call()
        except Exception as exc:
            log(f"WARN {label} fetch failed: {exc}")
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            norm = normalize_measurement(item, label)
            if norm:
                measurements.append(norm)
    # sort oldest first for Nightscout graph coherence
    measurements.sort(key=lambda m: m["entry"]["date"])
    return measurements


def post_to_nightscout(measurements: Iterable[dict[str, Any]]) -> tuple[int, int]:
    ns_url = (get_env("NIGHTSCOUT_URL", required=True) or "").rstrip("/")
    secret = get_env("NIGHTSCOUT_API_SECRET", required=True) or ""
    db = get_env("UPLOADER_DB", DEFAULT_DB) or DEFAULT_DB
    timeout = int(get_env("HTTP_TIMEOUT_SECONDS", "30") or "30")
    api_secret_hash = hashlib.sha1(secret.encode("utf-8")).hexdigest()
    con = db_connect(db)
    inserted = 0
    skipped = 0
    for m in measurements:
        ident = m["id"]
        if already_uploaded(con, ident):
            skipped += 1
            continue
        resp = requests.post(
            f"{ns_url}/api/v1/entries.json",
            headers={"api-secret": api_secret_hash, "content-type": "application/json"},
            json=[m["entry"]],
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Nightscout upload failed HTTP {resp.status_code}: {resp.text[:500]}")
        mark_uploaded(con, ident, m.get("raw"))
        inserted += 1
    return inserted, skipped


def run_once() -> None:
    measurements = fetch_measurements()
    inserted, skipped = post_to_nightscout(measurements)
    log(f"complete fetched={len(measurements)} uploaded={inserted} skipped={skipped}")


def main() -> int:
    interval = int(get_env("POLL_INTERVAL_SECONDS", "300") or "300")
    once = "--once" in sys.argv
    if once:
        run_once()
        return 0
    log(f"starting LibreLinkUp -> Nightscout bridge interval={interval}s")
    while True:
        try:
            run_once()
        except Exception as exc:
            log(f"ERROR {type(exc).__name__}: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
