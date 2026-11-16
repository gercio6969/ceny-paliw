"""Modele danych: cena pojedynczego paliwa i całe obwieszczenie."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

FUEL_KEYS = ("pb95", "pb98", "on")


@dataclass(frozen=True)
class FuelPrice:
    gross: Decimal  # zł za 1 l, z VAT
    net: Decimal | None = None  # zł za 1 dm3, bez VAT; brak w komunikacie na gov.pl

    def to_dict(self) -> dict[str, float | None]:
        return {
            "net": float(self.net) if self.net is not None else None,
            "gross": float(self.gross),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FuelPrice:
        net = data.get("net")
        return cls(
            gross=Decimal(str(data["gross"])),
            net=Decimal(str(net)) if net is not None else None,
        )


OFFICIAL_PREFIX = "MP/"


@dataclass(frozen=True)
class Notice:
    """Jedno obwieszczenie w sprawie maksymalnej ceny paliw."""

    eli: str  # np. "MP/2026/1065"; komunikat z gov.pl przed publikacją w ELI: "GOV/2026-11-17"
    position: int
    announced: date  # data ogłoszenia w Monitorze Polskim
    prices: dict[str, FuelPrice] = field(default_factory=dict)
    source_url: str = ""

    @property
    def is_official(self) -> bool:
        """Obwieszczenie z Monitora Polskiego (a nie komunikat ministerstwa na gov.pl)."""
        return self.eli.startswith(OFFICIAL_PREFIX)

    @property
    def valid_from(self) -> date:
        # Ceny obowiązują od dnia następującego po ogłoszeniu obwieszczenia.
        return self.announced + timedelta(days=1)

    def to_dict(self) -> dict:
        return {
            "eli": self.eli,
            "position": self.position,
            "announced": self.announced.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "source_url": self.source_url,
            "prices": {key: self.prices[key].to_dict() for key in FUEL_KEYS if key in self.prices},
        }

    @classmethod
    def from_dict(cls, data: dict) -> Notice:
        return cls(
            eli=data["eli"],
            position=int(data["position"]),
            announced=date.fromisoformat(data["announced"]),
            prices={k: FuelPrice.from_dict(v) for k, v in data["prices"].items()},
            source_url=data.get("source_url", ""),
        )
