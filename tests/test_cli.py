import json
from datetime import date
from decimal import Decimal

import pytest

from fuelprices import cli, gov_pl, monitor_polski, sejm_api
from fuelprices.models import FuelPrice, Notice


def _ref(pos: int, day: int) -> sejm_api.ActRef:
    return sejm_api.ActRef(
        f"MP/2026/{pos}", 2026, pos, "maksymalnej ceny paliw", date(2026, 11, day)
    )


def _mp(pos: int, day: int) -> monitor_polski.Position:
    title = "Obwieszczenie Ministra Energii w sprawie maksymalnej ceny paliw ciekłych"
    return monitor_polski.Position(2026, pos, title, date(2026, 11, day))


@pytest.fixture
def sources(monkeypatch, notice_text):
    """Atrapy obu źródeł; testy ustawiają, co każde z nich „zwraca”."""
    state = {"eli": [], "monitor": [], "downloaded": [], "monitor_calls": []}
    monkeypatch.setattr(sejm_api, "make_session", lambda **kwargs: None)

    def find_eli(session, year):
        if isinstance(state["eli"], Exception):
            raise state["eli"]
        return [r for r in state["eli"] if r.year == year]

    def find_monitor(session, year, last_known):
        state["monitor_calls"].append(last_known)
        if isinstance(state["monitor"], Exception):
            raise state["monitor"]
        return [p for p in state["monitor"] if p.position > last_known]

    def download(session, url):
        state["downloaded"].append(url)
        return state.get("text", notice_text)

    monkeypatch.setattr(sejm_api, "find_notices", find_eli)
    monkeypatch.setattr(monitor_polski, "find_new_fuel_notices", find_monitor)

    def fetch_gov(session, known_days):
        if isinstance(state.get("gov"), Exception):
            raise state["gov"]
        return [n for n in state.get("gov", []) if n.valid_from not in known_days]

    monkeypatch.setattr(sejm_api, "download_pdf_text", download)
    monkeypatch.setattr(gov_pl, "fetch_new", fetch_gov)
    return state


def _history(output):
    return [n["eli"] for n in json.loads(output.read_text(encoding="utf-8"))["history"]]


def test_adds_new_notices_and_skips_known(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1066, 3), _ref(1065, 2)]

    assert cli.run(output, backfill=10, year=2026) == 0
    assert cli.run(output, backfill=10, year=2026) == 0  # drugi przebieg: nic nowego

    assert _history(output) == ["MP/2026/1066", "MP/2026/1065"]
    assert len(sources["downloaded"]) == 2


def test_todays_notice_comes_from_monitor_polski(tmp_path, sources):
    """ELI ma tylko piątek, Monitor Polski już dzisiejsze obwieszczenie (cena na jutro)."""
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1101, 6)]
    sources["monitor"] = [_mp(1108, 9)]

    assert cli.run(output, backfill=10, year=2026) == 0

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["latest"]["eli"] == "MP/2026/1108"
    assert document["latest"]["valid_from"] == "2026-11-10"
    assert document["latest"]["source_url"] == monitor_polski.pdf_url(2026, 1108)
    assert sources["monitor_calls"] == [0]  # pusta historia – szuka od początku roku


def test_same_notice_from_both_sources_is_downloaded_once(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1108, 9)]
    sources["monitor"] = [_mp(1108, 9)]

    assert cli.run(output, backfill=10, year=2026) == 0
    assert len(sources["downloaded"]) == 1


def test_works_when_eli_is_down(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = ConnectionError("ELI down")
    sources["monitor"] = [_mp(1108, 9)]

    assert cli.run(output, backfill=10, year=2026) == 0
    assert _history(output) == ["MP/2026/1108"]


def test_works_when_monitor_is_down(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1101, 6)]
    sources["monitor"] = ConnectionError("RCL down")

    assert cli.run(output, backfill=10, year=2026) == 0
    assert _history(output) == ["MP/2026/1101"]


def test_fails_when_all_sources_are_down(tmp_path, sources):
    sources["eli"] = ConnectionError("ELI down")
    sources["monitor"] = ConnectionError("RCL down")
    sources["gov"] = ConnectionError("gov.pl down")
    assert cli.run(tmp_path / "prices.json", backfill=10, year=2026) == 1


def test_fails_on_unparseable_notice(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1066, 3)]
    sources["text"] = "maksymalnej ceny paliw, zmiana"

    assert cli.run(output, backfill=10, year=2026) == 1
    assert not output.exists()  # nie nadpisujemy danych przy błędzie


@pytest.mark.parametrize("value", ["0", "401", "-5", "abc"])
def test_backfill_out_of_range_is_rejected(value):
    with pytest.raises(SystemExit):
        cli._parse_args(["--backfill", value])


def test_monitor_scans_after_last_known_notice(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1134, 12)]
    assert cli.run(output, backfill=10, year=2026) == 0  # historia: 1134

    sources["monitor"] = [_mp(1140, 13)]
    assert cli.run(output, backfill=10, year=2026) == 0

    assert sources["monitor_calls"] == [0, 1134]
    assert _history(output) == ["MP/2026/1140", "MP/2026/1134"]


def test_writes_github_step_summary(tmp_path, sources, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    sources["eli"] = ConnectionError("ELI down")
    sources["monitor"] = [_mp(1141, 16)]

    assert cli.run(tmp_path / "prices.json", backfill=10, year=2026) == 0

    text = summary.read_text(encoding="utf-8")
    assert "Monitor Polski**: OK, nowe: MP/2026/1141" in text
    assert "API ELI**: BŁĄD" in text


def _gov_notice(announced_day: int) -> Notice:
    price = FuelPrice(gross=Decimal("6.02"))
    return Notice(
        eli=f"GOV/2026-11-{announced_day + 1:02d}",
        position=0,
        announced=date(2026, 11, announced_day),
        prices={"pb95": price, "pb98": price, "on": price},
        source_url="https://www.gov.pl/web/energia/x",
    )


def test_tomorrow_from_gov_when_monitor_is_blocked(tmp_path, sources):
    """Sytuacja z 16.11.2026: Monitor nieosiągalny z GitHuba, ELI ma tylko piątek."""
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1140, 13)]
    sources["monitor"] = ConnectionError("timeout")
    sources["gov"] = [_gov_notice(16)]

    assert cli.run(output, backfill=10, year=2026) == 0

    assert _history(output) == ["GOV/2026-11-17", "MP/2026/1140"]


def test_official_notice_later_replaces_gov_entry(tmp_path, sources):
    output = tmp_path / "prices.json"
    sources["eli"] = [_ref(1140, 13)]
    sources["gov"] = [_gov_notice(16)]
    assert cli.run(output, backfill=10, year=2026) == 0

    sources["eli"] = [_ref(1141, 16), _ref(1140, 13)]  # następnego dnia ELI już ma 1141
    assert cli.run(output, backfill=10, year=2026) == 0

    assert _history(output) == ["MP/2026/1141", "MP/2026/1140"]
