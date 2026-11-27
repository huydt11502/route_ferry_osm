from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
import re

try:
    import dateparser
except ImportError:  # pragma: no cover - used only in minimal installations
    dateparser = None


def parse_date(value: str, *, relative_base: date | None = None) -> date | None:
    """Parse Vietnamese/English absolute or relative dates into an ISO-ready date."""
    if not value:
        return None
    if dateparser is None:
        try:
            parsed = parsedate_to_datetime(value)
            return parsed.date()
        except (TypeError, ValueError, IndexError):
            pass
        match = re.search(r"(\d+)\s*(?:tháng|month|months)\s*(?:trước|ago)", value.lower())
        if match and relative_base:
            return relative_base - timedelta(days=int(match.group(1)) * 30)
        return None
    settings = {"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DAY_OF_MONTH": "first"}
    if relative_base:
        settings["RELATIVE_BASE"] = datetime.combine(relative_base, datetime.min.time())
    parsed = dateparser.parse(value, languages=["vi", "en"], settings=settings)
    return parsed.date() if parsed else None


def parse_date_detail(value: str, *, relative_base: date | None = None) -> tuple[date | None, bool]:
    """Return (date, approximate) for review labels; month-level relative labels are approximate."""
    parsed = parse_date(value, relative_base=relative_base)
    normalized = value.lower()
    approximate = bool(re.search(r"tháng|month|months", normalized)) and not re.search(r"\d{1,2}[/-]\d{1,2}", normalized)
    return parsed, approximate
