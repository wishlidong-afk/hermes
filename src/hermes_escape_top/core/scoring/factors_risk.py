"""A9–A16: Tier-1/2 risk-signal factors (credit, rates, dollar, cross-asset).

Every factor here is flag-gated. ``risk_factor_definitions(config)`` returns only
the FactorDefinitions whose feature flag is ON; ``module_a_factors(config)`` appends
that list. With all flags OFF (default) it returns [] → the A-module factor list is
byte-identical to before, so scores / missing-weight / decisions are unchanged.

Scores/thresholds here are reasonable defaults; they are NOT yet calibrated. Enable
one flag at a time and run the shadow + PBO gate before trusting them live.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .registry import FactorContext, FactorDefinition


def _bucket_high(pctl: Optional[float], hi: float = 90, mid: float = 75, lo: float = 60,
                 max_score: float = 4.0, label: str = "") -> tuple[float, str]:
    """High percentile = more risk (e.g. credit spread, real rate, dollar, defensive RS)."""
    if pctl is None:
        return 0.0, f"{label}: unavailable"
    if pctl >= hi:
        return max_score, f"{label} extreme: {pctl:.0f}th pctl"
    if pctl >= mid:
        return round(max_score * 0.75, 2), f"{label} elevated: {pctl:.0f}th pctl"
    if pctl >= lo:
        return round(max_score * 0.5, 2), f"{label} watch: {pctl:.0f}th pctl"
    return 0.0, f"{label} normal: {pctl:.0f}th pctl"


def _bucket_low(pctl: Optional[float], lo: float = 10, mid: float = 25, hi: float = 40,
                max_score: float = 4.0, label: str = "") -> tuple[float, str]:
    """Low percentile = more risk (e.g. risk-on ETF ratio rolling over)."""
    if pctl is None:
        return 0.0, f"{label}: unavailable"
    if pctl <= lo:
        return max_score, f"{label} breakdown: {pctl:.0f}th pctl"
    if pctl <= mid:
        return round(max_score * 0.75, 2), f"{label} weak: {pctl:.0f}th pctl"
    if pctl <= hi:
        return round(max_score * 0.5, 2), f"{label} softening: {pctl:.0f}th pctl"
    return 0.0, f"{label} healthy: {pctl:.0f}th pctl"


def _hy_oas(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_high(ctx.get("SOFT.hy_oas_pctl"), label="HY credit spread")


def _real_rate(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_high(ctx.get("SOFT.real_rate_10y_pctl"), label="10Y real yield")


def _dollar(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_high(ctx.get("SOFT.dollar_broad_pctl"), label="Broad dollar")


def _yield_curve(ctx: FactorContext) -> tuple[float, str]:
    v = ctx.get("SOFT.yield_curve_10y3m")
    if v is None:
        return 0.0, "10Y-3M curve: unavailable"
    if v <= -0.5:
        return 4.0, f"10Y-3M deeply inverted: {v:.2f}"
    if v < 0.0:
        return 3.0, f"10Y-3M inverted: {v:.2f}"
    if v < 0.5:
        return 1.0, f"10Y-3M flat: {v:.2f}"
    return 0.0, f"10Y-3M normal: {v:.2f}"


def _credit_etf(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_low(ctx.get("SOFT.credit_etf_ratio_pctl"), label="HYG/IEF credit")


def _concentration(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_low(ctx.get("SOFT.concentration_rsp_spy_pctl"), label="RSP/SPY breadth")


def _defensive_rotation(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_high(ctx.get("SOFT.defensive_cyclical_pctl"), label="Defensive rotation")


def _financial_stress(ctx: FactorContext) -> tuple[float, str]:
    return _bucket_low(ctx.get("SOFT.financial_stress_xlf_pctl"), label="XLF/SPY financials")


def _nfci(ctx: FactorContext) -> tuple[float, str]:
    # NFCI > 0 = tighter-than-average financial conditions; high percentile = stress.
    return _bucket_high(ctx.get("SOFT.nfci_pctl"), label="Financial conditions (NFCI)")


def _move(ctx: FactorContext) -> tuple[float, str]:
    # MOVE = bond-market implied vol; spikes often lead equity VIX / risk-off.
    return _bucket_high(ctx.get("SOFT.move_pctl"), label="Bond vol (MOVE)")


def _ndx_concentration(ctx: FactorContext) -> tuple[float, str]:
    # Equal-weight QQQE underperforming cap-weight QQQ = Nasdaq breadth narrowing
    # (a few mega-caps carrying the index) = classic late-cycle top tell.
    return _bucket_low(ctx.get("SOFT.ndx_concentration_pctl"), label="QQQE/QQQ NDX breadth")


def _cot_nq(ctx: FactorContext) -> tuple[float, str]:
    # CFTC COT NQ: combined asset-mgr + leveraged-fund net-long / OI.
    # High percentile = speculative/institutional positioning crowded long
    # = elevated unwind risk (contrarian — high score = more risk).
    return _bucket_high(ctx.get("SOFT.cot_nq_net_oi_pct_pctl"), label="NQ COT net positioning")


# (feature_flag, FactorDefinition) — each appended only when its flag is ON.
_RISK_FACTORS: List[tuple[str, FactorDefinition]] = [
    ("data_hy_oas", FactorDefinition("A9_HY_OAS", "A", 4.0, ["SOFT.hy_oas_pctl"], _hy_oas, "A9 hy_oas")),
    ("data_real_rate", FactorDefinition("A10_REAL_RATE", "A", 4.0, ["SOFT.real_rate_10y_pctl"], _real_rate, "A10 real_rate")),
    ("data_dollar", FactorDefinition("A11_DOLLAR", "A", 4.0, ["SOFT.dollar_broad_pctl"], _dollar, "A11 dollar")),
    ("data_yield_curve", FactorDefinition("A12_YIELD_CURVE", "A", 4.0, ["SOFT.yield_curve_10y3m"], _yield_curve, "A12 yield_curve")),
    ("data_credit_etf", FactorDefinition("A13_CREDIT_ETF", "A", 4.0, ["SOFT.credit_etf_ratio_pctl"], _credit_etf, "A13 credit_etf")),
    ("data_concentration", FactorDefinition("A14_CONCENTRATION", "A", 4.0, ["SOFT.concentration_rsp_spy_pctl"], _concentration, "A14 concentration")),
    ("data_defensive_rotation", FactorDefinition("A15_DEFENSIVE_ROTATION", "A", 4.0, ["SOFT.defensive_cyclical_pctl"], _defensive_rotation, "A15 defensive_rotation")),
    ("data_financial_stress", FactorDefinition("A16_FINANCIAL_STRESS", "A", 4.0, ["SOFT.financial_stress_xlf_pctl"], _financial_stress, "A16 financial_stress")),
    ("data_nfci", FactorDefinition("A17_NFCI", "A", 4.0, ["SOFT.nfci_pctl"], _nfci, "A17 nfci")),
    ("data_move", FactorDefinition("A18_MOVE", "A", 4.0, ["SOFT.move_pctl"], _move, "A18 move")),
    ("data_ndx_concentration", FactorDefinition("A19_NDX_CONCENTRATION", "A", 4.0, ["SOFT.ndx_concentration_pctl"], _ndx_concentration, "A19 ndx_concentration")),
    ("data_cot_nq", FactorDefinition("A20_COT_NQ", "A", 4.0, ["SOFT.cot_nq_net_oi_pct_pctl"], _cot_nq, "A20 cot_nq")),
]


def risk_factor_definitions(config: Optional[Dict[str, Any]]) -> List[FactorDefinition]:
    if not config:
        return []
    feats = config.get("features", {}) or {}
    return [fd for flag, fd in _RISK_FACTORS if bool(feats.get(flag, False))]
