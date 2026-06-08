from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List


@dataclass
class ScoreResult:
    symbol: str
    as_of: date
    module_scores: Dict[str, float] = field(default_factory=lambda: {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0})
    raw_total: float = 0.0
    final_score: float = 0.0
    missing_weight: float = 0.0
    confidence_missing_weight: float = 0.0
    confidence_missing_fields: List[str] = field(default_factory=list)
    non_scoring_missing_weight: float = 0.0
    non_scoring_missing_fields: List[str] = field(default_factory=list)
    blind_spot: bool = False
    data_quality: float = 100.0
    hard_valve_hits: List[str] = field(default_factory=list)
    status: str = "HOLD"
    raw_status: str = "HOLD"
    sell_fraction: float = 0.0
    explain: List[str] = field(default_factory=list)
    factor_scores: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        return payload

    @classmethod
    def empty(cls, symbol: str, as_of: date) -> "ScoreResult":
        return cls(symbol=symbol, as_of=as_of, explain=["greenfield empty score result"])
