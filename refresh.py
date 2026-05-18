#!/usr/bin/env python3
"""
refresh.py — Refresh the West Bank incident dataset for PALSHIELD's map.

Runs in GitHub Actions on a schedule. Pulls fresh data from ACLED's API
(OAuth password grant), filters to Israeli aggressor / Palestinian civilian
victim, deduplicates, merges with the static Masafer Yatta documentation
dataset, and writes `incidents.json` for the front-end to consume.

Env vars (set as GitHub Secrets):
  ACLED_EMAIL       - email registered with acleddata.com
  ACLED_PASSWORD    - account password

Files in the repo:
  masafer_yatta_static.json - persistent Masafer Yatta records (manual updates)
  incidents.json            - OUTPUT, served to the front-end
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT          = Path(__file__).parent
OUTPUT_PATH   = ROOT / "incidents.json"
MASAFER_PATH  = ROOT / "masafer_yatta_static.json"

TOKEN_URL     = "https://acleddata.com/oauth/token"
API_URL       = "https://acleddata.com/api/acled/read"
PAGE_SIZE     = 5000

ISRAELI_PATTERNS = [
    "Military Forces of Israel",
    "Settlers (Israel)",
    "Police Forces of Israel",
    "Settlement Emergency Squad",
    "Private Security Forces (Israel)",
    "Unidentified Armed Group (Israel)",
]
ISRAELI_RE = re.compile("|".join(re.escape(p) for p in ISRAELI_PATTERNS))

PERPETRATORS = [
    "Israeli Military",          # 0
    "Settlers",                  # 1
    "Israeli Police",            # 2
    "Private Security (Israel)", # 3
    "Unidentified (Israeli)",    # 4
]

SOURCES = [
    {"code": "ACLED", "name": "ACLED — Armed Conflict Location & Event Data",
     "url": "https://acleddata.com"},
    {"code": "MYDoc", "name": "Masafer Yatta Field Documentation",
     "url": ""},
]


def categorize_actor(actor: str) -> int:
    if not actor:
        return 4
    if "Settler" in actor or "Settlement" in actor:
        return 1
    if "Military Forces" in actor:
        return 0
    if "Police Forces" in actor:
        return 2
    if "Private Security" in actor:
        return 3
    return 4


def clean_notes(n: str, limit: int = 220) -> str:
    if not n:
        return ""
    n = re.sub(r"\s+", " ", str(n)).strip()
    if len(n) <= limit:
        return n
    return n[:limit].rsplit(" ", 1)[0] + "…"


def get_access_token(email: str, password: str) -> str:
    """OAuth password grant. Returns a 24h bearer token."""
    resp = requests.post(TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "username":   email,
        "password":   password,
        "grant_type": "password",
        "client_id":  "acled",
        "scope":      "authenticated",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_acled(token: str) -> list[dict]:
    """Fetch all West Bank events since 2016, paginated."""
    rows = []
    page = 1
    while True:
        params = {
            "_format":     "json",
            "country":     "Palestine",
            "admin1":      "West Bank",
            "event_date":  "2016-01-01|2099-12-31",
            "event_date_where": "BETWEEN",
            "limit":       PAGE_SIZE,
            "page":        page,
        }
        r = requests.get(API_URL, params=params, headers={
            "Authorization": f"Bearer {token}",
        }, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data.get("success") is False:
            raise RuntimeError(f"ACLED error: {data}")
        batch = data.get("data", [])
        if not batch:
            break
        rows.extend(batch)
        print(f"  page {page}: +{len(batch)} rows (cumulative {len(rows)})", flush=True)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return rows


def filter_and_shape(raw: list[dict]) -> list[dict]:
    """Apply Israeli-aggressor / Palestinian-civilian filter, shape for app."""
    out  = []
    seen = set()
    for r in raw:
        actor1 = r.get("actor1", "") or ""
        actor2 = r.get("actor2", "") or ""
        if not ISRAELI_RE.search(actor1):
            continue
        if actor2 != "Civilians (Palestine)":
            continue
        try:
            lat = float(r.get("latitude"))
            lng = float(r.get("longitude"))
        except (TypeError, ValueError):
            continue
        date = r.get("event_date", "")
        notes = r.get("notes", "") or ""
        # dedupe key
        key = (date, round(lat, 5), round(lng, 5), actor1, notes[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "d":   date,
            "lat": round(lat, 5),
            "lng": round(lng, 5),
            "g":   r.get("admin2", ""),
            "l":   r.get("location", ""),
            "p":   categorize_actor(actor1),
            "f":   int(r.get("fatalities") or 0),
            "n":   clean_notes(notes),
            "s":   0,  # source: ACLED
        })
    return out


def load_masafer_static() -> tuple[list[dict], list[str]]:
    """Load the static Masafer Yatta dataset from the repo, if present."""
    if not MASAFER_PATH.exists():
        print(f"  (no {MASAFER_PATH.name} found — skipping)", flush=True)
        return [], []
    with MASAFER_PATH.open() as f:
        payload = json.load(f)
    return payload.get("incidents", []), payload.get("violation_types", [])


def main() -> int:
    email    = os.environ.get("ACLED_EMAIL")
    password = os.environ.get("ACLED_PASSWORD")
    if not email or not password:
        print("ERROR: set ACLED_EMAIL and ACLED_PASSWORD env vars", file=sys.stderr)
        return 1

    print("→ Authenticating with ACLED…", flush=True)
    token = get_access_token(email, password)
    print("  ✓ token acquired", flush=True)

    print("→ Fetching West Bank events…", flush=True)
    raw = fetch_acled(token, email, password)
    print(f"  ✓ {len(raw):,} raw rows", flush=True)

    print("→ Filtering and shaping…", flush=True)
    acled_records = filter_and_shape(raw)
    print(f"  ✓ {len(acled_records):,} ACLED records after filter+dedupe", flush=True)

    print("→ Loading Masafer Yatta static dataset…", flush=True)
    masafer_records, violation_types = load_masafer_static()
    print(f"  ✓ {len(masafer_records):,} Masafer Yatta records", flush=True)

    incidents    = acled_records + masafer_records
    governorates = sorted({r["g"] for r in acled_records if r.get("g")})
    date_start   = min(r["d"] for r in incidents)
    date_end     = max(r["d"] for r in incidents)

    payload = {
        "generated":       datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "date_range":      {"start": date_start, "end": date_end},
        "perpetrators":    PERPETRATORS,
        "sources":         SOURCES,
        "governorates":    governorates,
        "violation_types": violation_types,
        "hrp_monthly":     [],
        "incidents":       incidents,
    }

    OUTPUT_PATH.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"→ Wrote {OUTPUT_PATH.name}: {len(incidents):,} incidents, {size_kb:.0f} KB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
