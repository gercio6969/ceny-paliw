"""Modele danych: cena pojedynczego paliwa i całe obwieszczenie."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

FUEL_KEYS = ("pb95", "pb98", "on")


@dataclass(frozen=True)
class FuelPrice:
    net: Decimal  # zł za 1 dm3, bez VAT
    gross: Decimal  # zł za 1 l, z VAT

    def to_dict(self) -> dict[str, float]:
        return {"net": float(self.net), "gross": float(self.gross)}

    @classmethod
    def from_dict(cls, data: dict) -> FuelPrice:
        return cls(net=Decimal(str(data["net"])), gross=Decimal(str(data["gross"])))


@dataclass(frozen=True)
class Notice:
    """Jedno obwieszczenie w sprawie maksymalnej ceny paliw."""

    eli: str  # np. "MP/2026/1065"
    position: int
    announced: date  # data ogłoszenia w Monitorze Polskim
    prices: dict[str, FuelPrice] = field(default_factory=dict)
    source_url: str = ""

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
