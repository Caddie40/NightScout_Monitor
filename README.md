# HeartScout + Nightscout Server Bundle

**Bundle version:** `1.0.0`  
**Build:** `20260607-000004`  
**Nightscout upstream version:** `15.0.7`  
**Source host:** `homelab01`

This repository contains the server-side code and deployment files for a local diabetes/health telemetry stack built around Nightscout and HeartScout.

The system is intended for local monitoring, personal data aggregation, and historical review. It is not medical-control software and should not replace the Libre app, prescribed diabetes treatment, or emergency alerting paths.

## What this is

This bundle is a copy of the server-side code used on my personal server for:

- Running a local Nightscout instance.
- Uploading LibreLinkUp CGM readings into Nightscout.
- Running the HeartScout FastAPI server for heart-rate and step telemetry.
- Preserving the custom Nightscout UI/server modifications used by this deployment.
- Capturing Docker and version metadata for repeatability.

Live secrets and runtime data were intentionally excluded.

## What it does

At a high level, the stack does four things:

1. **Nightscout hosts the CGM dashboard**
   - Runs `nightscout/cgm-remote-monitor` using Docker Compose.
   - Stores CGM data in MongoDB.
   - Serves the web dashboard on a port of your choosing.
   - Includes local customizations for UI/views/CSS and server behavior.

2. **LibreLinkUp uploader bridges CGM data into Nightscout**
   - Logs into a LibreLinkUp follower account.
   - Pulls recent glucose measurements.
   - Normalizes them into Nightscout SGV entries.
   - Uploads them into Nightscout through the Nightscout API.
   - Tracks uploaded records in SQLite so duplicates are skipped.

3. **HeartScout stores and serves heart/step data**
   - Exposes FastAPI endpoints for Android-side Health Connect relay data.
   - Accepts heart-rate batches and step readings.
   - Stores readings in SQLite.
   - Serves recent heart data, daily summaries, relay status, and live WebSocket updates.
   - Can query recent Nightscout glucose data when configured with a Nightscout URL/token.

4. **Version/provenance files document the bundle**
   - Root `VERSION` file defines the bundle version.
   - `metadata/version.json` records component versions.
   - Docker metadata snapshots preserve the runtime context without live secrets.

## Repository layout

```text
.
├── VERSION
├── README.md
├── README.txt
├── heartscout-server/
├── metadata/
├── nightscout-container-opt-app/
├── nightscout-service/
└── nightscout-uploader/
```

### `nightscout-container-opt-app/`

A copy of `/opt/app` from the running Nightscout container.

- Upstream package version: `15.0.7`
- Docker image tag used by the server: `nightscout/cgm-remote-monitor:latest`
- `node_modules` was removed to keep the export small.
- This is included as a source/reference snapshot of the running Nightscout application code.

### `nightscout-service/`

The local Nightscout deployment directory from my personal server.

Contains:

- `docker-compose.yml`
- Custom CSS
- Custom Nightscout view templates
- Custom server-side override files
- Redacted environment snapshot

The compose service maps local customization files into the Nightscout container, including:

```text
custom-css/main.css                     -> /opt/app/static/css/main.css
custom-views/index.html                 -> /opt/app/views/index.html
custom-views/frame.html                 -> /opt/app/views/frame.html
custom-views/adminindex.html            -> /opt/app/views/adminindex.html
custom-views/foodindex.html             -> /opt/app/views/foodindex.html
custom-views/profileindex.html          -> /opt/app/views/profileindex.html
custom-views/reportindex.html           -> /opt/app/views/reportindex.html
custom-views/service-worker.js          -> /opt/app/views/service-worker.js
custom-server/lib/server/treatments.js  -> /opt/app/lib/server/treatments.js
```

### `nightscout-uploader/`

The LibreLinkUp-to-Nightscout bridge.

Main file:

```text
nightscout-uploader/librelinkup_to_nightscout.py
```

Version:

```text
1.0.0
```

Expected configuration values are supplied by `.env` when deployed:

```text
LIBRELINKUP_EMAIL=
LIBRELINKUP_PASSWORD=
LIBRELINKUP_REGION=US
LIBRELINKUP_PATIENT_ID=
CGM_TIMEZONE=
NIGHTSCOUT_URL=
NIGHTSCOUT_API_SECRET=
UPLOADER_DB=/data/uploader.sqlite3
HTTP_TIMEOUT_SECONDS=30
POLL_INTERVAL_SECONDS=300
```


### `heartscout-server/`

The HeartScout FastAPI server.

Main file:

```text
heartscout-server/main.py
```

Version:

```text
1.0.0
```

Primary functions:

- Ingest heart-rate readings from an Android relay.
- Ingest step readings from an Android relay.
- Track relay/device status.
- Store local telemetry in SQLite.
- Serve a small web interface from `static/index.html`.
- Provide WebSocket updates for live heart-rate display.
- Query Nightscout recent glucose data when configured.

Exposed API routes:

```text
POST /api/heart
POST /api/steps
POST /api/relay/status
GET  /api/relay/status
GET  /api/heart/recent
GET  /api/summary/today
GET  /api/nightscout/recent
GET  /
WS   /ws/live
```

Expected configuration values:

```text
DATABASE_PATH=/data/heartscout.db
API_SECRET=
NIGHTSCOUT_URL=
NIGHTSCOUT_TOKEN=
```

The live database, logs, PID files, and virtual environment were not copied.


## Version file

Root `VERSION` currently contains:

```text
heartscout-nightscout-server-bundle 1.0.0
build: 20260607-000004
nightscout-upstream: 15.0.7
nightscout-image: nightscout/cgm-remote-monitor:latest
heartscout-server: 1.0.0
librelinkup-nightscout-uploader: 1.0.0
```

## Security and excluded files

The export intentionally excludes live secrets and runtime data.

Excluded examples:

```text
.env
API_SECRET.txt
*.db
*.log
*.pid
venv/
node_modules/
LibreView CSV imports
backup env files
```

Redacted config snapshots may exist as:

```text
.env.redacted
.env.example
```

Before deploying this anywhere, create new `.env` files with fresh local values.

## Running Nightscout locally

From the Nightscout service directory:

```bash
cd nightscout-service
docker compose up -d
```

Check status:

```bash
docker compose ps
docker compose logs -f nightscout
```

The original homelab deployment exposed Nightscout at:

```text
http://<your local ip address>:3000
```

For a new deployment, adjust `.env`, ports, DNS, reverse proxy, and authentication settings as needed.

## Running the LibreLinkUp uploader

From the uploader directory:

```bash
cd nightscout-uploader
cp .env.example .env
```

Edit `.env` with LibreLinkUp follower credentials and Nightscout details.

Test once:

```bash
docker compose run --rm librelinkup-uploader python /app/librelinkup_to_nightscout.py --once
```

Run continuously:

```bash
docker compose up -d --build
```

View logs:

```bash
docker compose logs -f librelinkup-uploader
```

## Running HeartScout server

From the HeartScout server directory:

```bash
cd heartscout-server
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with the needed values:

```text
DATABASE_PATH=./data/heartscout.db
API_SECRET=change-me
NIGHTSCOUT_URL=http://localhost:3000
NIGHTSCOUT_TOKEN=
```

Start the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Operational notes

- Nightscout is the CGM dashboard and MongoDB-backed historical store.
- The LibreLinkUp uploader is the CGM ingestion bridge.
- HeartScout is a separate health telemetry service for heart/step data.
- HeartScout and Nightscout can be linked through `NIGHTSCOUT_URL` and `NIGHTSCOUT_TOKEN`.
- This bundle is designed as a source/export snapshot, not a turnkey public cloud deployment.
- Do not expose these services publicly without HTTPS, authentication, firewall rules, and secret rotation.

## Medical safety note

This project is for personal telemetry, visualization, and historical analysis. It is not a certified medical device.
