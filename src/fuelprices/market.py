"""Dane rynkowe do sekcji „Rynek”: ropa Brent, kurs USD/PLN, hurt ORLEN, akcje ORLEN.

Każde źródło jest pobierane osobno. Błąd jednego źródła nie przerywa pozostałych:
zostaje poprzednia wartość z pliku (z flagą ``stale``), a program kończy się sukcesem,
bo dane rynkowe są dodatkiem do cen paliw, nie ich warunkiem.

Źródła:
    - NBP (oficjalne API): kurs średni USD/PLN, tabela A.
    - Yahoo Finance (nieoficjalne): kontrakt Brent ``BZ=F`` i akcje ``PKN.WA``.
    - FRED (Bank Rezerwy Federalnej w St. Louis): Brent spot, zapas gdy Yahoo zawiedzie
      (publikowany z kilkudniowym opóźnieniem).
    - ORLEN (nieoficjalne API strony tool.orlen.pl): hurtowe ceny netto w zł/m³.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import math
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from .sejm_api import MAX_JSON_BYTES, fetch_json, fetch_limited, make_session

log = logging.getLogger("ceny-paliw.market")

NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/usd/last/30/?format=json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
FRED_BRENT_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU"
ORLEN_URL = "https://tool.orlen.pl/api/wholesalefuelprices"

HISTORY_POINTS = 30

# Nazwy produktów w API ORLEN → klucze w pliku. Dopasowanie po fragmencie nazwy.
ORLEN_PRODUCTS = {
    "pb95": ("pb95", "95"),
    "pb98": ("pb98", "98"),
    "on": ("ekodiesel",),
}


class MarketError(ValueError):
    """Odpowiedź źródła nie ma oczekiwanego formatu."""


def _series(points: list[tuple[date, float]], low: float, high: float) -> dict:
    """Seria od najstarszego, ostatnie ``HISTORY_POINTS`` punktów, z bieżącą wartością.

    Odrzuca wartości nieskończone, NaN (niedozwolone w JSON) i spoza zakresu ``low``–``high``.
    """
    valid = [(d, v) for d, v in points if math.isfinite(v) and low <= v <= high]
    points = sorted({d: v for d, v in valid}.items())[-HISTORY_POINTS:]
    if not points:
        raise MarketError("Pusta seria danych")
    last_day, last_value = points[-1]
    previous = points[-2][1] if len(points) > 1 else None
    return {
        "value": round(last_value, 4),
        "previous": round(previous, 4) if previous is not None else None,
        "date": last_day.isoformat(),
        "history": [[d.isoformat(), round(v, 4)] for d, v in points],
    }


# --- parsery (czyste funkcje, testowane bez sieci) ---------------------------------


def parse_nbp(payload: dict) -> dict:
    rates = payload.get("rates")
    if not isinstance(rates, list) or not rates:
        raise MarketError("NBP: brak kursów")
    points = [(date.fromisoformat(r["effectiveDate"]), float(r["mid"])) for r in rates]
    return _series(points, 1.0, 10.0) | {
        "unit": "zł",
        "label": "USD/PLN",
        "source": "NBP, tabela A",
    }


def parse_yahoo(payload: dict) -> list[tuple[date, float]]:
    try:
        result = payload["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MarketError(f"Yahoo: nieoczekiwany format ({exc})") from exc
    points = [
        (datetime.fromtimestamp(ts, UTC).date(), float(close))
        for ts, close in zip(stamps, closes, strict=False)
        if close is not None
    ]
    if not points:
        raise MarketError("Yahoo: brak notowań")
    return points


def parse_fred_csv(text: str) -> list[tuple[date, float]]:
    points = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[1] in ("", "."):
            continue
        try:
            points.append((date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue  # nagłówek
    if not points:
        raise MarketError("FRED: brak notowań")
    return points


def parse_orlen(payload: object) -> dict:
    """Najnowsze hurtowe ceny netto ORLEN, przeliczone z zł/m³ na zł/l."""
    if not isinstance(payload, list):
        raise MarketError("ORLEN: oczekiwano listy produktów")
    result: dict[str, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("productName", "")).lower().replace(" ", "")
        for key, needles in ORLEN_PRODUCTS.items():
            if key in result or not any(n in name for n in needles):
                continue
            # "95" występuje też w nazwach typu "ON ... 95" – Pb95 musi mieć "pb"
            if key in ("pb95", "pb98") and "pb" not in name:
                continue
            try:
                per_m3 = float(item["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not math.isfinite(per_m3) or not 1000 <= per_m3 <= 20000
            ):  # zł/m³ – odrzuć nierealne wartości
                continue
            result[key] = {
                "value": round(per_m3 / 1000, 3),
                "per_m3": per_m3,
                "date": str(item.get("effectiveDate", ""))[:10],
            }
    if not result:
        raise MarketError("ORLEN: nie rozpoznano żadnego produktu")
    return result


# --- pobieranie --------------------------------------------------------------------


def fetch_usdpln(session: requests.Session) -> dict:
    return parse_nbp(fetch_json(session, NBP_URL))


def fetch_yahoo(session: requests.Session, symbol: str) -> list[tuple[date, float]]:
    url = YAHOO_URL.format(symbol=symbol)
    return parse_yahoo(fetch_json(session, url, {"range": "2mo", "interval": "1d"}))


def fetch_brent(session: requests.Session) -> dict:
    try:
        points, source = fetch_yahoo(session, "BZ=F"), "ICE Brent (kontrakt), Yahoo Finance"
    except (requests.RequestException, MarketError, ValueError) as exc:
        log.warning("Brent z Yahoo niedostępny (%s), używam FRED", exc)
        raw = fetch_limited(session, FRED_BRENT_URL, max_bytes=MAX_JSON_BYTES)
        text = raw.decode("utf-8", errors="replace")
        points, source = parse_fred_csv(text), "Brent spot, FRED (opóźnienie kilku dni)"
    series = _series(points, 5.0, 500.0)
    return series | {"unit": "USD/bbl", "label": "Ropa Brent", "source": source}


def fetch_orlen_shares(session: requests.Session) -> dict:
    points = fetch_yahoo(session, "PKN.WA")
    series = _series(points, 1.0, 2000.0)
    return series | {"unit": "zł", "label": "Akcje ORLEN", "source": "GPW, Yahoo Finance"}


def fetch_orlen_wholesale(session: requests.Session) -> dict:
    return {
        "label": "Hurt ORLEN (netto)",
        "unit": "zł/l",
        "source": "ORLEN, hurtowe ceny paliw",
        "products": parse_orlen(fetch_json(session, ORLEN_URL)),
    }


FETCHERS: dict[str, Callable[[requests.Session], dict]] = {
    "brent": fetch_brent,
    "usdpln": fetch_usdpln,
    "orlen_wholesale": fetch_orlen_wholesale,
    "orlen_shares": fetch_orlen_shares,
}


def update(
    previous: dict,
    session: requests.Session,
    fetchers: dict[str, Callable[[requests.Session], dict]] | None = None,
    now: datetime | None = None,
) -> dict:
    """Pobiera wszystkie źródła; przy błędzie zostawia poprzednią wartość jako ``stale``."""
    now = now or datetime.now(UTC)
    old = previous.get("items", {}) if isinstance(previous, dict) else {}
    items: dict[str, dict] = {}
    for key, fetch in (fetchers or FETCHERS).items():
        try:
            items[key] = fetch(session) | {"stale": False}
        except Exception as exc:  # noqa: BLE001 – każde źródło może zawieść inaczej
            log.warning("Źródło %s niedostępne: %s", key, exc)
            if key in old:
                items[key] = old[key] | {"stale": True}

    # Brent w złotówkach – tylko gdy oba składniki są świeże i z tego samego przebiegu
    brent, usd = items.get("brent"), items.get("usdpln")
    if brent and usd and not brent["stale"] and not usd["stale"]:
        brent["value_pln"] = round(brent["value"] * usd["value"], 2)

    return {"schema": 1, "updated_at": now.replace(microsecond=0).isoformat(), "items": items}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aktualizuje data/market.json")
    parser.add_argument("--output", type=Path, default=Path("data/market.json"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    previous = {}
    if args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Uszkodzony %s, zaczynam od zera", args.output)

    session = make_session()
    document = update(previous, session)
    if not document["items"]:
        log.error("Żadne źródło danych rynkowych nie odpowiedziało")
        return 1

    # Nie nadpisuj pliku, jeśli zmienił się wyłącznie znacznik czasu.
    if previous.get("items") == document["items"]:
        log.info("Dane rynkowe bez zmian")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    tmp.replace(args.output)
    for key, item in document["items"].items():
        log.info("%s: %s%s", key, item.get("value", "…"), " (stare)" if item["stale"] else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
