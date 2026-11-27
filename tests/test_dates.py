from datetime import date

from ferrycheck.dates import parse_date


def test_relative_dates_in_vietnamese_and_english():
    base = date(2026, 11, 27)
    assert parse_date("2 tháng trước", relative_base=base) is not None
    assert parse_date("a month ago", relative_base=base) is not None
