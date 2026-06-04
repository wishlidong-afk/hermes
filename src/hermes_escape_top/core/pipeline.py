"""Integration pipeline harness -- wires integration components into one flow.

Data flow (per INTEGRATION_ARCHITECTURE §9):
  sanitize/failover → score(calibrated/deduplicated) → verdict(hard-valve priority)
  → single risk engine → fragility/disagreement → confidence spine
  → unified optimizer(R3) → routing → audit

Production daily decisions use :mod:`hermes_escape_top.pipeline`.  This module is
kept as a deterministic integration harness for component-level tests and
architecture experiments.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from hermes_escape_top.core.contracts import (
    ConfidenceState,
    Field,
    RiskState,
    SizingDecision,
    Verdict,
)
from hermes_escape_top.core.confidence.spine import compute_confidence
from hermes_escape_top.core.data.sanitize import sanitize_ohlcv, SanitizeResult
from hermes_escape_top.core.data.failover import FailoverSource, FailoverResult
from hermes_escape_top.core.portfolio.risk_engine import build_risk_state
from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets
from hermes_escape_top.core.governance.governance import (
    decision_fragility,
    detect_disagreement,
    attribute,
)
from hermes_escape_top.core.features.context import (
    MarketContext,
    regime_with_transition,
)
from hermes_escape_top.core.monitor.drift import DriftMonitor


# ---------------------------------------------------------------------------
# Pipeline Result
# ---------------------------------------------------------------------------

class PipelineResult:
    """Immutable result of a single pipeline execution."""

    def __init__(
        self,
        as_of: str,
        symbols: List[str],
        sanitize_results: Dict[str, SanitizeResult],
        failover_results: Dict[str, FailoverResult],
        scores: Dict[str, Dict[str, Any]],
        verdicts: Dict[str, Verdict],
        risk_state: RiskState,
        confidence: ConfidenceState,
        sizing: SizingDecision,
        regime: Dict[str, Any],
        fragility: Dict[str, float],
        disagreement: Dict[str, float],
        attribution: Dict[str, List],
        drift_state: Dict[str, Any],
        audit: Dict[str, Any],
    ):
        self.as_of = as_of
        self.symbols = symbols
        self.sanitize_results = sanitize_results
        self.failover_results = failover_results
        self.scores = scores
        self.verdicts = verdicts
        self.risk_state = risk_state
        self.confidence = confidence
        self.sizing = sizing
        self.regime = regime
        self.fragility = fragility
        self.disagreement = disagreement
        self.attribution = attribution
        self.drift_state = drift_state
        self.audit = audit


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def score_pipeline(
    as_of: str,
    store: Dict[str, pd.DataFrame],
    cfg: Dict[str, Any],
    scorer_fn: Any = None,
    verdict_fn: Any = None,
    failover_sources: Optional[Dict[str, FailoverSource]] = None,
    factor_returns: Optional[Dict[str, pd.Series]] = None,
    meta_p_act: Optional[Dict[str, float]] = None,
    mirror_cycles: Optional[Dict[str, str]] = None,
    train_scores: Optional[np.ndarray] = None,
) -> PipelineResult:
    """The SINGLE daily pipeline entry point.

    Wires: sanitize/failover → score → verdict → risk → fragility/disagreement
           → confidence → optimizer(R3) → audit.
    """
    symbols = cfg.get("symbols", ["MSTR", "FNGU", "SOXL"])
    sanitize_cfg = cfg.get("sanitize", {})
    drift_cfg = cfg.get("drift", {})

    # ── Step 1: Data acquisition with failover + sanitization ──
    sanitize_results: Dict[str, SanitizeResult] = {}
    failover_results: Dict[str, FailoverResult] = {}
    clean_store: Dict[str, pd.DataFrame] = {}

    for sym in list(store.keys()):
        if failover_sources and sym in failover_sources:
            fr = failover_sources[sym].fetch(as_of=as_of)
            failover_results[sym] = fr
            raw_df = fr.data if fr.data is not None else store.get(sym, pd.DataFrame())
        else:
            raw_df = store.get(sym, pd.DataFrame())
            failover_results[sym] = FailoverResult(
                data=raw_df, active_source="local", active_rank=1,
                is_degraded=False, tried=[], notes=[],
            )

        sr = sanitize_ohlcv(raw_df, sanitize_cfg)
        sanitize_results[sym] = sr
        clean_store[sym] = sr.clean_df

    # ── Step 2: Market Context ──
    ctx = MarketContext(as_of, clean_store, cfg)
    regime_info = {}
    for sym in symbols:
        regime_info[sym] = regime_with_transition(ctx, sym, cfg.get("regime", {}))

    # ── Step 3: Scoring ──
    scores: Dict[str, Dict[str, Any]] = {}
    if scorer_fn is not None:
        for sym in symbols:
            try:
                scores[sym] = scorer_fn(sym, clean_store, ctx, cfg)
            except Exception as e:
                scores[sym] = {"total": 0, "error": str(e)[:200]}
    else:
        for sym in symbols:
            scores[sym] = _default_score(sym, clean_store, cfg)

    # ── Step 4: Verdict ──
    verdicts: Dict[str, Verdict] = {}
    if verdict_fn is not None:
        for sym in symbols:
            verdicts[sym] = verdict_fn(sym, scores[sym], clean_store, cfg)
    else:
        for sym in symbols:
            verdicts[sym] = _default_verdict(sym, scores[sym], cfg)

    # ── Step 5: Risk Engine (single covariance source) ──
    leg_returns = {}
    for sym in symbols:
        d = clean_store.get(sym, pd.DataFrame())
        if not d.empty and "close" in d.columns:
            leg_returns[sym] = d["close"].pct_change().dropna()

    target_weights = {sym: v.rule_target_weight for sym, v in verdicts.items()}
    risk_state = build_risk_state(leg_returns, target_weights, factor_returns, cfg)

    # ── Step 6: Fragility + Disagreement ──
    frag_values: Dict[str, float] = {}
    disg_values: Dict[str, float] = {}

    for sym in symbols:
        snap = scores.get(sym, {})
        if scorer_fn is not None:
            def _scorer_wrapper(s):
                r = scorer_fn(sym, clean_store, ctx, cfg)
                total = r.get("total", 0)
                thresholds = cfg.get("thresholds", {})
                return "EXIT" if total >= thresholds.get("exit", 75) else "HOLD"
            frag_values[sym] = decision_fragility(snap, _scorer_wrapper, seed=42)
        else:
            frag_values[sym] = 0.0

        disg_values[sym] = detect_disagreement(
            verdicts[sym].status,
            meta_p_act.get(sym) if meta_p_act else None,
            mirror_cycles.get(sym) if mirror_cycles else None,
            cfg.get("governance", {}),
        )

    max_frag = max(frag_values.values()) if frag_values else 0.0
    max_disg = max(disg_values.values()) if disg_values else 0.0

    # ── Step 7: Drift Monitor ──
    drift_state = {"psi": 0.0, "alert": False}
    if train_scores is not None:
        live_scores_arr = np.array([scores[s].get("total", 0) for s in symbols])
        if len(live_scores_arr) > 0:
            monitor = DriftMonitor(drift_cfg)
            drift_state = monitor.evaluate(train_scores, live_scores_arr)

    # ── Step 8: Confidence Spine ──
    data_confs = [sanitize_results[s].data_confidence for s in symbols if s in sanitize_results]
    avg_data_conf = float(np.mean(data_confs)) if data_confs else 0.5

    primary_failover = None
    for sym in symbols:
        if sym in failover_results:
            primary_failover = {
                "is_degraded": failover_results[sym].is_degraded,
                "active_source_rank": failover_results[sym].active_rank,
            }
            break

    staleness_days = _compute_staleness(clean_store, symbols, as_of)

    confidence = compute_confidence(
        data_conf=avg_data_conf,
        failover_state=primary_failover,
        staleness_days=staleness_days,
        drift_state=drift_state,
        fragility=max_frag,
        disagreement=max_disg,
        cfg=cfg,
    )

    # ── Step 9: Sizing Optimizer (single entry, R3 enforced) ──
    liquidity_data = _liquidity_data(clean_store, symbols, cfg)
    sizing = optimize_targets(
        verdicts,
        risk_state,
        confidence,
        cfg,
        leg_returns=leg_returns,
        liquidity_data=liquidity_data,
    )

    # ── Step 10: Attribution ──
    attr_results: Dict[str, List] = {}
    for sym in symbols:
        components = {k: v for k, v in scores.get(sym, {}).items()
                      if isinstance(v, (int, float)) and k != "total"}
        total = scores.get(sym, {}).get("total", 0)
        if total > 0:
            attr_results[sym] = attribute(components, total)
        else:
            attr_results[sym] = []

    # ── Step 11: Audit Log ──
    audit = _build_audit(
        as_of, symbols, scores, verdicts, risk_state,
        confidence, sizing, regime_info, frag_values, disg_values, drift_state,
    )

    return PipelineResult(
        as_of=as_of,
        symbols=symbols,
        sanitize_results=sanitize_results,
        failover_results=failover_results,
        scores=scores,
        verdicts=verdicts,
        risk_state=risk_state,
        confidence=confidence,
        sizing=sizing,
        regime=regime_info,
        fragility=frag_values,
        disagreement=disg_values,
        attribution=attr_results,
        drift_state=drift_state,
        audit=audit,
    )


# ---------------------------------------------------------------------------
# Default scorer/verdict (placeholder for existing scoring chain)
# ---------------------------------------------------------------------------

def _default_score(sym: str, store: Dict[str, pd.DataFrame], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Placeholder: returns zero-score. Real system plugs in A/B/C/D scorer."""
    return {"A": 0, "B": 0, "C": 0, "D": 0, "total": 0, "missing_weight": 0}


def _default_verdict(sym: str, score: Dict[str, Any], cfg: Dict[str, Any]) -> Verdict:
    """Placeholder: maps total score to status via threshold table."""
    total = score.get("total", 0)
    thresholds = cfg.get("thresholds", {
        "exit": 75, "defensive_exit": 65, "reduce": 50, "trim": 35, "watch": 20,
    })
    sleeve_caps = cfg.get("sleeve_caps", {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30})
    cap = sleeve_caps.get(sym, 0.20)

    sell_table = cfg.get("sell_fractions", {
        "EXIT": 1.0, "DEFENSIVE_EXIT": 0.85, "REDUCE": 0.60, "TRIM": 0.35,
    })

    if total >= thresholds["exit"]:
        status, fraction = "EXIT", sell_table["EXIT"]
    elif total >= thresholds["defensive_exit"]:
        status, fraction = "DEFENSIVE_EXIT", sell_table["DEFENSIVE_EXIT"]
    elif total >= thresholds["reduce"]:
        status, fraction = "REDUCE", sell_table["REDUCE"]
    elif total >= thresholds["trim"]:
        status, fraction = "TRIM", sell_table["TRIM"]
    elif total >= thresholds["watch"]:
        status, fraction = "WATCH", 0.0
    else:
        status, fraction = "HOLD", 0.0

    rule_weight = cap * (1.0 - fraction)

    return Verdict(
        symbol=sym,
        status=status,
        rule_target_weight=rule_weight,
        sell_fraction=fraction,
        hard_valve_hits=[],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_staleness(
    store: Dict[str, pd.DataFrame],
    symbols: List[str],
    as_of: str,
) -> float:
    """Max staleness across symbols: days between latest data and as_of."""
    as_of_dt = pd.Timestamp(as_of)
    max_stale = 0.0
    for sym in symbols:
        df = store.get(sym, pd.DataFrame())
        if df.empty:
            max_stale = max(max_stale, 30.0)
            continue
        latest = df.index.max()
        days = (as_of_dt - latest).days
        max_stale = max(max_stale, float(max(0, days)))
    return max_stale


def _liquidity_data(store: Dict[str, pd.DataFrame], symbols: List[str], cfg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    netliq = float(cfg.get("portfolio", {}).get("netliq", cfg.get("netliq", 100_000.0)))
    out: Dict[str, Dict[str, float]] = {}
    for sym in symbols:
        df = store.get(sym, pd.DataFrame())
        if df.empty:
            continue
        close_col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
        if close_col is None:
            continue
        close = pd.to_numeric(df[close_col], errors="coerce").dropna()
        if close.empty:
            continue
        price = float(close.iloc[-1])
        volume_col = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)
        adv20_shares = float("inf")
        adv20_notional = float("inf")
        if volume_col is not None:
            volume = pd.to_numeric(df[volume_col], errors="coerce").dropna().tail(20)
            if len(volume) >= 5:
                adv20_shares = float(volume.mean())
                adv20_notional = adv20_shares * price
        out[sym] = {
            "adv20_shares": adv20_shares,
            "adv20_notional": adv20_notional,
            "price": price,
            "netliq": netliq,
        }
    return out


def _build_audit(
    as_of: str,
    symbols: List[str],
    scores: Dict,
    verdicts: Dict,
    risk: RiskState,
    confidence: ConfidenceState,
    sizing: SizingDecision,
    regime: Dict,
    fragility: Dict,
    disagreement: Dict,
    drift: Dict,
) -> Dict[str, Any]:
    """Build structured audit log for reproducibility."""
    return {
        "as_of": as_of,
        # Deterministic, as_of-anchored timestamp: same inputs -> byte-identical
        # audit, restoring the "逐位一致" reproducibility invariant. (Was
        # datetime.utcnow(), which made every run's audit differ.)
        "timestamp": f"{str(as_of)[:10]}T00:00:00+00:00",
        "symbols": symbols,
        "scores_summary": {s: scores[s].get("total", 0) for s in symbols},
        "verdicts_summary": {s: {"status": verdicts[s].status, "rule_weight": verdicts[s].rule_target_weight} for s in symbols if s in verdicts},
        "risk_summary": {
            "portfolio_vol": risk.portfolio_vol,
            "gross_scaler": risk.gross_scaler,
            "corr_regime": risk.corr_regime,
            "binding": risk.binding,
        },
        "confidence": {
            "decision_confidence": confidence.decision_confidence,
            "mode": confidence.mode,
            "weakest_link": confidence.weakest_link,
        },
        "sizing_summary": {
            "target_weights": sizing.target_weights,
            "binding_constraint": sizing.binding_constraint,
            "confidence_applied": sizing.confidence_applied,
        },
        "regime": {s: regime.get(s, {}).get("regime", "UNKNOWN") for s in symbols},
        "fragility": fragility,
        "disagreement": disagreement,
        "drift": {"psi": drift.get("psi", 0), "alert": drift.get("alert", False)},
    }
