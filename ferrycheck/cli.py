import argparse
import json
import logging
import os
from pathlib import Path

from .checkpoint import Checkpoint
from .input import load_routes
from .models import Evidence
from .output import make_result, write_raw, write_raw_jsonl, write_xlsx
from .providers import OfflineProvider, ScrapeProvider
from .verdict import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description="Check validity of Vietnamese ferry routes")
    parser.add_argument("--input"); parser.add_argument("--output", default="ferry_check_result.xlsx")
    parser.add_argument("--raw-output", default="results_raw.jsonl")
    parser.add_argument("--limit", type=int, default=5); parser.add_argument("--evidence-dir", default="evidence")
    parser.add_argument("--checkpoint", default="ferrycheck.sqlite")
    parser.add_argument("--offline", action="store_true", help="do not make network requests")
    parser.add_argument("--maps", action="store_true", help="also collect public Google Maps data with Playwright")
    parser.add_argument("--maps-provider", choices=("playwright", "google_internal", "places_api", "serpapi", "outscraper"), default="playwright",
                        help="Google Maps source when --maps is enabled")
    parser.add_argument("--probe-providers", action="store_true", help="report configured API providers without scraping")
    args = parser.parse_args(); logging.basicConfig(filename="run.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.probe_providers:
        print(json.dumps({name: {"env": env, "configured": bool(os.environ.get(env, "").strip())}
                          for name, env in (("google_places_api", "GOOGLE_MAPS_API_KEY"),
                                            ("serpapi", "SERPAPI_KEY"),
                                            ("outscraper", "OUTSCRAPER_API_KEY"))}, ensure_ascii=False, indent=2))
        return
    if not args.input:
        parser.error("--input is required unless --probe-providers is used")
    routes = load_routes(args.input)[:args.limit]; checkpoint = Checkpoint(args.checkpoint); rows = []; raw_records = []
    provider = OfflineProvider() if args.offline else ScrapeProvider(maps=args.maps, maps_provider=args.maps_provider)
    try:
        for route in routes:
            cached = checkpoint.get(route.osm_id)
            if cached:
                saved = json.loads(cached)
                if "sheet" in saved:
                    rows.append(saved["sheet"]); raw_records.append(saved.get("raw", {})); continue
            try:
                evidence = provider.collect(route)
            except Exception as exc:  # keep one route failure from losing the whole run
                logging.exception("collection failed for %s", route.osm_id)
                evidence = Evidence(raw={"provider_error": str(exc)})
            row, raw = make_result(route, evidence, evaluate(evidence)); write_raw(args.evidence_dir, route, evidence)
            checkpoint.save(route.osm_id, json.dumps({"sheet": row, "raw": raw}, ensure_ascii=False, default=str)); rows.append(row); raw_records.append(raw)
    finally:
        checkpoint.close()
    write_xlsx(args.output, rows); write_raw_jsonl(args.raw_output, raw_records)
