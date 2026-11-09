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
from datetime import date
from pathlib import Path

from . import sejm_api, storage
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


def run(output: Path, backfill: int, year: int) -> int:
    history = storage.load_history(output)
    known = {n.eli for n in history}
    session = sejm_api.make_session()

    refs = sejm_api.find_notices(session, year)
    if len(refs) < backfill:  # przełom roku – dociągnij koniec poprzedniego
        refs += sejm_api.find_notices(session, year - 1)
    if not refs:
        log.error("API nie zwróciło żadnych obwieszczeń o cenach paliw")
        return 1

    new: list[Notice] = []
    for ref in refs[:backfill]:
        if ref.eli in known:
            continue
        known.add(ref.eli)
        log.info("Pobieram %s (%s)", ref.eli, ref.pdf_url)
        text = sejm_api.download_text(session, ref)
        try:
            prices = parse_prices(text)
        except ParseError as exc:
            log.error("Nie udało się odczytać %s: %s", ref.eli, exc)
            return 1
        announced = ref.announced or parse_issue_date(text)
        if announced is None:
            log.error("Brak daty ogłoszenia dla %s", ref.eli)
            return 1
        new.append(
            Notice(ref.eli, ref.position, announced, prices, source_url=ref.pdf_url),
        )

    if not new:
        log.info("Brak nowych obwieszczeń, najnowsze: %s", refs[0].eli)
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
