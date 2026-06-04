from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Regime(str, Enum):
    LOW_VOL_TREND = "LOW_VOL_TREND"
    CHOP = "CHOP"
    HIGH_VOL = "HIGH_VOL"
    CRISIS = "CRISIS"
    UNKNOWN = "UNKNOWN"


RISK_RANK = {
    Regime.UNKNOWN: 1,
    Regime.LOW_VOL_TREND: 0,
    Regime.CHOP: 1,
    Regime.HIGH_VOL: 2,
    Regime.CRISIS: 3,
}


@dataclass(frozen=True)
class RegimeInput:
    close: Optional[float]
    ema20: Optional[float]
    ema50: Optional[float]
    ma200: Optional[float]
    vix_percentile: Optional[float]
    vix_term_ratio: Optional[float] = None


@dataclass
class RegimeHysteresis:
    current: Regime = Regime.UNKNOWN
    pending: Optional[Regime] = None
    pending_days: int = 0
    min_dwell_days_on_exit: int = 3

    def update(self, candidate: Regime) -> Regime:
        if self.current == Regime.UNKNOWN:
            self.current = candidate
            self.pending = None
            self.pending_days = 0
            return self.current

        if candidate == self.current:
            self.pending = None
            self.pending_days = 0
            return self.current

        current_rank = RISK_RANK[self.current]
        candidate_rank = RISK_RANK[candidate]

        # Risk deterioration is immediate. Risk improvement needs persistence.
        if candidate_rank > current_rank:
            self.current = candidate
            self.pending = None
            self.pending_days = 0
            return self.current

        if self.pending == candidate:
            self.pending_days += 1
        else:
            self.pending = candidate
            self.pending_days = 1

        if self.pending_days >= self.min_dwell_days_on_exit:
            self.current = candidate
            self.pending = None
            self.pending_days = 0

        return self.current


def classify_regime(inputs: RegimeInput) -> Regime:
    if _missing(inputs.close, inputs.ema20, inputs.ema50, inputs.ma200):
        return Regime.UNKNOWN

    close = float(inputs.close)
    ema20 = float(inputs.ema20)
    ema50 = float(inputs.ema50)
    ma200 = float(inputs.ma200)
    vix_pct = inputs.vix_percentile
    term_ratio = inputs.vix_term_ratio

    trend_broken = close < ma200
    short_trend_broken = close < ema50
    backwardation = term_ratio is not None and term_ratio >= 1.0

    if trend_broken and (_gte(vix_pct, 75.0) or backwardation):
        return Regime.CRISIS
    if _gte(vix_pct, 90.0) or (backwardation and short_trend_broken):
        return Regime.CRISIS

    if _gte(vix_pct, 70.0) or short_trend_broken or (term_ratio is not None and term_ratio >= 0.96):
        return Regime.HIGH_VOL

    if close > ema20 > ema50 > ma200 and not _gte(vix_pct, 70.0):
        return Regime.LOW_VOL_TREND

    return Regime.CHOP


def _gte(value: Optional[float], threshold: float) -> bool:
    return value is not None and float(value) >= threshold


def _missing(*values: Optional[float]) -> bool:
    return any(value is None for value in values)
