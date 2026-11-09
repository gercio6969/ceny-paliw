"""Szybkie źródło: strona Monitora Polskiego prowadzona przez Rządowe Centrum Legislacji.

API ELI Sejmu dodaje obwieszczenia dopiero następnego dnia roboczego (np. piątkowe
w poniedziałek rano), więc nie zdąży z ceną „na jutro”. Na monitorpolski.gov.pl akt jest
widoczny w dniu ogłoszenia. Pozycje w roczniku są numerowane kolejno, więc szukamy
nowych obwieszczeń, sprawdzając kolejne numery od ostatniego znanego.

Strona pozycji (stan na 2026 r.):
    <h2 class="one-item-heading">Obwieszczenie Ministra Energii z dnia … w sprawie
        maksymalnej ceny paliw ciekłych na stacji paliw</h2>
    … Data ogłoszenia: … <span> 2026-11-09 </span>
Nieistniejąca pozycja zwraca HTTP 200 ze stroną bez nagłówka ``one-item-heading``.

Autor: Gerard Modlewski
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date

import requests

from .sejm_api import MAX_JSON_BYTES, fetch_limited

BASE_URL = "https://monitorpolski.gov.pl"
MAX_PROBES = 120  # ok. 10–15 pozycji dziennie, z zapasem na kilka dni przerwy
STOP_AFTER_MISSING = 3  # tyle kolejnych nieistniejących pozycji kończy szukanie

_HEADING = re.compile(r'<h2[^>]*class="[^"]*one-item-heading[^"]*"[^>]*>(.*?)</h2>', re.S)
_ANNOUNCED = re.compile(r"Data og[łl]oszenia:.*?(\d{4}-\d{2}-\d{2})", re.S)
_FUEL_TITLE = re.compile(r"maksymaln\w*\s+cen\w*\s+paliw", re.IGNORECASE)

log = logging.getLogger("ceny-paliw.monitor")


@dataclass(frozen=True)
class Position:
    year: int
    position: int
    title: str
    announced: date | None

    @property
    def eli(self) -> str:
        return f"MP/{self.year}/{self.position}"

    @property
    def is_fuel_notice(self) -> bool:
        return bool(_FUEL_TITLE.search(self.title))

    @property
    def pdf_url(self) -> str:
        return pdf_url(self.year, self.position)


def pdf_url(year: int, position: int) -> str:
    # Bezpośredni adres pliku; wariant /MP/rok/poz/… przekierowuje na ten sam plik.
    return f"{BASE_URL}/M{year}{position:07d}01.pdf"


def page_url(year: int, position: int) -> str:
    return f"{BASE_URL}/MP/{year}/{position}"


def parse_position_page(text: str, year: int, position: int) -> Position | None:
    """Zwraca dane pozycji albo ``None``, gdy pozycja jeszcze nie istnieje."""
    heading = _HEADING.search(text)
    if heading is None:
        return None
    title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", heading.group(1)))).strip()
    announced = None
    if match := _ANNOUNCED.search(text):
        try:
            announced = date.fromisoformat(match.group(1))
        except ValueError:
            announced = None
    return Position(year, position, title, announced)


def fetch_position(session: requests.Session, year: int, position: int) -> Position | None:
    raw = fetch_limited(
        session, page_url(year, position), max_bytes=MAX_JSON_BYTES, headers={"Accept": "text/html"}
    )
    return parse_position_page(raw.decode("utf-8", errors="replace"), year, position)


def find_new_fuel_notices(
    session: requests.Session, year: int, last_known_position: int
) -> list[Position]:
    """Obwieszczenia o cenach paliw opublikowane po ``last_known_position``, od najnowszego."""
    found: list[Position] = []
    missing = 0
    position = last_known_position
    for _ in range(MAX_PROBES):
        position += 1
        item = fetch_position(session, year, position)
        if item is None:
            missing += 1
            if missing >= STOP_AFTER_MISSING:
                break
            continue
        missing = 0
        if item.is_fuel_notice:
            log.info("Monitor Polski: %s – %s", item.eli, item.announced)
            found.append(item)
    else:
        log.warning("Osiągnięto limit %s sprawdzonych pozycji", MAX_PROBES)
    return sorted(found, key=lambda p: p.position, reverse=True)
