from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Field:
    name: str
    value: Optional[float]
    source: str
    as_of: Optional[date]
    is_proxy: bool = False
    latency_days: int = 0
    quality_penalty: float = 0.0


@dataclass(frozen=True)
class Verdict:
    symbol: str
    status: str
    rule_target_weight: float
    sell_fraction: float
    hard_valve_hits: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConfidenceState:
    decision_confidence: float
    mode: str
    components: Dict[str, float]
    weakest_link: str
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RiskState:
    cov: Any
    corr: Any
    downside_corr: Any
    leg_vol: Dict[str, float]
    legs_used: List[str]
    legs_reported: List[str]
    portfolio_vol: float
    cvar: float
    vol_budget: float
    cvar_budget: float
    vol_scaler: float
    cvar_scaler: float
    gross_scaler: float
    risk_contributions: Dict[str, float]
    factor_betas: Dict[str, Dict[str, float]]
    book_factor_exposure: Dict[str, float]
    corr_regime: str
    binding: str
    explain: List[str]
    estimator_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SizingDecision:
    target_weights: Dict[str, float]
    binding_constraint: Dict[str, str]
    execution_plan: List[Dict[str, Any]]
    expected_utility: float
    confidence_applied: float
    notes: List[str] = field(default_factory=list)
