# Nightscout on homelab01

Path: `/home/deployer/services/nightscout`

## Commands

```bash
cd /home/deployer/services/nightscout
docker compose up -d
docker compose ps
docker compose logs -f nightscout
```

## Access

Local/LAN URL:

```text
http://<your local ip address>:3000
```

Nightscout is configured with `AUTH_DEFAULT_ROLES=denied`, so viewing requires authentication/token/API secret. The API secret is in `.env`.

## Uploader target

Use the Nightscout URL plus API secret from `.env` in the Android uploader/bridge app.

Common API base format used by uploaders:

```text
http://API_SECRET@<your local ip address>:3000/api/v1/
```

If an uploader asks separately for URL and secret:

```text
URL: http://<your local ip address>:3000
API_SECRET: see .env
```

## Libre 3 Plus note

Nightscout is now the receiver/database/dashboard. Libre 3 Plus still needs an Android-side uploader or bridge path such as xDrip+/Juggluco/LibreLinkUp bridge depending on what works with the installed Libre app and region.

## Safety

Nightscout is supplemental monitoring and historical telemetry. Do not treat it as a replacement for the Libre app's safety alerts.
