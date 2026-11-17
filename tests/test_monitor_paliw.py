import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fuelprices import monitor_paliw
from fuelprices.models import FuelPrice, Notice
from fuelprices.parser import ParseError

FIXTURE = Path(__file__).parent / "fixtures" / "monitorpaliw_fragment.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_official_and_provisional_records():
    notices = monitor_paliw.parse_document(_payload())

    official = notices[1]
    assert official.eli == "MP/2026/1140"
    assert official.position == 1140
    assert official.valid_from == date(2026, 11, 14)
    assert official.prices["on"] == FuelPrice(gross=Decimal("7.52"), net=Decimal("6.96"))

    provisional = notices[2]
    assert provisional.eli == "GOV/2026-11-17"
    assert not provisional.is_official
    assert provisional.valid_from == date(2026, 11, 17)
    assert provisional.prices["pb98"].gross == Decimal("6.68")
    assert provisional.prices["pb98"].net is None
    assert provisional.source_url.startswith("https://www.gov.pl/web/energia/")


def test_fetch_new_returns_only_missing_or_upgraded_days(monkeypatch):
    monkeypatch.setattr(monitor_paliw, "fetch_json", lambda session, url: _payload())
    price = FuelPrice(gross=Decimal("6.02"))
    prices = {"pb95": price, "pb98": price, "on": price}
    history = [
        Notice("MP/2026/1134", 1134, date(2026, 11, 12), prices),  # mamy oficjalnie
        Notice("GOV/2026-11-14", 0, date(2026, 11, 13), prices),  # mamy tylko z gov.pl
    ]

    new = monitor_paliw.fetch_new(None, history)

    assert [n.eli for n in new] == ["MP/2026/1140", "GOV/2026-11-17"]


def test_rejects_unrealistic_price():
    payload = _payload()
    payload["records"][2]["brutto"]["on"] = 76.4
    with pytest.raises(ParseError, match="nierealna"):
        monitor_paliw.parse_document(payload)


def test_rejects_missing_price():
    payload = _payload()
    del payload["records"][2]["brutto"]["pb95"]
    with pytest.raises(ParseError):
        monitor_paliw.parse_document(payload)


def test_ignores_untrusted_source_links():
    payload = _payload()
    payload["records"][2]["sources"] = [{"type": "x", "url": "https://zla-strona.example/"}]
    assert monitor_paliw.parse_document(payload)[2].source_url == ""


def test_rejects_unexpected_format():
    with pytest.raises(ParseError):
        monitor_paliw.parse_document({"items": []})
