__version__ = "1.0.0"

import os
import json
import hashlib
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import sqlite3
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager

load_dotenv()

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/heartscout.db")
API_SECRET = os.getenv("API_SECRET", "change...me")
NIGHTSCOUT_URL = os.getenv("NIGHTSCOUT_URL", "").rstrip("/")
NIGHTSCOUT_TOKEN = os.getenv("NIGHTSCOUT_TOKEN", "")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="HeartScout", lifespan=lifespan)

# WebSocket connections for live BPM
active_connections: List[WebSocket] = []

def get_db():
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS heart_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            bpm REAL NOT NULL,
            source TEXT NOT NULL,
            raw_json TEXT,
            inserted_at TEXT NOT NULL,
            UNIQUE(timestamp_utc, source)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS step_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time_utc TEXT NOT NULL,
            end_time_utc TEXT NOT NULL,
            count INTEGER NOT NULL,
            source TEXT NOT NULL,
            raw_json TEXT,
            inserted_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_step_readings_unique
        ON step_readings(start_time_utc, end_time_utc, source)
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS relay_status (
            device TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            heart_count INTEGER NOT NULL,
            step_count INTEGER NOT NULL,
            newest_heart_timestamp_utc TEXT,
            oldest_heart_timestamp_utc TEXT,
            message TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    print("Database initialized.")

class HeartReading(BaseModel):
    timestamp_utc: str
    bpm: float
    source: str = "health_connect"
    raw_json: Optional[str] = None

class StepReading(BaseModel):
    start_time_utc: str
    end_time_utc: str
    count: int
    source: str = "health_connect"
    raw_json: Optional[str] = None

class HeartBatch(BaseModel):
    readings: List[HeartReading]

class RelayStatus(BaseModel):
    device: str = "android"
    status: str = "unknown"
    heart_count: int = 0
    step_count: int = 0
    newest_heart_timestamp_utc: Optional[str] = None
    oldest_heart_timestamp_utc: Optional[str] = None
    message: Optional[str] = None

@app.post("/api/heart")
async def ingest_heart(batch: HeartBatch, secret: Optional[str] = None):
    if secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API secret")
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for r in batch.readings:
        try:
            c.execute("""
                INSERT INTO heart_readings (timestamp_utc, bpm, source, raw_json, inserted_at)
                VALUES (?, ?, ?, ?, ?)
            """, (r.timestamp_utc, r.bpm, r.source, r.raw_json, now))
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate
    conn.commit()
    conn.close()

    if batch.readings:
        latest_seen = max(batch.readings, key=lambda r: r.timestamp_utc)
        print(
            f"Heart ingest: received={len(batch.readings)} inserted={inserted} "
            f"latest={latest_seen.timestamp_utc} bpm={latest_seen.bpm} source={latest_seen.source}",
            flush=True,
        )

    # Broadcast latest reading to live clients
    if batch.readings:
        latest = batch.readings[-1]
        payload = json.dumps({
            "type": "heart",
            "timestamp_utc": latest.timestamp_utc,
            "bpm": latest.bpm
        })
        for ws in active_connections[:]:
            try:
                await ws.send_text(payload)
            except:
                active_connections.remove(ws)

    return {"status": "ok", "inserted": inserted}

@app.post("/api/steps")
async def ingest_steps(reading: StepReading, secret: Optional[str] = None):
    if secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid API secret")
    conn = get_db()
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    try:
        c.execute("""
            INSERT INTO step_readings (start_time_utc, end_time_utc, count, source, raw_json, inserted_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (reading.start_time_utc, reading.end_time_utc, reading.count, reading.source, reading.raw_json, now))
        inserted = 1
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()
    return {"status": "ok", "inserted": inserted}

def sqlite_utc_expr(column: str) -> str:
    # Health Connect sends ISO-8601 strings like 2026-05-29T18:00:18Z.
    # SQLite datetime('now') uses "YYYY-MM-DD HH:MM:SS". Normalize before comparing;
    # raw lexical comparison treats every same-day "T" timestamp as newer than the
    # space-separated cutoff, making /recent return all of today instead of the window.
    return f"datetime(replace(replace({column}, 'T', ' '), 'Z', ''))"

@app.post("/api/relay/status")
async def relay_status_update(status: RelayStatus, secret: Optional[str] = None):
    if secret != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO relay_status (device, status, heart_count, step_count, newest_heart_timestamp_utc, oldest_heart_timestamp_utc, message, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device) DO UPDATE SET
            status=excluded.status,
            heart_count=excluded.heart_count,
            step_count=excluded.step_count,
            newest_heart_timestamp_utc=excluded.newest_heart_timestamp_utc,
            oldest_heart_timestamp_utc=excluded.oldest_heart_timestamp_utc,
            message=excluded.message,
            updated_at=excluded.updated_at
    """, (status.device, status.status, status.heart_count, status.step_count, status.newest_heart_timestamp_utc, status.oldest_heart_timestamp_utc, status.message, now))
    conn.commit()
    conn.close()
    print(f"Relay status: device={status.device} status={status.status} heart_count={status.heart_count} newest={status.newest_heart_timestamp_utc} message={status.message}")
    return {"status": "ok"}

@app.get("/api/relay/status")
async def relay_status_get():
    conn = get_db()
    rows = conn.execute("SELECT * FROM relay_status ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/heart/recent")
async def recent_heart(minutes: int = 60):
    safe_minutes = max(1, min(minutes, 7 * 24 * 60))
    conn = get_db()
    c = conn.cursor()
    c.execute(f"""
        SELECT timestamp_utc, bpm, source
        FROM heart_readings
        WHERE {sqlite_utc_expr('timestamp_utc')} >= datetime('now', ?)
        ORDER BY {sqlite_utc_expr('timestamp_utc')} ASC
    """, (f"-{safe_minutes} minutes",))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/summary/today")
async def summary_today():
    local_tz = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "America/Detroit"))
    now_local = datetime.now(local_tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = end_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*) as count,
            AVG(bpm) as avg_bpm,
            MIN(bpm) as min_bpm,
            MAX(bpm) as max_bpm
        FROM heart_readings
        WHERE timestamp_utc >= ? AND timestamp_utc < ?
    """, (start_utc, end_utc))
    row = dict(c.fetchone())
    c.execute(f"""
        SELECT timestamp_utc, bpm, source, inserted_at
        FROM heart_readings
        ORDER BY {sqlite_utc_expr('timestamp_utc')} DESC
        LIMIT 1
    """)
    latest = c.fetchone()
    conn.close()
    if latest:
        row.update({
            "latest_timestamp_utc": latest["timestamp_utc"],
            "latest_bpm": latest["bpm"],
            "latest_source": latest["source"],
            "latest_inserted_at": latest["inserted_at"],
        })
    return row


@app.get("/api/nightscout/recent")
async def nightscout_recent(count: int = 288):
    """Proxy recent Nightscout SGV entries for the dashboard.

    Configure server/.env:
      NIGHTSCOUT_URL=https://your-nightscout.example
      NIGHTSCOUT_TOKEN=optional-token
    """
    if not NIGHTSCOUT_URL:
        return {"configured": False, "entries": [], "latest": None, "error": "NIGHTSCOUT_URL not configured"}

    safe_count = max(1, min(count, 1000))
    query = {"count": str(safe_count)}
    if NIGHTSCOUT_TOKEN:
        query["token"] = NIGHTSCOUT_TOKEN
    url = f"{NIGHTSCOUT_URL}/api/v1/entries/sgv.json?{urllib.parse.urlencode(query)}"
    try:
        headers = {"Accept": "application/json", "User-Agent": "HeartScout/1.0"}
        if NIGHTSCOUT_TOKEN:
            # Nightscout legacy API auth expects the SHA-1 hash of API_SECRET in the api-secret header.
            # Some deployments accept a token query param instead; keep both for compatibility.
            headers["api-secret"] = hashlib.sha1(NIGHTSCOUT_TOKEN.encode("utf-8")).hexdigest()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"configured": True, "entries": [], "latest": None, "error": str(exc)}

    entries = []
    for item in data if isinstance(data, list) else []:
        sgv = item.get("sgv") or item.get("mbg")
        timestamp = item.get("dateString")
        if not timestamp and item.get("date"):
            try:
                timestamp = datetime.fromtimestamp(float(item["date"]) / 1000, tz=timezone.utc).isoformat()
            except Exception:
                timestamp = None
        if sgv is None or timestamp is None:
            continue
        entries.append({
            "timestamp_utc": timestamp,
            "sgv": sgv,
            "direction": item.get("direction"),
            "delta": item.get("delta"),
            "noise": item.get("noise"),
            "type": item.get("type"),
        })

    entries.sort(key=lambda item: item["timestamp_utc"])
    latest = entries[-1] if entries else None
    return {"configured": True, "entries": entries, "latest": latest, "error": None}

@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        active_connections.remove(ws)

# Serve dashboard
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open("static/index.html") as f:
        return HTMLResponse(
            content=f.read(),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
