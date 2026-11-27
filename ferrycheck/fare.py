import re
from typing import Any

_AMOUNT = re.compile(r"(?P<number>\d[\d.,]*)\s*(?P<unit>k|nghìn|ngàn|đ|đồng|vnd)?", re.I)
_VEHICLES = (("xe máy", "motorcycle"), ("xe gắn máy", "motorcycle"), ("người đi bộ", "pedestrian"),
             ("ô tô", "car"), ("xe hơi", "car"), ("xe tải", "truck"), ("xe đạp", "bicycle"))


def parse_fares(text: str, source_url: str = "", source_date: str = "", *, require_vehicle: bool = False) -> list[dict[str, Any]]:
    result = []
    lower = text.lower()
    for match in _AMOUNT.finditer(lower):
        if not match.group("unit"):
            continue
        raw = match.group("number").replace(".", "").replace(",", "")
        try:
            unit = match.group("unit").lower()
            amount = int(raw) * 1000 if unit == "k" or unit.startswith("ngh") or unit.startswith("ngÃ") else int(raw)
        except ValueError:
            continue
        vehicle = ""
        context = lower[max(0, match.start() - 45):match.end() + 45]
        for label, normalized in _VEHICLES:
            if label in context:
                vehicle = normalized
                break
        if amount > 0 and (not require_vehicle or vehicle):
            result.append({"amount_vnd": amount, "vehicle": vehicle, "source_url": source_url, "source_date": source_date})
    return result
