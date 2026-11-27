from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .links import build_links
from .models import Evidence, Route
from .verdict import Verdict

SHEET_COLUMNS = ["osm_id", "ten", "khu_vuc", "ket_luan", "ly_do", "google", "binh_luan", "hinh_anh", "link_BL", "bao_chi", "link_bao", "facebook", "instagram", "gia_ve", "nguon_gia", "ngay_gia", "ghi_chu"]
_CONFIDENCE = {"high": "Cao", "medium": "Trung bình", "low": "Thấp"}
_LABEL = {"valid": "Còn hoạt động", "outdated": "Đã ngừng", "unknown": "Chưa rõ"}
_VEHICLE = {"motorcycle": "Xe máy", "pedestrian": "Người đi bộ", "car": "Ô tô", "truck": "Xe tải", "bicycle": "Xe đạp"}


def _date(value: date | str | None) -> str:
    return value.isoformat() if isinstance(value, date) else (value or "")[:10]


def _display_date(value: date | str | None) -> str:
    try:
        return datetime.strptime(_date(value), "%Y-%m-%d").strftime("%d/%m/%y")
    except ValueError:
        return _date(value)


def _google_text(evidence: Evidence) -> str:
    if not any((evidence.google_status, evidence.rating, evidence.review_count, evidence.reviews)):
        return "–"
    status = {"operating": "Đang hoạt động", "open": "Đang hoạt động", "permanently closed": "Đã đóng cửa"}.get(evidence.google_status, evidence.google_status or "Chưa rõ")
    rating = f" · {evidence.rating}★ ({evidence.review_count})" if evidence.rating else ""
    return f"{status}{rating} · {len(evidence.reviews)} BL / {evidence.review_window}"


def _review_text(evidence: Evidence) -> str:
    lines = []
    for review in evidence.reviews[:3]:
        approx = "≈" if review.approx else ""
        stars = f"★{review.rating} " if review.rating else ""
        lines.append(f"{approx}{_display_date(review.date)} {stars}{review.text[:57]}…")
    return "\n".join(lines) if lines else "–"


def _news_data(evidence: Evidence) -> tuple[str, str]:
    relevant = sorted((item for item in evidence.news if item.keywords), key=lambda item: item.date or date.min, reverse=True)
    if not relevant:
        return "–", ""
    first = relevant[0]
    return f"{_display_date(first.date)} · {first.outlet} · {', '.join(first.keywords)}", first.url


def _fare_data(evidence: Evidence) -> tuple[str, str, str, bool]:
    if not evidence.fares:
        return "–", "", "–", False
    newest = max(evidence.fares, key=lambda fare: fare.get("source_date", ""))
    source_url, source_date = newest.get("source_url", ""), newest.get("source_date", "")
    same_source = []
    seen = set()
    for fare in evidence.fares:
        key = (fare.get("source_url"), fare.get("source_date"), fare.get("vehicle"), fare.get("amount_vnd"))
        if fare.get("source_url") == source_url and fare.get("source_date") == source_date and key not in seen:
            seen.add(key); same_source.append(fare)
    text = " · ".join(f"{_VEHICLE.get(fare.get('vehicle', ''), fare.get('vehicle', '')) or 'Khác'} {fare['amount_vnd'] // 1000 if fare['amount_vnd'] % 1000 == 0 else fare['amount_vnd']}k" for fare in same_source)
    try:
        stale = date.today() - date.fromisoformat(source_date) > timedelta(days=365)
    except ValueError:
        stale = True
    return text or "–", source_url, f"{_display_date(source_date)} {'có thể cũ' if stale else 'mới'}", stale


def make_result(route: Route, evidence: Evidence, verdict: Verdict) -> tuple[dict[str, str], dict[str, Any]]:
    links = build_links(route); news_text, news_url = _news_data(evidence); fare_text, fare_url, fare_date, fare_stale = _fare_data(evidence)
    manual = verdict.verdict == "unknown" or verdict.confidence == "low"
    conclusion = f"{_LABEL[verdict.verdict]} · {_CONFIDENCE[verdict.confidence]}" + (" · cần kiểm tra tay" if manual else "")
    notes = []
    if not evidence.place_url:
        notes.append("chưa lấy được place/review Google Maps; mở link BL để kiểm tra")
    if not evidence.facebook_links:
        notes.append("chưa thấy direct Facebook public")
    if not evidence.instagram_links:
        notes.append("chưa thấy direct Instagram public")
    if fare_stale:
        notes.append("giá từ nguồn cũ, kiểm tra lại")
    if not route.xa_huyen_tinh:
        notes.append("điền xã/huyện/tỉnh rồi tìm lại")
    image_text = "\n".join(item.get("url", "") for item in evidence.raw.get("review_images", []) if item.get("url")) or "–"
    sheet = {"osm_id": route.osm_id, "ten": route.name or "(không tên)", "khu_vuc": route.xa_huyen_tinh or "–", "ket_luan": conclusion,
             "ly_do": verdict.reason[:100], "google": _google_text(evidence), "binh_luan": _review_text(evidence), "hinh_anh": image_text, "link_BL": "Xem BL" if evidence.place_url else "Tìm BL",
             "bao_chi": news_text, "link_bao": "Xem báo" if news_url else "Tìm báo", "facebook": "FB" if evidence.facebook_links else "Tìm FB",
             "instagram": "IG" if evidence.instagram_links else "Tìm IG", "gia_ve": fare_text, "nguon_gia": "Nguồn" if fare_url else "–",
             "ngay_gia": fare_date, "ghi_chu": "; ".join(notes) or "–"}
    hyperlinks = {"osm_id": links["link_osm"], "link_BL": evidence.place_url or links["link_google_maps"], "link_bao": news_url or links["link_google_news"],
                  "nguon_gia": fare_url, "hinh_anh": next((item.get("url", "") for item in evidence.raw.get("review_images", []) if item.get("url")), ""), "facebook": evidence.facebook_links[0].get("url", "") if evidence.facebook_links else links["link_facebook"],
                  "instagram": evidence.instagram_links[0].get("url", "") if evidence.instagram_links else links["link_instagram"]}
    raw = {"osm_id": route.osm_id, "verdict": {"label": verdict.verdict, "confidence": verdict.confidence, "reason": verdict.reason, "manual": manual},
           "google": {"status": evidence.google_status, "rating": evidence.rating, "count": evidence.review_count, "window": evidence.review_window, "in_window": len(evidence.reviews), "place_url": evidence.place_url, "comments": [asdict(review) for review in evidence.reviews]},
           "news": [asdict(item) for item in evidence.news], "social": {"fb": evidence.facebook_links, "ig": evidence.instagram_links},
           "fee": {"text": fare_text, "url": fare_url, "date": _date(next((fare.get("source_date") for fare in evidence.fares), "")), "stale": fare_stale},
           "collected_at": datetime.now().astimezone().isoformat(), "raw": evidence.raw}
    return {**sheet, "_hyperlinks": hyperlinks}, raw


def write_xlsx(path: str | Path, rows: list[dict[str, str]]) -> None:
    workbook = Workbook(); sheet = workbook.active; sheet.title = "result"; sheet.freeze_panes = "A2"
    sheet.append(SHEET_COLUMNS)
    for row in rows:
        sheet.append([row.get(column, "") for column in SHEET_COLUMNS])
    for column in range(1, len(SHEET_COLUMNS) + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 42 if column in (5, 7, 16) else 22
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="1F4E78")
    for row_number, row in enumerate(rows, 2):
        for column, url in row.get("_hyperlinks", {}).items():
            if url:
                cell = sheet.cell(row_number, SHEET_COLUMNS.index(column) + 1); cell.hyperlink = url; cell.style = "Hyperlink"
        for cell in sheet[row_number]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        value = sheet.cell(row_number, 4).value or ""; colour = "C6EFCE" if "Còn hoạt động" in value else "FFC7CE" if "Đã ngừng" in value else "FFF2CC"
        sheet.cell(row_number, 4).fill = PatternFill("solid", fgColor=colour)
    workbook.save(path)


def write_raw_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def write_raw(evidence_dir: str | Path, route: Route, evidence: Evidence) -> None:
    target = Path(evidence_dir) / route.osm_id.replace("/", "_"); target.mkdir(parents=True, exist_ok=True)
    (target / "evidence.json").write_text(json.dumps(asdict(evidence), ensure_ascii=False, default=str, indent=2), encoding="utf-8")
