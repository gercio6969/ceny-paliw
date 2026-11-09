from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def notice_text() -> str:
    return (FIXTURES / "obwieszczenie.txt").read_text(encoding="utf-8")
