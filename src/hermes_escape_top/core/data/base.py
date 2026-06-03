from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Field:
    name: str
    value: Optional[float]
    source: str
    as_of: Optional[date]
    is_proxy: bool = False
    latency_days: int = 0
    quality_penalty: float = 0.0

    @property
    def missing(self) -> bool:
        return self.value is None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat() if self.as_of else None
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Field":
        raw_date = payload.get("as_of")
        parsed = date.fromisoformat(raw_date) if raw_date else None
        return cls(
            name=str(payload["name"]),
            value=payload.get("value"),
            source=str(payload.get("source") or "unknown"),
            as_of=parsed,
            is_proxy=bool(payload.get("is_proxy", False)),
            latency_days=int(payload.get("latency_days") or 0),
            quality_penalty=float(payload.get("quality_penalty") or 0.0),
        )


@dataclass
class SymbolSnapshot:
    symbol: str
    as_of: date
    fields: Dict[str, Field] = field(default_factory=dict)

    def get(self, name: str) -> Optional[float]:
        field_item = self.fields.get(name)
        return field_item.value if field_item else None

    def field(self, name: str) -> Optional[Field]:
        return self.fields.get(name)

    def is_missing(self, name: str) -> bool:
        return name not in self.fields or self.fields[name].missing

    def missing_fields(self) -> list[str]:
        return [name for name, item in sorted(self.fields.items()) if item.missing]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "fields": {name: item.to_dict() for name, item in sorted(self.fields.items())},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SymbolSnapshot":
        return cls(
            symbol=str(payload["symbol"]),
            as_of=date.fromisoformat(str(payload["as_of"])),
            fields={name: Field.from_dict(value) for name, value in payload.get("fields", {}).items()},
        )

