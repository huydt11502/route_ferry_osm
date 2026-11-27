from dataclasses import dataclass
from datetime import date
import re

from .models import Evidence

CLOSURE = re.compile(r"ngừng hoạt động|đã ngừng|dừng hoạt động|không còn hoạt động|đã có cầu|cầu thay phà|không còn phà|đóng bến|xóa bỏ bến", re.I)
OPERATION = re.compile(r"đi phà|qua phà|phà chạy|chờ phà|xếp hàng|vừa đi", re.I)


@dataclass
class Verdict:
    verdict: str
    confidence: str
    reason: str
    link_bang_chung: str = ""
    last_evidence_date: str = ""
    needs_manual: str = "Y"


def evaluate(evidence: Evidence, today: date | None = None) -> Verdict:
    closed = evidence.google_status.lower() in {"permanently closed", "đã đóng cửa", "closed permanently"}
    operation_reviews = [r for r in evidence.reviews if OPERATION.search(r.text)]
    closure_reviews = [r for r in evidence.reviews if CLOSURE.search(r.text)]
    operation_news = [n for n in evidence.news if OPERATION.search(f"{n.title} {n.snippet}")]
    closure_news = [n for n in evidence.news if CLOSURE.search(f"{n.title} {n.snippet}")]
    operations = operation_reviews + operation_news
    closures = closure_reviews + closure_news
    conflict = bool(operations and (closures or closed))
    if conflict:
        verdict, reason = "unknown", "Bằng chứng Google và nguồn khác mâu thuẫn"
    elif closed or (closures and not operations):
        verdict, reason = "outdated", "Có bằng chứng gần đây cho thấy bến phà đã ngừng hoạt động"
    elif operations:
        verdict, reason = "valid", f"Có {len(operations)} bằng chứng gần đây cho thấy phà đang hoạt động"
    else:
        verdict, reason = "unknown", "Chưa có bằng chứng đủ rõ về tình trạng hoạt động"
    confidence = "low" if conflict else "high" if len(operation_reviews) >= 3 or (evidence.google_status.lower() in {"operating", "open", "đang hoạt động"} and operation_reviews) else "medium" if operations or closures else "low"
    dates = [x.date for x in evidence.reviews + evidence.news if x.date]
    latest = max(dates).isoformat() if dates else ""
    return Verdict(verdict, confidence, reason, needs_manual="Y" if verdict == "unknown" or confidence == "low" or conflict else "N", last_evidence_date=latest)
