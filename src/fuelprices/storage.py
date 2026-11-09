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


def merge(history: list[Notice], new: list[Notice]) -> list[Notice]:
    """Łączy historię z nowymi obwieszczeniami, bez duplikatów, od najnowszego."""
    by_eli = {n.eli: n for n in history}
    by_eli.update({n.eli: n for n in new})
    ordered = sorted(by_eli.values(), key=lambda n: (n.announced, n.position), reverse=True)
    return ordered[:MAX_HISTORY]


def build_document(history: list[Notice], now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    return {
        "schema": SCHEMA_VERSION,
        "updated_at": now.replace(microsecond=0).isoformat(),
        "source": "Obwieszczenia Ministra Energii w sprawie maksymalnej ceny paliw "
        "ciekłych na stacji paliw, Monitor Polski (api.sejm.gov.pl)",
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
