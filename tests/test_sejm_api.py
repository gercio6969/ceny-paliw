from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import pytest

from fuelprices import sejm_api
from fuelprices.parser import parse_prices


def _item(pos: int, title: str, promulgation: str = "2026-11-02") -> dict:
    return {
        "ELI": f"MP/2026/{pos}",
        "year": 2026,
        "pos": pos,
        "title": title,
        "promulgation": promulgation,
    }


FUEL_TITLE = (
    "Obwieszczenie Ministra Energii w sprawie maksymalnej ceny paliw ciekłych na stacji paliw"
)


def test_select_notices_filters_and_sorts():
    items = [
        _item(1001, FUEL_TITLE, "2026-10-20"),
        _item(1002, "Obwieszczenie w sprawie wysokości minimalnego wynagrodzenia"),
        _item(1065, FUEL_TITLE),
        _item(1065, FUEL_TITLE),  # duplikat
        {"title": FUEL_TITLE},  # niekompletny rekord
    ]

    refs = sejm_api.select_notices(items)

    assert [r.position for r in refs] == [1065, 1001]
    assert refs[0].announced == date(2026, 11, 2)
    assert refs[0].pdf_url == "https://api.sejm.gov.pl/eli/acts/MP/2026/1065/text.pdf"


class _Response:
    def __init__(self, *, json_data=None, content=b"", headers=None):
        self.content = json.dumps(json_data).encode() if json_data is not None else content
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i : i + chunk_size]


class _Session:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append(url)
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_find_notices_falls_back_to_year_listing():
    import requests

    session = _Session(
        {
            f"{sejm_api.BASE_URL}/acts/search": requests.ConnectionError("down"),
            f"{sejm_api.BASE_URL}/acts/MP/2026": _Response(
                json_data={"items": [_item(1065, FUEL_TITLE)]}
            ),
        }
    )

    refs = sejm_api.find_notices(session, 2026)

    assert [r.eli for r in refs] == ["MP/2026/1065"]
    assert len(session.calls) == 2


def _make_pdf(text: str) -> bytes:
    reportlab = pytest.importorskip("reportlab")
    del reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = next(
        (
            p
            for p in (
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            )
            if p.exists()
        ),
        None,
    )
    if font is None:
        pytest.skip("brak fontu z polskimi znakami")
    pdfmetrics.registerFont(TTFont("DejaVu", str(font)))

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont("DejaVu", 10)
    y = 800
    for line in text.splitlines():
        pdf.drawString(50, y, line)
        y -= 14
    pdf.save()
    return buffer.getvalue()


def test_download_text_extracts_pdf(notice_text):
    ref = sejm_api.ActRef("MP/2026/1065", 2026, 1065, FUEL_TITLE, date(2026, 11, 2))
    session = _Session({ref.pdf_url: _Response(content=_make_pdf(notice_text))})

    text = sejm_api.download_text(session, ref)

    assert parse_prices(text)["pb95"].gross == parse_prices(notice_text)["pb95"].gross


def test_fetch_limited_rejects_declared_oversize():
    session = _Session({"u": _Response(content=b"x", headers={"Content-Length": "999999999"})})
    with pytest.raises(sejm_api.ResponseTooLarge):
        sejm_api.fetch_limited(session, "u", max_bytes=1024)


def test_fetch_limited_rejects_streamed_oversize():
    session = _Session({"u": _Response(content=b"x" * 200_000)})
    with pytest.raises(sejm_api.ResponseTooLarge):
        sejm_api.fetch_limited(session, "u", max_bytes=100_000)


def test_download_text_rejects_non_pdf():
    ref = sejm_api.ActRef("MP/2026/1065", 2026, 1065, FUEL_TITLE, date(2026, 11, 2))
    session = _Session({ref.pdf_url: _Response(content=b"<html>blad</html>")})
    with pytest.raises(ValueError, match="nie jest plikiem PDF"):
        sejm_api.download_text(session, ref)
