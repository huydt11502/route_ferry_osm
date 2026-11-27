# Ferry Route Validity Checker

CLI pilot for reviewing Vietnam ferry routes from OSM. The current scaffold supports UTF-8/BOM CSV input, deterministic link generation, offline verdict evaluation, CSV output, raw evidence folders, and SQLite checkpoints. Web providers can be added behind the `Evidence` model without changing output rules.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Pilot

```bash
python -m ferrycheck --input tests/fixtures/pilot_routes.csv --limit 3 --offline
```

The command writes the report, raw JSONL, evidence folder, checkpoint database, and log in the current directory.

Run the test suite:

```bash
python -m pytest -q
```

Run the standalone public-news/fare sample for one route:

```bash
python news_fare.py --name "Phà Cát Lái" --days 365 --out news_fare_cat_lai.json
```

The default pilot collects public Google News RSS and public Google search result links for Facebook/Instagram. Use `--offline` for deterministic local tests. The fixtures under `tests/fixtures/` document the expected evidence shapes for valid, outdated, conflicting, and unknown routes.

To include the Google Maps adapter after installing Playwright browsers:

```bash
playwright install chromium
python -m ferrycheck --input ferry_check_449.csv --limit 5 --maps
```

For a provider that returns structured place/review data, set one API key and select its adapter:

```powershell
$env:GOOGLE_MAPS_API_KEY = "..."
& .venv\Scripts\python.exe -m ferrycheck --input ferry_check_449.csv --limit 5 --maps --maps-provider places_api
```

The alternatives are `--maps-provider serpapi` with `SERPAPI_KEY`, or
`--maps-provider outscraper` with `OUTSCRAPER_API_KEY`. Check configuration without making
requests using `python -m ferrycheck --probe-providers`. Keys are never written to raw evidence.

For a small best-effort sample without an API key, `--maps-provider google_internal` makes
one low-volume request to the public Maps review feed. This endpoint is undocumented and
may return `review_text_gated`; it is not suitable for bulk scraping or guaranteed output.

## Current implementation boundary

Google Maps remains a separate Playwright adapter because its public markup is dynamic and selectors must be configured in `config.yaml`; until that adapter is enabled, the output records the Maps link and does not invent Google status/reviews. News and social collection are already provider-backed, cached, and public-only.
