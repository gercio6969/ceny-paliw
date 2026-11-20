"""Punkt wejścia: pobiera nowe obwieszczenia i aktualizuje data/prices.json.

Kod wyjścia:
    0 – sukces (także gdy nie było nic nowego),
    1 – błąd pobierania lub parsowania (workflow w GitHub Actions się nie powiedzie,
        więc GitHub wyśle powiadomienie e-mail).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import gov_pl, monitor_paliw, monitor_polski, sejm_api, storage
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
    title: str = ""

    @property
    def is_amendment(self) -> bool:
        return "zmieniając" in self.title.lower()


def _from_monitor(session, year: int, history: list[Notice], refs: list) -> list[Candidate]:
    """Nowe obwieszczenia z monitorpolski.gov.pl (dostępne w dniu ogłoszenia)."""
    positions = [n.position for n in history if n.eli.startswith(f"MP/{year}/")]
    positions += [r.position for r in refs if r.year == year]
    last_known = max(positions, default=0)
    found = monitor_polski.find_new_fuel_notices(session, year, last_known)
    return [Candidate(p.eli, p.year, p.position, p.announced, p.pdf_url, p.title) for p in found]


def _from_eli(refs: list, backfill: int) -> list[Candidate]:
    return [
        Candidate(r.eli, r.year, r.position, r.announced, r.pdf_url, r.title)
        for r in refs[:backfill]
    ]


def _summary(lines: list[str]) -> None:
    """Podsumowanie przebiegu widoczne publicznie na stronie runu w GitHub Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def run(output: Path, backfill: int, year: int) -> int:
    history = storage.load_history(output)
    known = {n.eli for n in history}
    status: dict[str, str] = {}

    # 1. Monitor Polski (RCL): obwieszczenia z dzisiaj, czyli ceny na jutro, z cenami netto.
    #    Serwer bywa nieosiągalny z GitHuba, więc jedna krótka próba, bez ponawiania.
    monitor_ok = True
    fresh: list[Candidate] = []
    try:
        fresh = _from_monitor(sejm_api.make_session(retries=0), year, history, [])
        status["Monitor Polski"] = f"OK, nowe: {', '.join(c.eli for c in fresh) or 'brak'}"
    except Exception as exc:  # noqa: BLE001 – drugie źródło może nadal zadziałać
        monitor_ok = False
        status["Monitor Polski"] = f"BŁĄD: {exc}"
        log.warning("Monitor Polski niedostępny: %s", exc)

    # 2. Komunikaty Ministerstwa Energii na gov.pl: ceny na jutro (tylko z VAT), osiągalne
    #    z GitHuba. Zastępowane przez obwieszczenie z ELI, gdy to się pojawi.
    gov_ok = True
    gov_new: list[Notice] = []
    try:
        known_days = {n.valid_from for n in history}
        gov_new = gov_pl.fetch_new(sejm_api.make_session(retries=0), known_days)
        found = ", ".join(n.valid_from.isoformat() for n in gov_new) or "brak"
        status["gov.pl"] = f"OK, nowe dni: {found}"
    except Exception as exc:  # noqa: BLE001
        gov_ok = False
        status["gov.pl"] = f"BŁĄD: {exc}"
        log.warning("gov.pl niedostępne: %s", exc)

    # 3. Monitor Paliw (monitorpaliw.pl, CC BY 4.0): te same oficjalne dane w JSON, osiągalne
    #    z GitHuba – w praktyce główne źródło cen na jutro, gdy strony rządowe blokują GitHuba.
    mp_ok = True
    mp_new: list[Notice] = []
    try:
        mp_new = monitor_paliw.fetch_new(sejm_api.make_session(retries=2, backoff=1), history)
        found = ", ".join(f"{n.valid_from.isoformat()} ({n.eli})" for n in mp_new) or "brak"
        status["monitorpaliw.pl"] = f"OK, nowe: {found}"
    except Exception as exc:  # noqa: BLE001
        mp_ok = False
        status["monitorpaliw.pl"] = f"BŁĄD: {exc}"
        log.warning("monitorpaliw.pl niedostępne: %s", exc)

    # 4. API ELI Sejmu: pełna historia, ale z opóźnieniem jednego dnia roboczego.
    refs: list = []
    eli_ok = True
    try:
        session = sejm_api.make_session()
        refs = sejm_api.find_notices(session, year)
        if len(refs) < backfill:  # przełom roku – dociągnij koniec poprzedniego
            refs += sejm_api.find_notices(session, year - 1)
        status["API ELI"] = f"OK, najnowsze: {refs[0].eli if refs else 'brak'}"
    except Exception as exc:  # noqa: BLE001
        eli_ok = False
        status["API ELI"] = f"BŁĄD: {exc}"
        log.warning("API ELI niedostępne: %s", exc)

    _summary(["### Źródła obwieszczeń", ""] + [f"- **{k}**: {v}" for k, v in status.items()])
    for name, value in status.items():
        log.info("%s: %s", name, value)

    if not eli_ok and not monitor_ok and not gov_ok and not mp_ok:
        log.error("Żadne źródło obwieszczeń nie odpowiada")
        return 1

    session = sejm_api.make_session()
    candidates = {c.eli: c for c in _from_eli(refs, backfill)}
    candidates.update({c.eli: c for c in fresh})  # dla tych samych aktów wolimy plik z RCL

    new: list[Notice] = []
    failed: list[Candidate] = []
    for cand in sorted(candidates.values(), key=lambda c: (c.year, c.position), reverse=True):
        if cand.eli in known:
            continue
        known.add(cand.eli)
        log.info("Pobieram %s (%s)", cand.eli, cand.pdf_url)
        try:
            text = sejm_api.download_pdf_text(session, cand.pdf_url)
            prices = parse_prices(text)
            announced = cand.announced or parse_issue_date(text)
            if announced is None:
                raise ParseError("brak daty ogłoszenia")
        except Exception as exc:  # noqa: BLE001 – jeden nietypowy akt nie może zatrzymać reszty
            kind = "obwieszczenie zmieniające" if cand.is_amendment else "obwieszczenie"
            log.warning("Nie udało się odczytać %s (%s): %s", cand.eli, kind, exc)
            failed.append(cand)
            continue
        new.append(Notice(cand.eli, cand.position, announced, prices, source_url=cand.pdf_url))

    # Wpisy z gov.pl i Monitora Paliw; który wpis zostaje na dany dzień, decyduje
    # storage.merge (oficjalne przed gov.pl, korekta przed pierwotnym obwieszczeniem).
    new += [*gov_new, *mp_new]
    merged = storage.merge(history, new)

    # Akt, którego nie udało się odczytać, jest problemem tylko wtedy, gdy żadne źródło
    # nie dało dla niego danych (ten sam numer ELI albo późniejsza korekta na ten dzień).
    uncovered = [
        c for c in failed
        if not any(
            n.eli == c.eli
            or (n.is_official and n.position >= c.position and c.announced is not None
                and n.valid_from == c.announced + timedelta(days=1))
            for n in merged
        )
    ]  # fmt: skip
    if failed:
        _summary(
            ["", "### Nieodczytane akty", ""]
            + [
                f"- {c.eli}: {'pokryty innym źródłem' if c not in uncovered else 'BRAK DANYCH'}"
                f" – {c.title}"
                for c in failed
            ]
        )
    for cand in uncovered:
        print(f"::error::Nie udało się odczytać {cand.eli} i żadne źródło go nie zastąpiło")

    new = [n for n in new if n in merged and n not in history]

    if not new:
        newest = history[0].eli if history else "brak"
        log.info("Brak nowych obwieszczeń, najnowsze: %s", newest)
        return 1 if uncovered else 0

    storage.save(output, merged)
    for notice in new:
        p = notice.prices
        log.info(
            "%s (od %s): Pb95 %s, Pb98 %s, ON %s zł/l",
            notice.eli, notice.valid_from, p["pb95"].gross, p["pb98"].gross, p["on"].gross,
        )  # fmt: skip
    return 1 if uncovered else 0


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
