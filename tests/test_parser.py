from datetime import date
from decimal import Decimal

import pytest

from fuelprices.parser import ParseError, normalize, parse_issue_date, parse_prices


def test_parses_all_fuels(notice_text):
    prices = parse_prices(notice_text)

    assert prices["pb95"].net == Decimal("5.98")
    assert prices["pb95"].gross == Decimal("6.45")
    assert prices["pb98"].net == Decimal("6.77")
    assert prices["pb98"].gross == Decimal("7.31")
    assert prices["on"].net == Decimal("7.53")
    assert prices["on"].gross == Decimal("8.14")


def test_handles_hyphenation_and_superscript(notice_text):
    # w fixture "napędo-\nwego" i "dm³" – typowe artefakty ekstrakcji PDF
    assert "oleju napędowego" in normalize(notice_text)
    assert parse_prices(notice_text)["on"].net == Decimal("7.53")


def test_parses_issue_date(notice_text):
    assert parse_issue_date(notice_text) == date(2026, 11, 2)


def test_issue_date_missing():
    assert parse_issue_date("brak daty") is None


def test_rejects_other_documents():
    with pytest.raises(ParseError, match="nie jest obwieszczeniem"):
        parse_prices("Obwieszczenie w sprawie ogłoszenia jednolitego tekstu ustawy")


def test_rejects_missing_fuel(notice_text):
    text = notice_text.replace("bezołowiowej 98", "bezołowiowej 100")
    with pytest.raises(ParseError, match="pb98"):
        parse_prices(text)


def test_rejects_unrealistic_price(notice_text):
    text = notice_text.replace("6,45 zł za 1 l", "64,50 zł za 1 l")
    with pytest.raises(ParseError):
        parse_prices(text)


def test_rejects_gross_not_above_net(notice_text):
    text = notice_text.replace("6,45 zł za 1 l", "5,90 zł za 1 l")
    with pytest.raises(ParseError, match="VAT"):
        parse_prices(text)
