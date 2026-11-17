"""Źródło pośrednie: otwarte dane serwisu Monitor Paliw (monitorpaliw.pl), licencja CC BY 4.0.

Strony rządowe (monitorpolski.gov.pl, gov.pl) nie odpowiadają serwerom GitHuba, a API ELI
Sejmu ma dobę opóźnienia. Monitor Paliw zbiera te same oficjalne dane (obwieszczenia z ELI
i komunikaty z gov.pl) i publikuje je w JSON, także ceny „tymczasowe” z gov.pl na następny
dzień, zanim obwieszczenie trafi do API ELI.

Licencja: https://monitorpaliw.pl/licencja/ – wymagane uznanie autorstwa
„Monitor Paliw, monitorpaliw.pl” z linkiem (jest w stopce aplikacji).

Format (stan na listopad 2026 r.), rekordy rosnąco po dacie:
    {"generated": "...", "records": [
        {"pos": 1140, "eli": "MP/2026/1140", "published": "2026-11-13",
         "valid_from": "2026-11-14", "valid_to": "2026-11-16",
         "netto": {"pb95": 5.58, "pb98": 6.17, "on": 6.96},
         "brutto": {"pb95": 6.02, "pb98": 6.66, "on": 7.52},
         "sources": [{"type": "govpl", "url": "https://www.gov.pl/..."}, ...]},
        {"pos": null, "eli": null, "provisional": true, "valid_from": "2026-11-17",
         "netto": null, "brutto": {...}, "sources": [{"type": "govpl", ...}]}
    ]}

Autor: Gerard Modlewski
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, timedelta
from decimal import Decimal

import requests

from .models import FUEL_KEYS, FuelPrice, Notice
from .parser import ParseError
from .sejm_api import fetch_json

DATA_URL = "https://monitorpaliw.pl/data/prices.json"
RECENT_RECORDS = 15  # tylko najnowsze; starszą historię uzupełnia API ELI
_ELI = re.compile(r"^MP/\d{4}/\d{1,5}$")
_TRUSTED_SOURCE = re.compile(r"^https://(www\.gov\.pl|monitorpolski\.gov\.pl|api\.sejm\.gov\.pl)/")
_MIN_PRICE, _MAX_PRICE = 2.0, 20.0

log = logging.getLogger("ceny-paliw.monitorpaliw")


def _price(value: object, key: str) -> Decimal:
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise ParseError(f"monitorpaliw: nieprawidłowa cena {key}: {value!r}")
    if not _MIN_PRICE <= value <= _MAX_PRICE:
        raise ParseError(f"monitorpaliw: nierealna cena {key}: {value}")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _source_url(record: dict) -> str:
    """Link do oficjalnego źródła (gov.pl lub Monitor Polski), nigdy do zewnętrznej strony."""
    for source in record.get("sources") or []:
        url = source.get("url") if isinstance(source, dict) else None
        if isinstance(url, str) and _TRUSTED_SOURCE.match(url):
            return url
    return ""


def parse_record(record: dict) -> Notice:
    valid_from = date.fromisoformat(str(record["valid_from"]))
    brutto = record.get("brutto") or {}
    netto = record.get("netto") or {}
    prices: dict[str, FuelPrice] = {}
    for key in FUEL_KEYS:
        gross = _price(brutto.get(key), key)
        net = _price(netto[key], key) if key in netto and netto[key] is not None else None
        if net is not None and gross <= net:
            raise ParseError(f"monitorpaliw: cena z VAT nie jest wyższa od netto ({key})")
        prices[key] = FuelPrice(gross=gross, net=net)

    eli = record.get("eli")
    if isinstance(eli, str) and _ELI.match(eli) and not record.get("provisional"):
        notice_eli, position = eli, int(record.get("pos") or eli.rsplit("/", 1)[1])
    else:
        notice_eli, position = f"GOV/{valid_from.isoformat()}", 0

    return Notice(
        eli=notice_eli,
        position=position,
        announced=valid_from - timedelta(days=1),
        prices=prices,
        source_url=_source_url(record),
    )


def parse_document(payload: object) -> list[Notice]:
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ParseError("monitorpaliw: nieoczekiwany format pliku")
    records = [r for r in payload["records"] if isinstance(r, dict) and r.get("valid_from")]
    records.sort(key=lambda r: str(r["valid_from"]))
    return [parse_record(r) for r in records[-RECENT_RECORDS:]]


def fetch_new(session: requests.Session, history: list[Notice]) -> list[Notice]:
    """Wpisy na dni, których brakuje w historii, albo oficjalne w miejsce tymczasowych."""
    by_day = {n.valid_from: n for n in history}
    result = []
    for notice in parse_document(fetch_json(session, DATA_URL)):
        current = by_day.get(notice.valid_from)
        if current is None or (notice.is_official and not current.is_official):
            result.append(notice)
    return result
