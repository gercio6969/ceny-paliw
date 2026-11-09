"""Punkt wejścia: pobiera nowe obwieszczenia i aktualizuje data/prices.json.

Kod wyjścia:
    0 – sukces (także gdy nie było nic nowego),
    1 – błąd pobierania lub parsowania (workflow w GitHub Actions się nie powiedzie,
        więc GitHub wyśle powiadomienie e-mail).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import monitor_polski, sejm_api, storage
from .models import Notice
from .parser import ParseError, parse_issue_date, parse_prices

log = logging.getLogger("ceny-paliw")


def _int_range(low: int, high: int):
    def check(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"wartość musi być w zakresie {low}–{high}")
        return number

    return check


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/prices.json"))
    parser.add_argument(
        "--backfill",
        type=_int_range(1, 400),
        default=10,
        help="ile najnowszych obwieszczeń sprawdzić pod kątem braków w historii (domyślnie 10)",
    )
    parser.add_argument("--year", type=_int_range(2000, 2100), default=date.today().year)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


@dataclass(frozen=True)
class Candidate:
    """Obwieszczenie do pobrania – z dowolnego źródła, identyfikowane numerem ELI."""

    eli: str
    year: int
    position: int
    announced: date | None
    pdf_url: str


def _from_monitor(session, year: int, history: list[Notice], refs: list) -> list[Candidate]:
    """Nowe obwieszczenia z monitorpolski.gov.pl (dostępne w dniu ogłoszenia)."""
    positions = [n.position for n in history if n.eli.startswith(f"MP/{year}/")]
    positions += [r.position for r in refs if r.year == year]
    last_known = max(positions, default=0)
    found = monitor_polski.find_new_fuel_notices(session, year, last_known)
    return [Candidate(p.eli, p.year, p.position, p.announced, p.pdf_url) for p in found]


def _from_eli(refs: list, backfill: int) -> list[Candidate]:
    return [Candidate(r.eli, r.year, r.position, r.announced, r.pdf_url) for r in refs[:backfill]]


def run(output: Path, backfill: int, year: int) -> int:
    history = storage.load_history(output)
    known = {n.eli for n in history}
    session = sejm_api.make_session()

    # 1. API ELI Sejmu: pełna historia, ale z opóźnieniem jednego dnia roboczego.
    refs: list = []
    eli_ok = True
    try:
        refs = sejm_api.find_notices(session, year)
        if len(refs) < backfill:  # przełom roku – dociągnij koniec poprzedniego
            refs += sejm_api.find_notices(session, year - 1)
    except Exception as exc:  # noqa: BLE001 – drugie źródło może nadal zadziałać
        eli_ok = False
        log.warning("API ELI niedostępne: %s", exc)

    # 2. Monitor Polski (RCL): obwieszczenia z dzisiaj, czyli ceny na jutro.
    monitor_ok = True
    fresh: list[Candidate] = []
    try:
        fresh = _from_monitor(session, year, history, refs)
    except Exception as exc:  # noqa: BLE001
        monitor_ok = False
        log.warning("Monitor Polski niedostępny: %s", exc)

    if not eli_ok and not monitor_ok:
        log.error("Żadne źródło obwieszczeń nie odpowiada")
        return 1

    candidates = {c.eli: c for c in _from_eli(refs, backfill)}
    candidates.update({c.eli: c for c in fresh})  # dla tych samych aktów wolimy plik z RCL

    new: list[Notice] = []
    for cand in sorted(candidates.values(), key=lambda c: (c.year, c.position), reverse=True):
        if cand.eli in known:
            continue
        known.add(cand.eli)
        log.info("Pobieram %s (%s)", cand.eli, cand.pdf_url)
        text = sejm_api.download_pdf_text(session, cand.pdf_url)
        try:
            prices = parse_prices(text)
        except ParseError as exc:
            log.error("Nie udało się odczytać %s: %s", cand.eli, exc)
            return 1
        announced = cand.announced or parse_issue_date(text)
        if announced is None:
            log.error("Brak daty ogłoszenia dla %s", cand.eli)
            return 1
        new.append(Notice(cand.eli, cand.position, announced, prices, source_url=cand.pdf_url))

    if not new:
        newest = history[0].eli if history else "brak"
        log.info("Brak nowych obwieszczeń, najnowsze: %s", newest)
        return 0

    storage.save(output, storage.merge(history, new))
    for notice in new:
        p = notice.prices
        log.info(
            "%s (od %s): Pb95 %s, Pb98 %s, ON %s zł/l",
            notice.eli, notice.valid_from, p["pb95"].gross, p["pb98"].gross, p["on"].gross,
        )  # fmt: skip
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    try:
        return run(args.output, args.backfill, args.year)
    except Exception:  # noqa: BLE001 – ostatnia linia obrony, log z tracebackiem
        log.exception("Aktualizacja cen nie powiodła się")
        return 1


if __name__ == "__main__":
    sys.exit(main())
