"""SizingOptimizer -- the SINGLE sizing entry point for the entire system.

Absorbs E6/E8/E12/E15/E25/E26/E27. Replaces all scaler multiplication chains.
All target weights come from optimize_targets(); no ad-hoc scaler chaining.

R3 hard constraint: w_i <= rule_target_weight for all i, always.

Solver strategy: 3-leg low-dimensional → scipy SLSQP preferred;
no-scipy fallback: constrained grid search + projection (deterministic).
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from hermes_escape_top.core.contracts import (
    ConfidenceState,
    RiskState,
    SizingDecision,
    Verdict,
)


# ---------------------------------------------------------------------------
# E6: Leverage decay drag
# ---------------------------------------------------------------------------

def expected_leg_return(
    sym: str,
    leg_vol: float,
    leverage: float,
    hold_days: float,
    base_mu: float,
    cfg: Dict[str, Any],
) -> float:
    """Expected return adjusted for leverage decay (E6) and fractional Kelly (E26).

    drag ~= -0.5 * L * (L-1) * sigma_daily^2 * hold_days
    """
    sigma_daily = leg_vol / math.sqrt(252.0) if leg_vol > 0 else 0.0
    drag = 0.5 * leverage * (leverage - 1.0) * sigma_daily ** 2 * hold_days
    mu_adj = base_mu - drag
    return mu_adj


# ---------------------------------------------------------------------------
# E26: Fractional Kelly
# ---------------------------------------------------------------------------

def kelly_fraction(
    p_act: float,
    payoff_ratio: float,
    frac: float = 0.3,
    ci_width: float = 0.0,
) -> float:
    """Fractional Kelly sizing multiplier.

    Full Kelly: f* = p - (1-p)/payoff_ratio
    Fractional: frac * f* * (1 - ci_width)
    """
    if payoff_ratio <= 0 or p_act <= 0:
        return 0.0
    f_star = p_act - (1.0 - p_act) / payoff_ratio
    if f_star <= 0:
        return 0.0
    return max(0.0, min(1.0, frac * f_star * (1.0 - ci_width)))


# ---------------------------------------------------------------------------
# E12: Liquidity cap
# ---------------------------------------------------------------------------

def liquidity_cap(
    adv20: float,
    price: float,
    netliq: float,
    cfg: Dict[str, Any],
) -> float:
    """Max weight such that position can be liquidated within max_days.

    days_to_liquidate = shares / (participation * ADV20)
    => max_notional = participation * ADV20 * max_days * price
    => max_weight = max_notional / netliq
    """
    max_days = float(cfg.get("max_liquidation_days", 3))
    participation = float(cfg.get("participation_rate", 0.10))
    if adv20 <= 0 or price <= 0 or netliq <= 0:
        return 0.0
    max_notional = participation * adv20 * max_days * price
    return min(1.0, max_notional / netliq)


# ---------------------------------------------------------------------------
# E15: CPPI exposure cap
# ---------------------------------------------------------------------------

def cppi_exposure_cap(
    equity: float,
    floor: float,
    multiplier: float,
) -> float:
    """CPPI: max exposure = multiplier * (equity - floor).

    Floor is a ratcheting minimum NAV.
    """
    cushion = max(0.0, equity - floor)
    return multiplier * cushion


# ---------------------------------------------------------------------------
# E25: Downside-averse utility
# ---------------------------------------------------------------------------

def dd_averse_utility(
    w: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    dd_aversion: float,
) -> float:
    """U(w) = w'mu - dd_aversion * sqrt(w'cov w)."""
    port_ret = float(w @ mu)
    port_risk = math.sqrt(max(float(w @ cov @ w), 1e-12))
    return port_ret - dd_aversion * port_risk


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rolling_annualized_mean(ret: Any, window: int = 252) -> Optional[float]:
    """Annualized mean return over the trailing `window` observations.

    Returns None when there are fewer than 20 observations so the caller can
    fall back to the vol-based proxy rather than use a noise-dominated estimate.
    """
    try:
        r = pd.to_numeric(ret, errors="coerce").dropna().tail(window)
        if len(r) < 20:
            return None
        return float(r.mean()) * 252.0
    except Exception:
        return None


def _cvar_normal_factor(cvar_alpha: float) -> float:
    """φ(Φ⁻¹(1−α)) / (1−α) — the normal-distribution CVaR multiplier.

    CVaR_daily ≈ port_vol_daily × _cvar_normal_factor(α).
    For α=0.95: Φ⁻¹(0.05)=−1.6449, φ(1.6449)=0.1031, factor≈2.063.
    """
    p = 1.0 - cvar_alpha
    z = math.sqrt(2.0) * math.erfinv(2.0 * p - 1.0)  # Φ⁻¹(1−α), negative
    phi_z = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return phi_z / max(p, 1e-9)


# ---------------------------------------------------------------------------
# Core: optimize_targets
# ---------------------------------------------------------------------------

def optimize_targets(
    verdicts: Dict[str, Verdict],
    risk_state: RiskState,
    confidence: ConfidenceState,
    cfg: Dict[str, Any],
    leg_returns: Optional[Dict[str, Any]] = None,
    liquidity_data: Optional[Dict[str, Dict[str, float]]] = None,
) -> SizingDecision:
    """The SINGLE sizing entry point. All target weights come from here.

    Constraints applied in order (each tightens upper_bounds):
      - R3:         w_i <= verdict.rule_target_weight (ALWAYS — belt-and-suspenders)
      - Confidence: w_i <= rule_target_i × decision_confidence  (E4 data quality)
      - Risk gross: w_i <= confidence_bound_i × risk_state.gross_scaler (E5 vol/CVaR)
      - E26 Kelly:  upper_i *= kelly_fraction(p_act=conf, payoff, frac)
      - E12 Liq:    upper_i = min(upper_i, liquidity_cap(adv20, price, netliq))
      - E15 CPPI:   scale all upper_i if sum(upper) > cppi_exposure_cap
      - Vol:        sqrt(w'cov w) <= vol_budget  (explicit SLSQP constraint)
      - CVaR:       CVaR_daily(w) <= cvar_budget (normal-approx SLSQP constraint)

    Args:
        leg_returns: per-symbol pd.Series of daily returns for mu estimation.
                     When provided, uses rolling 252-day annualized mean;
                     otherwise falls back to vol-based proxy.
        liquidity_data: per-symbol dict with keys 'adv20', 'price', 'netliq'
                        for E12 liquidity cap. Omit to skip E12.
    """
    sizing_cfg = cfg.get("sizing", cfg)
    dd_aversion = float(sizing_cfg.get("dd_aversion", 3.0))
    leverage_map = sizing_cfg.get("leverage_L", {})

    syms = sorted(verdicts.keys())
    n = len(syms)
    if n == 0:
        return _empty_decision(confidence)

    # ── Upper bounds: R3 → confidence → risk gross ────────────────────────────
    rule_targets = np.array([verdicts[s].rule_target_weight for s in syms])
    conf_factor = max(0.0, min(1.0, confidence.decision_confidence))
    risk_gross_factor = max(0.0, min(1.0, float(risk_state.gross_scaler)))
    upper_bounds = rule_targets * conf_factor * risk_gross_factor

    # ── E26: Fractional Kelly cap ─────────────────────────────────────────────
    kelly_cfg = sizing_cfg.get("kelly", {})
    if kelly_cfg.get("enabled", True):
        kf = kelly_fraction(
            p_act=conf_factor,
            payoff_ratio=float(kelly_cfg.get("payoff_ratio", 2.0)),
            frac=float(kelly_cfg.get("frac", 0.3)),
            ci_width=float(kelly_cfg.get("ci_width", 0.0)),
        )
        if kf > 0:
            upper_bounds = upper_bounds * kf

    # ── E12: Per-leg liquidity cap ─────────────────────────────────────────────
    if liquidity_data:
        liq_cfg = sizing_cfg.get("liquidity", {})
        for i, s in enumerate(syms):
            liq = liquidity_data.get(s, {})
            adv20 = float(liq.get("adv20", float("inf")))
            price = float(liq.get("price", 1.0))
            netliq = float(liq.get("netliq", 1.0))
            if math.isfinite(adv20) and adv20 > 0:
                liq_cap_val = liquidity_cap(adv20, price, netliq, liq_cfg)
                upper_bounds[i] = min(upper_bounds[i], liq_cap_val)

    # ── E15: CPPI portfolio-level gross exposure cap ───────────────────────────
    cppi_cfg = sizing_cfg.get("cppi", {})
    if cppi_cfg.get("enabled", False):
        equity = float(cppi_cfg.get("equity", 1.0))
        floor = equity * float(cppi_cfg.get("floor_ratio", 0.8))
        multiplier = float(cppi_cfg.get("multiplier", 3.0))
        max_gross = cppi_exposure_cap(equity, floor, multiplier)
        total_target = float(np.sum(upper_bounds))
        if total_target > 0 and max_gross < total_target:
            upper_bounds = upper_bounds * (max_gross / total_target)

    # Ensure non-negative after all caps
    upper_bounds = np.clip(upper_bounds, 0.0, None)

    # ── Expected returns: rolling historical mean (option A) ──────────────────
    # When leg_returns are provided the optimizer uses the actual trailing
    # 252-day annualized mean. Without them the vol-proxy (base_mu = 4×vol_i)
    # makes every leg push to its upper bound — SLSQP only adds value when
    # the vol or CVaR budget is binding. Providing leg_returns enables the
    # optimizer to meaningfully differentiate allocations across legs.
    mu = np.zeros(n)
    for i, s in enumerate(syms):
        lev = float(leverage_map.get(s, 1.0))
        vol_i = risk_state.leg_vol.get(s, 0.2)
        if leg_returns is not None and s in leg_returns:
            hist_mu = _rolling_annualized_mean(leg_returns[s])
            base_mu = hist_mu if hist_mu is not None else vol_i * max(2.0, dd_aversion + 1.0)
        else:
            base_mu = vol_i * max(2.0, dd_aversion + 1.0)
        mu[i] = expected_leg_return(s, vol_i, lev, 20.0, base_mu, sizing_cfg)

    # ── Covariance and budgets (single source: RiskState) ─────────────────────
    cov = risk_state.cov
    if cov.shape[0] != n:
        cov = np.eye(n) * 0.04
    vol_budget = risk_state.vol_budget
    cvar_budget = risk_state.cvar_budget
    cvar_alpha = float(sizing_cfg.get("cvar_alpha", 0.95))

    # ── Solve ─────────────────────────────────────────────────────────────────
    try:
        w_opt = _solve_slsqp(mu, cov, upper_bounds, vol_budget, dd_aversion,
                             cvar_budget, cvar_alpha)
    except Exception:
        w_opt = _solve_grid(mu, cov, upper_bounds, vol_budget, dd_aversion, n)

    # R3 hard clamp (belt-and-suspenders)
    for i in range(n):
        w_opt[i] = min(w_opt[i], rule_targets[i])
        w_opt[i] = max(0.0, w_opt[i])

    # Binding constraint detection
    binding = {}
    for i, s in enumerate(syms):
        if w_opt[i] <= 1e-8:
            binding[s] = "ZERO"
        elif abs(w_opt[i] - rule_targets[i]) < 1e-6:
            binding[s] = "R3_RULE"
        elif risk_gross_factor < 1.0 and abs(w_opt[i] - upper_bounds[i]) < 1e-6:
            binding[s] = "RISK_GROSS"
        elif abs(w_opt[i] - upper_bounds[i]) < 1e-6:
            binding[s] = "CONFIDENCE"
        else:
            port_vol = math.sqrt(max(float(w_opt @ cov @ w_opt), 1e-12))
            if port_vol >= vol_budget * 0.99:
                binding[s] = "VOL_BUDGET"
            else:
                binding[s] = "NONE"

    # Execution plan (E8: hard valve → execute_now, else sliced)
    exec_slices = int(sizing_cfg.get("exec_slices", 3))
    execution_plan = []
    for i, s in enumerate(syms):
        v = verdicts[s]
        is_hard_valve = len(v.hard_valve_hits) > 0
        execution_plan.append({
            "symbol": s,
            "target_weight": round(float(w_opt[i]), 6),
            "mode": "execute_now" if is_hard_valve else f"twap_{exec_slices}_slices",
            "hard_valve_hits": v.hard_valve_hits,
        })

    # Utility
    utility = dd_averse_utility(w_opt, mu, cov, dd_aversion)

    notes: List[str] = []
    if confidence.mode == "DEGRADED":
        notes.append("confidence DEGRADED; weights shrunk significantly")
    if risk_gross_factor < 1.0:
        notes.append(f"risk gross scaler applied: {risk_gross_factor:.3f}")
    if risk_state.binding != "NONE":
        notes.append(f"risk binding: {risk_state.binding}")

    return SizingDecision(
        target_weights={syms[i]: round(float(w_opt[i]), 6) for i in range(n)},
        binding_constraint=binding,
        execution_plan=execution_plan,
        expected_utility=round(float(utility), 6),
        confidence_applied=round(float(conf_factor), 6),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------

def _solve_slsqp(
    mu: np.ndarray,
    cov: np.ndarray,
    upper: np.ndarray,
    vol_budget: float,
    dd_aversion: float,
    cvar_budget: float = 0.08,
    cvar_alpha: float = 0.95,
) -> np.ndarray:
    """scipy SLSQP solver with explicit vol + CVaR constraints.

    CVaR uses the normal approximation:
        CVaR_daily(w) ≈ port_vol_annual(w) / √252 × φ(Φ⁻¹(1−α)) / (1−α)
    This is exact under normality and conservative (underestimates fat-tail CVaR),
    making the feasible set a superset of the true CVaR-feasible set — acceptable
    as a constraint because the upper_bounds already encode the historical-sim
    CVaR scaler from RiskState.
    """
    from scipy.optimize import minimize

    n = len(mu)
    cvar_factor = _cvar_normal_factor(cvar_alpha)

    def neg_utility(w):
        return -(float(w @ mu) - dd_aversion * math.sqrt(max(float(w @ cov @ w), 1e-12)))

    def vol_constraint(w):
        return vol_budget - math.sqrt(max(float(w @ cov @ w), 1e-12))

    def cvar_constraint(w):
        port_vol_ann = math.sqrt(max(float(w @ cov @ w), 1e-12))
        cvar_approx = port_vol_ann / math.sqrt(252.0) * cvar_factor
        return cvar_budget - cvar_approx

    bounds = [(0.0, float(upper[i])) for i in range(n)]
    x0 = upper * 0.5
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Values in x were outside bounds during a minimize step, clipping to bounds",
            category=RuntimeWarning,
        )
        result = minimize(
            neg_utility,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=[
                {"type": "ineq", "fun": vol_constraint},
                {"type": "ineq", "fun": cvar_constraint},
            ],
            options={"maxiter": 200, "ftol": 1e-10},
        )
    if result.success:
        return np.clip(result.x, 0.0, upper)
    # Fallback: scale upper × 0.3, then enforce both vol and CVaR feasibility.
    w_fallback = np.clip(upper * 0.3, 0.0, upper)
    port_vol_ann = math.sqrt(max(float(w_fallback @ cov @ w_fallback), 1e-12))
    if port_vol_ann > vol_budget:
        w_fallback = w_fallback * (vol_budget / port_vol_ann)
        port_vol_ann = vol_budget
    cvar_approx = port_vol_ann / math.sqrt(252.0) * cvar_factor
    if cvar_approx > cvar_budget:
        w_fallback = w_fallback * (cvar_budget / cvar_approx)
    return w_fallback


def _solve_grid(
    mu: np.ndarray,
    cov: np.ndarray,
    upper: np.ndarray,
    vol_budget: float,
    dd_aversion: float,
    n: int,
    grid_steps: int = 11,
) -> np.ndarray:
    """Deterministic grid search fallback for low-dimensional problems."""
    best_u = -1e18
    best_w = np.zeros(n)

    grids = [np.linspace(0, float(upper[i]), grid_steps) for i in range(n)]

    if n == 1:
        for w0 in grids[0]:
            w = np.array([w0])
            vol = math.sqrt(max(float(w @ cov @ w), 1e-12))
            if vol <= vol_budget:
                u = dd_averse_utility(w, mu, cov, dd_aversion)
                if u > best_u:
                    best_u = u
                    best_w = w.copy()
    elif n == 2:
        for w0 in grids[0]:
            for w1 in grids[1]:
                w = np.array([w0, w1])
                vol = math.sqrt(max(float(w @ cov @ w), 1e-12))
                if vol <= vol_budget:
                    u = dd_averse_utility(w, mu, cov, dd_aversion)
                    if u > best_u:
                        best_u = u
                        best_w = w.copy()
    elif n == 3:
        for w0 in grids[0]:
            for w1 in grids[1]:
                for w2 in grids[2]:
                    w = np.array([w0, w1, w2])
                    vol = math.sqrt(max(float(w @ cov @ w), 1e-12))
                    if vol <= vol_budget:
                        u = dd_averse_utility(w, mu, cov, dd_aversion)
                        if u > best_u:
                            best_u = u
                            best_w = w.copy()
    else:
        # n > 3: grid is too expensive; fall back to scaled upper bounds.
        best_w = np.clip(upper * 0.3, 0.0, upper)
        vol_fb = math.sqrt(max(float(best_w @ cov @ best_w), 1e-12))
        if vol_fb > vol_budget:
            best_w = best_w * (vol_budget / vol_fb)

    return best_w


def _empty_decision(confidence: ConfidenceState) -> SizingDecision:
    return SizingDecision(
        target_weights={},
        binding_constraint={},
        execution_plan=[],
        expected_utility=0.0,
        confidence_applied=round(float(confidence.decision_confidence), 6),
        notes=["no symbols to size"],
    )
