from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fuelprices import gov_pl
from fuelprices.parser import ParseError

FIXTURES = Path(__file__).parent / "fixtures"


def _fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_list_real_snapshot():
    articles = gov_pl.parse_list(_fx("gov_pl_lista.html"))
    assert [a.valid_from for a in articles] == [
        date(2026, 11, 17),
        date(2026, 11, 14),
        date(2026, 11, 13),
    ]
    assert articles[0].url.startswith("https://www.gov.pl/web/energia/maksymalna-cena")


def test_parse_article_single_day():
    prices = gov_pl.parse_article(_fx("gov_pl_17_listopada.html"), date(2026, 11, 17))
    assert prices["pb95"].gross == Decimal("6.02")
    assert prices["pb98"].gross == Decimal("6.68")
    assert prices["on"].gross == Decimal("7.64")
    assert prices["pb95"].net is None


def test_parse_article_weekend_range():
    prices = gov_pl.parse_article(_fx("gov_pl_14_16_listopada.html"), date(2026, 11, 14))
    assert prices["on"].gross == Decimal("7.52")


def test_parse_article_rejects_wrong_day():
    with pytest.raises(ParseError, match="dotyczy"):
        gov_pl.parse_article(_fx("gov_pl_17_listopada.html"), date(2026, 11, 18))


def test_parse_article_rejects_missing_price():
    page = _fx("gov_pl_17_listopada.html").replace("olej napędowy", "gaz LPG")
    with pytest.raises(ParseError, match="on"):
        gov_pl.parse_article(page, date(2026, 11, 17))


def test_fetch_new_skips_known_days(monkeypatch):
    pages = {
        gov_pl.LIST_URL: _fx("gov_pl_lista.html"),
        gov_pl.BASE_URL
        + "/web/energia/maksymalna-cena-detaliczna-paliw-obowiazujaca-17-listopada-2026-r": _fx(
            "gov_pl_17_listopada.html"
        ),
    }
    monkeypatch.setattr(gov_pl, "_get", lambda session, url: pages[url])

    notices = gov_pl.fetch_new(None, {date(2026, 11, 14), date(2026, 11, 13)})

    assert len(notices) == 1
    notice = notices[0]
    assert notice.eli == "GOV/2026-11-17"
    assert notice.valid_from == date(2026, 11, 17)
    assert not notice.is_official
