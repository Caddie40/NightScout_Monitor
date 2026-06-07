#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, datetime as dt, hashlib, json, subprocess, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib import request, error

COLUMNS = ["Historic Glucose mg/dL", "Scan Glucose mg/dL"]

def parse_rows(path: Path, tzname: str):
    tz = ZoneInfo(tzname)
    rows=[]
    with path.open(newline="", encoding="utf-8-sig") as f:
        first=f.readline()
        reader=csv.DictReader(f)
        for idx,row in enumerate(reader, start=2):
            ts=row.get("Device Timestamp", "").strip()
            if not ts:
                continue
            for col in COLUMNS:
                raw=row.get(col, "").strip()
                if not raw:
                    continue
                try:
                    sgv=int(round(float(raw)))
                    local=dt.datetime.strptime(ts, "%m-%d-%Y %I:%M %p").replace(tzinfo=tz)
                except Exception as exc:
                    raise SystemExit(f"Parse failure line {idx}: {exc}: {row}")
                utc=local.astimezone(dt.timezone.utc)
                ms=int(utc.timestamp()*1000)
                source="libreview_historic" if col.startswith("Historic") else "libreview_scan"
                rows.append({
                    "type":"sgv",
                    "sgv":sgv,
                    "date":ms,
                    "dateString":utc.isoformat().replace("+00:00", "Z"),
                    "device":source,
                    "direction":"NONE",
                    "utcOffset":0,
                    "identifier":f"libreview:{source}:{ms}:{sgv}",
                })
    # de-dupe exact repeated source/timestamp/value from CSV itself
    seen=set(); out=[]
    for r in sorted(rows, key=lambda x: x["date"]):
        k=r["identifier"]
        if k not in seen:
            seen.add(k); out.append(r)
    return out

def mongo_count(start_ms:int, end_ms:int):
    js=f"db.entries.countDocuments({{date:{{$gte:{start_ms},$lte:{end_ms}}}}})"
    try:
        out=subprocess.check_output(["docker","exec","nightscout-mongo","mongosh","--quiet","nightscout","--eval",js], text=True).strip()
        return int(out.splitlines()[-1])
    except Exception:
        return None

def post_batch(url: str, secret: str, batch: list[dict]):
    h=hashlib.sha1(secret.encode()).hexdigest()
    data=json.dumps(batch).encode()
    req=request.Request(url.rstrip()+"/api/v1/entries.json", data=data, method="POST", headers={"content-type":"application/json", "api-secret":h})
    with request.urlopen(req, timeout=60) as resp:
        body=resp.read().decode("utf-8", "replace")
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {body[:500]}")
        return body

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--timezone", default="<your specified timezone>")
    ap.add_argument("--nightscout-url", default="http://<your local ip address>:3000")
    ap.add_argument("--secret-file", type=Path, default=Path("path/to/your/API/Secret/Here"))
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--batch-size", type=int, default=500)
    args=ap.parse_args()
    entries=parse_rows(args.csv, args.timezone)
    if not entries:
        raise SystemExit("No glucose entries parsed")
    start,end=entries[0]["date"], entries[-1]["date"]
    existing=mongo_count(start,end)
    bydev={}
    for e in entries: bydev[e["device"]]=bydev.get(e["device"],0)+1
    print(json.dumps({
        "csv": str(args.csv),
        "parsed_entries": len(entries),
        "by_device": bydev,
        "first_utc": entries[0]["dateString"],
        "last_utc": entries[-1]["dateString"],
        "min_sgv": min(e["sgv"] for e in entries),
        "max_sgv": max(e["sgv"] for e in entries),
        "existing_nightscout_entries_in_range": existing,
        "commit": args.commit,
    }, indent=2))
    if not args.commit:
        print("DRY RUN ONLY. Re-run with --commit to upload.")
        return
    secret=args.secret_file.read_text().strip()
    uploaded=0
    for i in range(0, len(entries), args.batch_size):
        batch=entries[i:i+args.batch_size]
        post_batch(args.nightscout_url, secret, batch)
        uploaded += len(batch)
        print(f"uploaded {uploaded}/{len(entries)}", flush=True)
        time.sleep(0.1)
    print("IMPORT COMPLETE")
if __name__ == "__main__":
    main()
