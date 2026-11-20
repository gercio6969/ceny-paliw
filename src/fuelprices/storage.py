"""Odczyt i zapis pliku data/prices.json konsumowanego przez aplikację."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import Notice

SCHEMA_VERSION = 1
MAX_HISTORY = 400  # ok. półtora roku dni roboczych


def load_history(path: Path) -> list[Notice]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Notice.from_dict(item) for item in data.get("history", [])]


def rank(notice: Notice) -> tuple[bool, int]:
    """Pierwszeństwo wpisu na dany dzień: oficjalne przed gov.pl, korekta przed pierwotnym."""
    return (notice.is_official, notice.position)


def merge(history: list[Notice], new: list[Notice]) -> list[Notice]:
    """Łączy historię z nowymi obwieszczeniami, od najnowszego.

    Na jeden dzień obowiązywania przypada jeden wpis, wybierany według rangi:
      - obwieszczenie z Monitora Polskiego wygrywa z komunikatem z gov.pl (ma ceny netto
        i numer pozycji), nigdy odwrotnie;
      - z dwóch obwieszczeń na ten sam dzień wygrywa późniejsza pozycja – to obwieszczenie
        zmieniające (korekta), np. poz. 1154 korygująca poz. 1150 z 18.11.2026;
      - przy równej randze nowszy wpis zastępuje starszy (ten sam akt pobrany ponownie).
    """
    by_day: dict = {}
    for notice in [*history, *new]:
        current = by_day.get(notice.valid_from)
        if current is None or rank(notice) >= rank(current):
            by_day[notice.valid_from] = notice
    ordered = sorted(by_day.values(), key=lambda n: (n.valid_from, n.position), reverse=True)
    return ordered[:MAX_HISTORY]


def build_document(history: list[Notice], now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    return {
        "schema": SCHEMA_VERSION,
        "updated_at": now.replace(microsecond=0).isoformat(),
        "source": "Obwieszczenia Ministra Energii w sprawie maksymalnej ceny paliw "
        "ciekłych na stacji paliw (Monitor Polski, api.sejm.gov.pl) oraz komunikaty "
        "Ministerstwa Energii (gov.pl/web/energia)",
        "latest": history[0].to_dict() if history else None,
        "history": [n.to_dict() for n in history],
    }


def save(path: Path, history: list[Notice], now: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = build_document(history, now)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    tmp.replace(path)  # zapis atomowy
