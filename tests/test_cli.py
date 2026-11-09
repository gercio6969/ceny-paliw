import json
from datetime import date

import pytest

from fuelprices import cli, sejm_api


def _ref(pos: int, day: int) -> sejm_api.ActRef:
    return sejm_api.ActRef(
        f"MP/2026/{pos}", 2026, pos, "maksymalnej ceny paliw", date(2026, 11, day)
    )


def test_run_adds_new_notices_and_skips_known(tmp_path, monkeypatch, notice_text):
    output = tmp_path / "prices.json"
    downloaded = []
    monkeypatch.setattr(sejm_api, "make_session", lambda: None)
    monkeypatch.setattr(sejm_api, "find_notices", lambda s, y: [_ref(1066, 3), _ref(1065, 2)])

    def fake_download(session, ref):
        downloaded.append(ref.eli)
        return notice_text

    monkeypatch.setattr(sejm_api, "download_text", fake_download)

    assert cli.run(output, backfill=10, year=2026) == 0
    assert cli.run(output, backfill=10, year=2026) == 0  # drugi przebieg: nic nowego

    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["latest"]["eli"] == "MP/2026/1066"
    assert [n["eli"] for n in document["history"]] == ["MP/2026/1066", "MP/2026/1065"]
    assert downloaded == ["MP/2026/1066", "MP/2026/1065"]


def test_run_fails_on_unparseable_notice(tmp_path, monkeypatch):
    output = tmp_path / "prices.json"
    monkeypatch.setattr(sejm_api, "make_session", lambda: None)
    monkeypatch.setattr(sejm_api, "find_notices", lambda s, y: [_ref(1066, 3)])
    monkeypatch.setattr(sejm_api, "download_text", lambda s, r: "maksymalnej ceny paliw, zmiana")

    assert cli.run(output, backfill=10, year=2026) == 1
    assert not output.exists()  # nie nadpisujemy danych przy błędzie


@pytest.mark.parametrize("value", ["0", "401", "-5", "abc"])
def test_backfill_out_of_range_is_rejected(value):
    with pytest.raises(SystemExit):
        cli._parse_args(["--backfill", value])
