"""Wyciąganie cen z tekstu obwieszczenia.

Struktura obwieszczenia (stan na 2026 r.):

    1) dla benzyny silnikowej bezołowiowej 95 (CN ...):
       a) wynosi 5,98 zł za 1 dm3,
       b) powiększona o podatek od towarów i usług wynosi 6,45 zł za 1 l;
    2) dla benzyny silnikowej bezołowiowej 98 (CN ...): ...
    3) dla oleju napędowego (CN ...): ...

Cenę netto rozpoznajemy po jednostce "dm3", cenę z VAT po jednostce "l".
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .models import FUEL_KEYS, FuelPrice


class ParseError(ValueError):
    """Tekst obwieszczenia nie pasuje do oczekiwanego formatu."""


_FUEL_HEADERS = {
    "pb95": r"dla\s+benzyny\s+silnikowej\s+bezołowiowej\s+95\b",
    "pb98": r"dla\s+benzyny\s+silnikowej\s+bezołowiowej\s+98\b",
    "on": r"dla\s+oleju\s+napędowego\b",
}

_PRICE = r"(\d{1,2},\d{2})"
_NET = re.compile(rf"wynosi\s+{_PRICE}\s*zł\s+za\s+1\s*dm\s*3?", re.IGNORECASE)
_GROSS = re.compile(rf"wynosi\s+{_PRICE}\s*zł\s+za\s+1\s*l\b", re.IGNORECASE)

_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "października": 10, "listopada": 11, "grudnia": 12,
}  # fmt: skip
_DATE = re.compile(r"z\s+dnia\s+(\d{1,2})\s+([a-ząćęłńóśźż]+)\s+(\d{4})\s*r", re.IGNORECASE)

# Rozsądne granice ceny (zł/l) – zabezpieczenie przed błędnym odczytem PDF.
_MIN_PRICE = Decimal("2.00")
_MAX_PRICE = Decimal("20.00")


def normalize(text: str) -> str:
    """Łączy przeniesienia wyrazów i ujednolica białe znaki z ekstrakcji PDF."""
    text = text.replace(" ", " ").replace("³", "3")  # nbsp, "dm³"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # dzielenie wyrazów na końcu linii
    return re.sub(r"\s+", " ", text).strip()


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "."))


def _split_sections(text: str) -> dict[str, str]:
    """Dzieli tekst na fragmenty dotyczące poszczególnych paliw."""
    starts: list[tuple[int, str]] = []
    for key, pattern in _FUEL_HEADERS.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            raise ParseError(f"Nie znaleziono sekcji paliwa: {key}")
        starts.append((match.start(), key))
    starts.sort()

    sections: dict[str, str] = {}
    for i, (start, key) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        sections[key] = text[start:end]
    return sections


def _parse_section(key: str, section: str) -> FuelPrice:
    net = _NET.search(section)
    gross = _GROSS.search(section)
    if net is None or gross is None:
        raise ParseError(f"Brak ceny netto lub brutto dla paliwa: {key}")

    price = FuelPrice(net=_to_decimal(net.group(1)), gross=_to_decimal(gross.group(1)))
    for value in (price.net, price.gross):
        if not _MIN_PRICE <= value <= _MAX_PRICE:
            raise ParseError(f"Nierealna cena {value} zł dla paliwa: {key}")
    if price.gross <= price.net:
        raise ParseError(f"Cena z VAT nie jest wyższa od ceny netto dla paliwa: {key}")
    return price


def parse_prices(raw_text: str) -> dict[str, FuelPrice]:
    """Zwraca ceny wszystkich trzech paliw albo rzuca ParseError."""
    text = normalize(raw_text)
    if not re.search(r"maksymaln\w*\s+cen\w*\s+paliw", text, re.IGNORECASE):
        raise ParseError("Tekst nie jest obwieszczeniem w sprawie maksymalnej ceny paliw")
    sections = _split_sections(text)
    return {key: _parse_section(key, sections[key]) for key in FUEL_KEYS}


def parse_issue_date(raw_text: str) -> date | None:
    """Data obwieszczenia ("z dnia 2 listopada 2026 r."), jeśli występuje w tekście."""
    match = _DATE.search(normalize(raw_text))
    if match is None:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    return date(int(year), month, int(day))
