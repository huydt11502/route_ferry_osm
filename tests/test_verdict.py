from ferrycheck.models import Evidence, Review
from ferrycheck.verdict import evaluate


def test_valid_and_unknown():
    assert evaluate(Evidence(reviews=[Review("Hôm qua tôi vừa đi phà")])).verdict == "valid"
    assert evaluate(Evidence()).verdict == "unknown"


def test_outdated_and_conflict():
    assert evaluate(Evidence(reviews=[Review("bến đã ngừng hoạt động")])).verdict == "outdated"
    result = evaluate(Evidence(google_status="operating", reviews=[Review("vừa đi phà"), Review("đã có cầu thay phà")]))
    assert result.needs_manual == "Y"
