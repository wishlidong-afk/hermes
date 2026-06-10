from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from ..data.base import SymbolSnapshot
from ..data.quality import analyze_missing_fields, quality_from_snapshots
from ..decision.verdict import VerdictInput, make_verdict, sell_fraction_for as verdict_sell_fraction_for
from ..decision.verdict import status_from_score as verdict_status_from_score
from ..features.regime import Regime
from .hard_valves import evaluate_hard_valves
from .module_a import module_a_factors
from .module_b import module_b_factors
from .module_c import module_c_factors
from .module_d import module_d_factors
from .registry import FactorContext, FactorRegistry, FactorScore
from .result import ScoreResult


STATUS_ORDER = ["HOLD", "WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"]


@dataclass(frozen=True)
class ScoreBundle:
    result: ScoreResult
    factors: List[FactorScore]


def score_symbol(
    symbol: str,
    snapshots: Dict[str, SymbolSnapshot],
    config: Dict[str, Any],
    regime: Regime = Regime.UNKNOWN,
    histories: Optional[Dict[str, Any]] = None,
    suspect: bool = False,
    previous_status: Optional[str] = None,
) -> ScoreBundle:
    if symbol not in snapshots:
        raise KeyError(f"missing primary snapshot for {symbol}")
    factors = build_registry(symbol, config).evaluate(FactorContext(symbol=symbol, snapshots=snapshots, config=config))
    module_scores = aggregate_modules(factors, config)
    raw_total = weighted_percent_score(symbol, module_scores, config, regime=regime)
    missing_fields = [field for factor in factors for field in factor.missing_fields]
    missing = analyze_missing_fields(missing_fields, raw_total, config)
    confidence_missing_fields = [
        field
        for factor in factors
        if float(factor.max_score) > 0
        for field in factor.missing_fields
    ]
    confidence_missing = analyze_missing_fields(confidence_missing_fields, raw_total, config)
    non_scoring_missing_fields = sorted(set(missing.missing_fields) - set(confidence_missing.missing_fields))
    non_scoring_missing = analyze_missing_fields(non_scoring_missing_fields, raw_total, config)
    # F5/F6: drive score-inflation + blind-spot off the *scoring* missing weight
    # (max_score>0 factors only), so permanently-unwired placeholders (A2 CNN, B5,
    # D-M4, D-M5) no longer consume the live blind-spot budget or inflate the score.
    # Flag-gated, default OFF → byte-identical (uses the full missing weight).
    operational_missing = (
        confidence_missing
        if bool(config.get("features", {}).get("use_scored_missing_weight", False))
        else missing
    )
    final_score = operational_missing.adjusted_score
    status = status_from_score(final_score, config)
    hv_cfg = config.get("hard_valves", {}) if isinstance(config.get("hard_valves"), dict) else {}
    hm2_buffer = bool(config.get("features", {}).get("use_hm2_buffer", False))
    hard = evaluate_hard_valves(
        symbol, snapshots, total_score=final_score, c_score=module_scores.get("C", 0.0),
        histories=histories, suspect=suspect, hm2_buffer=hm2_buffer,
        hm2_buffer_status=str(hv_cfg.get("hm2_buffer_status", "DEFENSIVE_EXIT")),
    )
    verdict = make_verdict(
        VerdictInput(
            symbol=symbol,
            score=final_score,
            module_scores=module_scores,
            hard_valve_hits=hard.ids,
            missing_weight=operational_missing.missing_weight,
            red_light_count=red_light_count(factors),
            qqq_below_ema20=_qqq_below_ema20(snapshots),
            threshold_relief=_arming_relief(snapshots, config),
            previous_status=previous_status,
            hard_floor_status=hard.buffer_status if hard.buffered else None,
        ),
        config,
    )
    explain = build_explain(factors, operational_missing.blind_spot)
    explain = verdict.reasons + explain
    if hard.triggered:
        explain.insert(0, f"Hard valve triggered {','.join(hard.ids)}: {hard.reason}")
    elif hard.pending:
        explain.insert(0, f"Hard valve PENDING (suspect bar) {','.join(hard.pending_ids)}: {hard.pending_reason}")
    elif hard.buffered:
        explain.insert(0, f"Hard valve BUFFERED {','.join(hard.buffered_ids)}: lone H-M2 → {hard.buffer_status} (not instant EXIT); continuation valve will confirm full exit")
    result = ScoreResult(
        symbol=symbol,
        as_of=snapshots[symbol].as_of,
        module_scores=module_scores,
        raw_total=raw_total,
        final_score=final_score,
        missing_weight=operational_missing.missing_weight,
        confidence_missing_weight=confidence_missing.missing_weight,
        confidence_missing_fields=confidence_missing.missing_fields,
        non_scoring_missing_weight=non_scoring_missing.missing_weight,
        non_scoring_missing_fields=non_scoring_missing.missing_fields,
        blind_spot=operational_missing.blind_spot,
        data_quality=quality_from_snapshots([snapshots[symbol]]).overall_score,
        hard_valve_hits=hard.ids,
        status=verdict.status,
        raw_status=verdict.raw_status,
        sell_fraction=verdict.sell_fraction,
        explain=explain,
        factor_scores={module: [factor.to_dict() for factor in factors if factor.module == module] for module in ["A", "B", "C", "D"]},
    )
    return ScoreBundle(result=result, factors=factors)


def build_registry(symbol: str, config: Optional[Dict[str, Any]] = None) -> FactorRegistry:
    return FactorRegistry(module_a_factors(config) + module_b_factors(symbol) + module_c_factors() + module_d_factors(symbol))


def aggregate_modules(factors: Iterable[FactorScore], config: Dict[str, Any]) -> Dict[str, float]:
    caps = {module: float(value) for module, value in config.get("module_caps", {}).items()}
    totals = {module: 0.0 for module in caps}
    for factor in factors:
        totals.setdefault(factor.module, 0.0)
        totals[factor.module] += float(factor.score)
    return {module: round(min(score, caps.get(module, score)), 4) for module, score in sorted(totals.items())}


def weighted_percent_score(
    symbol: str,
    module_scores: Dict[str, float],
    config: Dict[str, Any],
    regime: Regime = Regime.UNKNOWN,
) -> float:
    caps = {module: float(value) for module, value in config.get("module_caps", {}).items()}
    weights = dict(config.get("symbols", {}).get(symbol, {}).get("module_weights", {}))
    for module in caps:
        weights.setdefault(module, 1.0)
    regime_name = regime.value if isinstance(regime, Regime) else str(regime)
    if bool(config.get("features", {}).get("use_regime_multipliers", True)):
        for module, multiplier in config.get("regime", {}).get("multipliers", {}).get(regime_name, {}).items():
            if module in weights:
                weights[module] = float(weights[module]) * float(multiplier)
    weighted = sum(float(module_scores.get(module, 0.0)) * float(weights.get(module, 1.0)) for module in caps)
    weighted_cap = sum(float(caps[module]) * float(weights.get(module, 1.0)) for module in caps)
    if weighted_cap <= 0:
        return 0.0
    return round(min(100.0, max(0.0, weighted / weighted_cap * 100.0)), 4)


def status_from_score(score: float, config: Dict[str, Any]) -> str:
    return verdict_status_from_score(score, config)


def sell_fraction_for(symbol: str, status: str, config: Dict[str, Any]) -> float:
    return verdict_sell_fraction_for(symbol, status, config)


def build_explain(factors: Iterable[FactorScore], blind_spot: bool) -> List[str]:
    messages = []
    if blind_spot:
        messages.append("Blind-spot penalty active: missing data weight exceeds configured threshold")
    for factor in factors:
        if factor.active:
            messages.append(factor.explain)
    return messages


def red_light_count(factors: Iterable[FactorScore]) -> int:
    return sum(1 for factor in factors if factor.max_score > 0 and factor.score / factor.max_score >= 0.75)


def _qqq_below_ema20(snapshots: Dict[str, SymbolSnapshot]) -> bool:
    snap = snapshots.get("QQQ")
    if snap is None:
        return False
    close = snap.get("close")
    ema20 = snap.get("ema20")
    return close is not None and ema20 is not None and close < ema20


# Leading, NON-additive macro signals that "arm" the system (lower thresholds for
# coincident technical factors). Signals already in the additive A-module score
# (A10 real_rate, A11 dollar) are intentionally EXCLUDED to avoid double-counting:
# they both raise the total score AND would lower the trigger bar simultaneously.
_ARM_HIGH = [
    "move_pctl",   # bond implied vol (MOVE) — early cross-asset stress signal
    "nfci_pctl",   # NFCI financial conditions — leading macro tightness
]
_ARM_LOW = [
    "yield_curve_10y3m_pctl",     # low = curve inverted = macro downturn signal
    "ndx_concentration_pctl",     # low = NDX breadth narrow = late-cycle tell
    "concentration_rsp_spy_pctl", # low = SPX breadth narrow
    "credit_etf_ratio_pctl",      # low = HYG/IEF deteriorating = credit stress
]


def _arming_relief(snapshots: Dict[str, SymbolSnapshot], config: Dict[str, Any]) -> float:
    """Arm-then-fire (flag-gated, default OFF → returns 0.0 → byte-identical).

    Counts leading macro factors currently in their risk zone and converts that
    into a threshold relief (points), so the *coincident* technical score trips a
    more defensive status earlier — but only while macro conditions are stressed
    (that conditionality is the precision lever). Bounded + calibratable."""
    if not bool(config.get("features", {}).get("use_arm_then_fire", False)):
        return 0.0
    soft = snapshots.get("SOFT")
    if soft is None:
        return 0.0
    cfg = config.get("arm_then_fire", {}) if isinstance(config.get("arm_then_fire"), dict) else {}
    hi_thr = float(cfg.get("high_pctl", 75.0))
    lo_thr = float(cfg.get("low_pctl", 25.0))
    armed = 0
    for fld in _ARM_HIGH:
        v = soft.get(fld)
        if v is not None and float(v) >= hi_thr:
            armed += 1
    for fld in _ARM_LOW:
        v = soft.get(fld)
        if v is not None and float(v) <= lo_thr:
            armed += 1
    per = float(cfg.get("relief_per_factor", 2.0))
    cap = float(cfg.get("relief_cap", 8.0))
    return min(cap, armed * per)


def score_results_to_dict(results: Dict[str, ScoreBundle]) -> Dict[str, Any]:
    return {symbol: bundle.result.to_dict() for symbol, bundle in sorted(results.items())}
