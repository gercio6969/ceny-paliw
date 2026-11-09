from datetime import UTC, date, datetime

import pytest

from fuelprices import market


def test_parse_nbp():
    payload = {
        "rates": [
            {"effectiveDate": "2026-11-05", "mid": 3.7012},
            {"effectiveDate": "2026-11-06", "mid": 3.6890},
        ]
    }
    usd = market.parse_nbp(payload)
    assert usd["value"] == 3.689
    assert usd["previous"] == 3.7012
    assert usd["date"] == "2026-11-06"
    assert usd["history"][0] == ["2026-11-05", 3.7012]


def test_parse_nbp_rejects_empty():
    with pytest.raises(market.MarketError):
        market.parse_nbp({"rates": []})


def test_parse_yahoo_skips_missing_closes():
    ts = int(datetime(2026, 11, 6, 15, tzinfo=UTC).timestamp())
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [ts - 86400, ts],
                    "indicators": {"quote": [{"close": [None, 64.21]}]},
                }
            ]
        }
    }
    assert market.parse_yahoo(payload) == [(date(2026, 11, 6), 64.21)]


def test_parse_yahoo_bad_format():
    with pytest.raises(market.MarketError):
        market.parse_yahoo({"chart": {"result": None}})


def test_parse_fred_csv_skips_missing_values():
    text = "observation_date,DCOILBRENTEU\n2026-10-30,63.10\n2026-11-02,.\n2026-11-03,64.02\n"
    assert market.parse_fred_csv(text) == [(date(2026, 10, 30), 63.10), (date(2026, 11, 3), 64.02)]


def test_parse_orlen_maps_products_and_converts_units():
    payload = [
        {"productName": "Pb95", "value": 5344, "effectiveDate": "2026-11-09T00:00:00"},
        {"productName": "Pb98", "value": 5990, "effectiveDate": "2026-11-09T00:00:00"},
        {"productName": "ONEkodiesel", "value": 5522, "effectiveDate": "2026-11-09T00:00:00"},
        {"productName": "ON Arktyczny 2", "value": 5700, "effectiveDate": "2026-11-09T00:00:00"},
        {"productName": "Pb95", "value": None},
    ]
    result = market.parse_orlen(payload)
    assert result["pb95"] == {"value": 5.344, "per_m3": 5344.0, "date": "2026-11-09"}
    assert result["on"]["value"] == 5.522
    assert set(result) == {"pb95", "pb98", "on"}


def test_parse_orlen_rejects_unknown_format():
    with pytest.raises(market.MarketError):
        market.parse_orlen({"error": "x"})


def _ok(value):
    return lambda session: {"value": value, "date": "2026-11-09"}


def _fail(session):
    raise ConnectionError("down")


def test_update_keeps_stale_value_on_failure_and_computes_pln():
    previous = {"items": {"orlen_shares": {"value": 80.5, "stale": False}}}
    fetchers = {
        "brent": _ok(64.0),
        "usdpln": _ok(3.7),
        "orlen_shares": _fail,
        "orlen_wholesale": _fail,
    }

    doc = market.update(previous, session=None, fetchers=fetchers)

    assert doc["items"]["brent"]["value_pln"] == 236.8
    assert doc["items"]["orlen_shares"] == {"value": 80.5, "stale": True}
    assert "orlen_wholesale" not in doc["items"]  # brak poprzedniej wartości


def test_update_skips_pln_when_rate_is_stale():
    previous = {"items": {"usdpln": {"value": 3.7, "stale": False}}}
    doc = market.update(previous, session=None, fetchers={"brent": _ok(64.0), "usdpln": _fail})
    assert "value_pln" not in doc["items"]["brent"]


def test_series_drops_nan_and_out_of_range():
    points = [
        (date(2026, 11, 3), float("nan")),
        (date(2026, 11, 4), 63.0),
        (date(2026, 11, 5), 9999.0),
        (date(2026, 11, 6), 64.0),
    ]
    series = market._series(points, 5.0, 500.0)
    assert series["history"] == [["2026-11-04", 63.0], ["2026-11-06", 64.0]]


def test_series_all_invalid_raises():
    with pytest.raises(market.MarketError):
        market._series([(date(2026, 11, 3), float("inf"))], 5.0, 500.0)
