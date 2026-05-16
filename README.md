# West Bank Civilian Harm Tracker

Static web app + data pipeline for [PALSHIELD's](https://palshield.org) interactive map of documented settler and Israeli military violence against Palestinian civilians in the West Bank.

Served via GitHub Pages. Embedded in WordPress via `<iframe>`.

## Repo layout

```
.
├── west-bank-incident-map.html   # the front-end (loads incidents.json)
├── incidents.json                # OUTPUT — refreshed daily by GitHub Actions
├── masafer_yatta_static.json     # persistent layer, manually updated
├── refresh.py                    # the refresh script
├── requirements.txt
└── .github/
    └── workflows/
        └── refresh.yml           # daily cron + manual trigger
```

## How the refresh works

1. **GitHub Actions** runs `refresh.py` daily at 06:00 UTC (also triggerable manually from the Actions tab).
2. The script authenticates with ACLED via OAuth password grant.
3. Pulls all West Bank events since 2016 (paginated, 5000 rows per call).
4. Filters to: aggressor = Israeli military / settlers / police / settlement emergency squad / private security / unidentified Israeli; victim = Palestinian civilians. Drops everything else (Palestinian armed groups, intra-Palestinian incidents, protest activity — covered elsewhere).
5. Deduplicates by (date, lat, lng, actor, notes prefix).
6. Merges with `masafer_yatta_static.json` so the South Hebron Hills granular layer is preserved.
7. Writes `incidents.json`, commits if changed.
8. GitHub Pages serves the updated file. The map picks it up on next page load (no cache, no CDN propagation delay).

## Required GitHub Secrets

Settings → Secrets and variables → Actions:

- `ACLED_EMAIL` — the email registered at [acleddata.com](https://acleddata.com/user/register)
- `ACLED_PASSWORD` — that account's password

Use an institutional email (`@palshield.org` or `@oleaobscura.com`) for the ACLED registration to get higher rate limits and better support.

## Updating the Masafer Yatta layer

The Masafer Yatta data does not have a public API. When the documentation project publishes a new dataset, regenerate `masafer_yatta_static.json` locally and commit it. The next scheduled refresh (or a manual workflow run) will pick it up automatically.

## Running locally

```bash
pip install -r requirements.txt
export ACLED_EMAIL='you@palshield.org'
export ACLED_PASSWORD='...'
python refresh.py
python -m http.server 8000     # then open http://localhost:8000/west-bank-incident-map.html
```

## Data terms

ACLED data is used under their [Terms of Use & Attribution Policy](https://acleddata.com/terms-of-use/). Attribution is displayed in the app methodology section. The output JSON is a heavily filtered, reformatted subset — not a redistribution of ACLED's raw data.
