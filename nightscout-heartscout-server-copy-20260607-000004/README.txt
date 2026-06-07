Nightscout + HeartScout server-side code export
Bundle version: 1.0.0
Build: 20260607-000004
Created on: 2026-06-07T00:00:10+00:00
Host: homelab01

Contents:
- nightscout-container-opt-app/ : /opt/app copied from the running Nightscout container, with node_modules removed.
- nightscout-service/           : Personal Server deployment/customization files from /home/deployer/services/nightscout, secrets and CSV imports excluded.
- nightscout-uploader/          : LibreLinkUp -> Nightscout uploader code from /home/deployer/services/nightscout-uploader, secrets excluded.
- heartscout-server/            : HeartScout FastAPI/server code from /home/deployer/projects/heartscout/server, excluding venv/data/logs/runtime pid files.
- metadata/                     : docker/container provenance and git status snapshots.

Security note:
Live .env files and API_SECRET.txt were not copied. Redacted .env snapshots are included where source .env files existed.
