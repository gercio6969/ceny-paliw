from datetime import date
from pathlib import Path

from fuelprices import monitor_polski

FIXTURES = Path(__file__).parent / "fixtures"

# Fragmenty odwzorowujące strukturę strony pozycji na monitorpolski.gov.pl (stan na 2026 r.).
FUEL_PAGE = """
<h1 id="h_title">Monitor Polski 2026 r. poz. 1108</h1>
<div id="content"> <h2 class="one-item-heading">Obwieszczenie Ministra Energii z dnia
9 listopada 2026 r. w sprawie maksymalnej ceny paliw ciek&#322;ych na stacji paliw</h2>
<table><tr><td class="width150px textBold">Data ogłoszenia: </td>
<td class="fontLarge"> <span> 2026-11-09 </span> </td></tr></table>
"""
OTHER_PAGE = FUEL_PAGE.replace(
    "Obwieszczenie Ministra Energii z dnia\n9 listopada 2026 r. w sprawie maksymalnej ceny "
    "paliw ciek&#322;ych na stacji paliw",
    "Postanowienie Prezydenta Rzeczypospolitej Polskiej o nadaniu orderów",
)
MISSING_PAGE = '<h1 id="h_title">Dziennik Ustaw</h1><div id="content"></div>'


def test_parses_fuel_notice_page():
    item = monitor_polski.parse_position_page(FUEL_PAGE, 2026, 1108)
    assert item.is_fuel_notice
    assert item.announced == date(2026, 11, 9)
    assert item.eli == "MP/2026/1108"
    assert "ciekłych" in item.title  # encje HTML zamienione na znaki


def test_other_act_is_not_fuel_notice():
    assert not monitor_polski.parse_position_page(OTHER_PAGE, 2026, 1109).is_fuel_notice


def test_missing_position_returns_none():
    assert monitor_polski.parse_position_page(MISSING_PAGE, 2026, 1300) is None


def test_pdf_url_format():
    assert monitor_polski.pdf_url(2026, 1108) == "https://monitorpolski.gov.pl/M2026000110801.pdf"


def test_find_scans_forward_and_stops_after_missing(monkeypatch):
    pages = {1102: OTHER_PAGE, 1103: FUEL_PAGE, 1104: OTHER_PAGE, 1105: FUEL_PAGE}
    calls = []

    def fake_fetch(session, year, position):
        calls.append(position)
        page = pages.get(position, MISSING_PAGE)
        return monitor_polski.parse_position_page(page, year, position)

    monkeypatch.setattr(monitor_polski, "fetch_position", fake_fetch)

    found = monitor_polski.find_new_fuel_notices(None, 2026, last_known_position=1101)

    assert [p.position for p in found] == [1105, 1103]
    assert calls == [1102, 1103, 1104, 1105, 1106, 1107, 1108]  # 3 kolejne braki = koniec


def test_real_page_snapshot():
    """Fragment prawdziwej strony poz. 1108 z 9 listopada 2026 r."""
    text = (FIXTURES / "monitor_polski_1108.html").read_text(encoding="utf-8")
    item = monitor_polski.parse_position_page(text, 2026, 1108)
    assert item.is_fuel_notice
    assert item.announced == date(2026, 11, 9)
    assert item.title.startswith("Obwieszczenie Ministra Energii z dnia 9 listopada 2026 r.")


def test_real_missing_page_snapshot():
    text = (FIXTURES / "monitor_polski_brak.html").read_text(encoding="utf-8")
    assert monitor_polski.parse_position_page(text, 2026, 1300) is None
