from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, Optional


@dataclass(frozen=True)
class ValuationRecord:
    symbol: str
    as_of: date
    percentile: Optional[float]
    source: str
    data_available: bool
    quality_penalty: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload


def valuation_missing(symbol: str, as_of: str, reason: str = "valuation source not configured") -> ValuationRecord:
    return ValuationRecord(symbol=symbol, as_of=date.fromisoformat(str(as_of)[:10]), percentile=None, source="valuation_contract", data_available=False, quality_penalty=5.0, reason=reason)
