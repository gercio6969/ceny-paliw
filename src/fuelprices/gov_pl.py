"""Szybkie źródło: komunikaty Ministerstwa Energii na gov.pl.

Ministerstwo publikuje codziennie wiadomość „Maksymalna cena detaliczna paliw obowiązująca
17 listopada 2026 r.” (albo „… w dniach 14-16 listopada 2026 r.” przed weekendem) w dniu
ogłoszenia obwieszczenia, czyli z ceną na jutro. W odróżnieniu od monitorpolski.gov.pl
strona jest osiągalna z serwerów GitHuba, a API ELI Sejmu ma dobę opóźnienia.

Komunikat podaje tylko ceny z VAT. Gdy obwieszczenie trafi do API ELI, zastępuje ten
wpis (z cenami netto i numerem pozycji) – patrz ``storage.merge``.

Treść wiadomości (stan na 2026 r.):
    <p>benzyna 95 &ndash; 6,02 zł/l</p>
    <p>benzyna 98 &ndash; 6,66 zł/l</p>
    <p>olej napędowy &ndash; 7,52 zł/l</p>

Autor: Gerard Modlewski
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import requests

from .models import FuelPrice, Notice
from .parser import ParseError
from .sejm_api import MAX_JSON_BYTES, fetch_limited

BASE_URL = "https://www.gov.pl"
LIST_URL = f"{BASE_URL}/web/energia/wiadomosci"
TIMEOUT = 20
MAX_ARTICLES = 6

_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}  # fmt: skip

_LINK = re.compile(r'href="(/web/energia/maksymalna-cena-detaliczna-paliw[a-z0-9-]*)"')
# „… które będą obowiązywać 17 listopada 2026 r.” albo „… w dniach 14-16 listopada 2026 r.”
_VALIDITY = re.compile(
    r"obowiąz\w*\s+(?:w\s+dniach\s+)?(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s+"
    r"([a-ząćęłńóśźż]+)\s+(\d{4})",
    re.IGNORECASE,
)
# Początek właściwej treści wiadomości – ceny i datę bierzemy tylko z tego fragmentu,
# żeby nie złapać wartości z innych wiadomości wyświetlanych na tej samej stronie.
_ANCHOR = re.compile(r"Minister\s+Energii\s+podał\s+maksymaln", re.IGNORECASE)
_WINDOW = 700
_PRICES = {
    "pb95": re.compile(r"benzyna\s+95\s*[-–:]\s*(\d{1,2},\d{2})\s*zł\s*/\s*l", re.IGNORECASE),
    "pb98": re.compile(r"benzyna\s+98\s*[-–:]\s*(\d{1,2},\d{2})\s*zł\s*/\s*l", re.IGNORECASE),
    "on": re.compile(r"olej\s+napędowy\s*[-–:]\s*(\d{1,2},\d{2})\s*zł\s*/\s*l", re.IGNORECASE),
}
_MIN_PRICE, _MAX_PRICE = Decimal("2.00"), Decimal("20.00")

log = logging.getLogger("ceny-paliw.gov")


@dataclass(frozen=True)
class Article:
    path: str
    valid_from: date

    @property
    def url(self) -> str:
        return BASE_URL + self.path


def _text(raw: str) -> str:
    plain = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", plain.replace(" ", " ")).strip()


def parse_validity(text: str) -> date | None:
    """Pierwszy dzień obowiązywania z tekstu („obowiązywać 17 listopada 2026”)."""
    match = _VALIDITY.search(text)
    if match is None:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def _validity_from_path(path: str) -> date | None:
    # /web/energia/maksymalna-cena-detaliczna-paliw-obowiazujaca-w-dniach-14-16-listopada-2026-r
    slug = path.rsplit("/", 1)[-1]
    match = re.search(r"obowiazujaca-(?:w-dniach-)?(\d{1,2})(?:-\d{1,2})?-([a-z]+)-(\d{4})", slug)
    if match is None:
        return None
    day, month_ascii, year = match.groups()
    ascii_months = {
        k.translate(str.maketrans("ąćęłńóśźż", "acelnoszz")): v for k, v in _MONTHS.items()
    }
    month = ascii_months.get(month_ascii)
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def parse_list(page: str) -> list[Article]:
    """Wiadomości o cenach paliw z listy, od najnowszej, bez duplikatów."""
    seen: dict[str, Article] = {}
    for path in _LINK.findall(page):
        if path in seen:
            continue
        valid_from = _validity_from_path(path)
        if valid_from is not None:
            seen[path] = Article(path, valid_from)
    return sorted(seen.values(), key=lambda a: a.valid_from, reverse=True)


def parse_article(page: str, valid_from: date) -> dict[str, FuelPrice]:
    """Ceny z treści wiadomości. Sprawdza, że dotyczy oczekiwanego dnia."""
    full = _text(page)
    anchor = _ANCHOR.search(full)
    if anchor is None:
        raise ParseError("gov.pl: nie znaleziono treści komunikatu")
    text = full[anchor.start() : anchor.start() + _WINDOW]
    stated = parse_validity(text)
    if stated != valid_from:
        raise ParseError(f"gov.pl: wiadomość dotyczy {stated}, oczekiwano {valid_from}")
    prices: dict[str, FuelPrice] = {}
    for key, pattern in _PRICES.items():
        match = pattern.search(text)
        if match is None:
            raise ParseError(f"gov.pl: brak ceny {key}")
        value = Decimal(match.group(1).replace(",", "."))
        if not _MIN_PRICE <= value <= _MAX_PRICE:
            raise ParseError(f"gov.pl: nierealna cena {value} zł dla {key}")
        prices[key] = FuelPrice(gross=value)
    return prices


def _get(session: requests.Session, url: str) -> str:
    raw = fetch_limited(
        session, url, max_bytes=MAX_JSON_BYTES, headers={"Accept": "text/html"}, timeout=TIMEOUT
    )
    return raw.decode("utf-8", errors="replace")


def fetch_new(session: requests.Session, known_days: set[date]) -> list[Notice]:
    """Komunikaty o cenach na dni, których jeszcze nie ma w historii."""
    notices: list[Notice] = []
    for article in parse_list(_get(session, LIST_URL))[:MAX_ARTICLES]:
        if article.valid_from in known_days:
            continue
        prices = parse_article(_get(session, article.url), article.valid_from)
        log.info("gov.pl: ceny od %s z %s", article.valid_from, article.url)
        notices.append(
            Notice(
                eli=f"GOV/{article.valid_from.isoformat()}",
                position=0,
                announced=article.valid_from - timedelta(days=1),
                prices=prices,
                source_url=article.url,
            )
        )
    return notices
