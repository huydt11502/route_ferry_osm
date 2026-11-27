"""Evidence score for deciding whether a ferry is currently operating."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivityScore:
    score: int
    label: str
    reasons: tuple[str, ...]


def score_activity(
    *,
    google_status: str = "",
    recent_reviews: int = 0,
    recent_operational_mentions: int = 0,
    closure_signals: int = 0,
) -> ActivityScore:
    """Return a reproducible activity score from collected evidence.

    Google open/operating status gives +2, recent reviews +1, recent
    operational mentions from news/social +1, and each closure signal -3.
    Scores 3-5 mean active, 1-2 mean insufficient evidence, and <=0 means
    there are signs that the ferry has stopped operating.
    """

    score = 0
    reasons: list[str] = []
    normalized = google_status.strip().lower()
    if normalized in {"open", "operating", "đang hoạt động"}:
        score += 2
        reasons.append("Google đang hoạt động (+2)")
    if recent_reviews > 0:
        score += 1
        reasons.append(f"{recent_reviews} review gần đây (+1)")
    if recent_operational_mentions > 0:
        score += 1
        reasons.append(f"{recent_operational_mentions} nguồn gần đây ghi nhận vận hành (+1)")
    if closure_signals:
        penalty = 3 * closure_signals
        score -= penalty
        reasons.append(f"{closure_signals} tín hiệu đóng/ngừng (-{penalty})")
    score = max(-5, min(5, score))
    if score >= 3:
        label = "Còn hoạt động"
    elif score >= 1:
        label = "Chưa đủ dữ liệu"
    else:
        label = "Có dấu hiệu ngừng"
    return ActivityScore(score, label, tuple(reasons))
