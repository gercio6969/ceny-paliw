import json
from datetime import UTC, date, datetime
from decimal import Decimal

from fuelprices import storage
from fuelprices.models import FuelPrice, Notice


def _notice(pos: int, day: int) -> Notice:
    price = FuelPrice(net=Decimal("5.98"), gross=Decimal("6.45"))
    return Notice(
        eli=f"MP/2026/{pos}",
        position=pos,
        announced=date(2026, 11, day),
        prices={"pb95": price, "pb98": price, "on": price},
    )


def test_merge_deduplicates_and_sorts_newest_first():
    history = [_notice(1000, 2), _notice(990, 1)]
    merged = storage.merge(history, [_notice(1010, 3), _notice(1000, 2)])
    assert [n.position for n in merged] == [1010, 1000, 990]


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "data" / "prices.json"
    history = [_notice(1065, 2)]

    storage.save(path, history, now=datetime(2026, 11, 2, 12, 0, tzinfo=UTC))

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["latest"]["eli"] == "MP/2026/1065"
    assert document["latest"]["valid_from"] == "2026-11-03"
    assert document["latest"]["prices"]["pb95"] == {"net": 5.98, "gross": 6.45}
    assert storage.load_history(path) == history


def test_load_missing_file(tmp_path):
    assert storage.load_history(tmp_path / "missing.json") == []
