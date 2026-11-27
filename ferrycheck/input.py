import csv
from pathlib import Path

from .models import Route


def load_routes(path: str | Path) -> list[Route]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return [Route(
            osm_id=(row.get("osm_id") or "").strip(), name=(row.get("name") or "").strip(),
            toa_do=(row.get("toa_do") or "").strip(), dai_m=(row.get("dai_m") or "").strip(),
            osm_tag_xe_nguoi=(row.get("osm_tag_xe_nguoi") or "").strip(),
            osm_duration=(row.get("osm_duration") or "").strip(), osm_operator=(row.get("osm_operator") or "").strip(),
            xa_huyen_tinh=(row.get("xa_huyen_tinh") or "").strip(), fee=(row.get("fee") or "").strip(),
            charge=(row.get("charge") or "").strip(), opening_hours=(row.get("opening_hours") or "").strip(),
        ) for row in rows if (row.get("osm_id") or "").strip()]
