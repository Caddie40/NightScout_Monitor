# LibreLinkUp -> Nightscout uploader

This service pulls readings from a LibreLinkUp follower account and uploads SGV entries to local Nightscout.

Nightscout URL used by the container:

```text
http://host.docker.internal:<your preferred port here>
```

Host Nightscout URL for browser/uploader verification:

```text
http://<local ip address>:<your preferred port numnber here>
```

## Required user action

1. On Android, open the FreeStyle Libre 3 app.
2. Find **Connected Apps**, **Share**, or **LibreLinkUp**.
3. Invite a LibreLinkUp follower account.
   - This can be a second email you control.
   - It should not be the same login if Abbott refuses self-following.
4. Install/open **LibreLinkUp** and accept the invitation.
5. Put the follower login into `.env` on this server.

## Configure

```bash
cd /home/deployer/services/nightscout-uploader
cp .env.example .env
nano .env
```

Required fields:

```text
LIBRELINKUP_EMAIL=
LIBRELINKUP_PASSWORD=
LIBRELINKUP_REGION=US
```

`NIGHTSCOUT_API_SECRET` is already populated from the local Nightscout deployment if CODEX installed this directory.

## Test once

```bash
cd /home/deployer/services/nightscout-uploader
docker compose run --rm librelinkup-uploader python /app/librelinkup_to_nightscout.py --once
```

Expected success resembles:

```text
complete fetched=... uploaded=... skipped=...
```

If you see `no shared patients`, accept the LibreLinkUp invitation in the LibreLinkUp app first.

## Start continuous uploader

```bash
docker compose up -d --build
```

## Logs

```bash
docker compose logs -f librelinkup-uploader
```

## Stop

```bash
docker compose down
```

## Security note

Nightscout is currently LAN HTTP only. Do not expose your port publicly until HTTPS/reverse proxy/auth policy are configured.
