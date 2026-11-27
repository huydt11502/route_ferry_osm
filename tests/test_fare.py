from ferrycheck.fare import parse_fares


def test_fare_formats():
    fares = parse_fares("xe máy 5k, người đi bộ 20 nghìn, ô tô 50.000đ")
    assert [item["amount_vnd"] for item in fares] == [5000, 20000, 50000]
    assert fares[0]["vehicle"] == "motorcycle"
