"""SizingOptimizer -- the SINGLE sizing entry point for the entire system.

Absorbs E6/E8/E12/E15/E25/E26/E27. Replaces all scaler multiplication chains.
All target weights come from optimize_targets(); no ad-hoc scaler chaining.

R3 hard constraint: w_i <= rule_target_weight for all i, always.

Solver strategy: 3-leg low-dimensional → scipy SLSQP preferred;
no-scipy fallback: constrained grid search + projection (deterministic).
"""

from __future__ import annotations

import itertools
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
    adv20_shares: float,
    price: float,
    netliq: float,
    cfg: Dict[str, Any],
) -> float:
    """Max weight such that position can be liquidated within max_days.

    `adv20_shares` is average daily share volume. If the caller already has
    dollar ADV, it must pass that through `liquidity_data["adv20_notional"]`
    so the optimizer does not multiply by price twice.

    days_to_liquidate = shares / (participation * ADV20_shares)
    => max_notional = participation * ADV20_shares * max_days * price
    => max_weight = max_notional / netliq
    """
    max_days = float(cfg.get("max_liquidation_days", 3))
    participation = float(cfg.get("participation_rate", 0.10))
    if adv20_shares <= 0 or price <= 0 or netliq <= 0:
        return 0.0
    max_notional = participation * adv20_shares * max_days * price
    return min(1.0, max_notional / netliq)


def liquidity_notional_cap(
    adv20_notional: float,
    netliq: float,
    cfg: Dict[str, Any],
) -> float:
    """Liquidity cap when ADV20 is already expressed in dollars."""
    max_days = float(cfg.get("max_liquidation_days", 3))
    participation = float(cfg.get("participation_rate", 0.10))
    if adv20_notional <= 0 or netliq <= 0:
        return 0.0
    max_notional = participation * adv20_notional * max_days
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


def _shrink_expected_returns(
    raw_mu: Dict[str, float],
    shrink: float,
) -> Dict[str, float]:
    """James-Stein-style shrinkage of per-leg means toward the cross-sectional mean.

    Trailing-mean estimates of expected return are notoriously noise-dominated
    (the "mean is hard to estimate" problem): with ~252 daily observations the
    standard error of an annualized mean swamps the signal. Shrinking each leg
    toward the cross-sectional grand mean trades a little bias for a large
    variance reduction, so the optimizer differentiates legs on durable
    differences rather than estimation noise.

    shrunk_i = shrink * grand_mean + (1 - shrink) * raw_mu_i
    """
    if not raw_mu:
        return {}
    shrink = max(0.0, min(1.0, shrink))
    grand = sum(raw_mu.values()) / len(raw_mu)
    return {s: shrink * grand + (1.0 - shrink) * m for s, m in raw_mu.items()}


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
      - Risk gross: w_i <= confidence_bound_i × risk_state.gross_scaler
                    (E5 — gross_scaler = min(vol_scaler, cvar_scaler), so BOTH the
                    vol budget and the historical-sim CVaR budget are already
                    encoded here; the optimizer does not re-impose CVaR.)
      - E26 Kelly:  upper_i *= kelly_fraction(...)  — OFF by default; opt-in only,
                    and only with a calibrated win probability (see kelly cfg).
      - E12 Liq:    upper_i = min(upper_i, liquidity_cap(adv20, price, netliq))
      - E15 CPPI:   scale all upper_i if sum(upper) > cppi_exposure_cap
      - Vol:        sqrt(w'cov w) <= vol_budget  (explicit SLSQP constraint)

    Args:
        leg_returns: per-symbol pd.Series of daily returns. Only consulted when
                     sizing.mu_mode == "historical_tilt" (opt-in); under the
                     default "proxy" mode the vol-based proxy is used.
        liquidity_data: per-symbol dict with keys 'adv20_shares' or
                        'adv20_notional', plus 'price' and 'netliq', for E12
                        liquidity cap. Omit to skip E12.
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
    # OFF by default. Kelly's p_act is the probability the position WINS — it must
    # come from a calibrated probability model (FactorLab score→probability), NOT
    # from decision_confidence (a data-quality composite). Feeding confidence in as
    # p_act is a category error that silently slashes every position ~75-90%.
    # Enable only once a real p_act source is wired and pass it via kelly.p_act.
    kelly_cfg = sizing_cfg.get("kelly", {})
    if kelly_cfg.get("enabled", False):
        p_act = kelly_cfg.get("p_act", None)
        if p_act is None:
            raise ValueError(
                "kelly.enabled=True requires a calibrated kelly.p_act (win "
                "probability); decision_confidence must not be used as p_act."
            )
        kf = kelly_fraction(
            p_act=float(p_act),
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
            price = float(liq.get("price", 1.0))
            netliq = float(liq.get("netliq", 1.0))
            adv20_notional = float(liq.get("adv20_notional", float("nan")))
            adv20_shares = float(liq.get("adv20_shares", liq.get("adv20", float("inf"))))
            if math.isfinite(adv20_notional) and adv20_notional > 0:
                liq_cap_val = liquidity_notional_cap(adv20_notional, netliq, liq_cfg)
                upper_bounds[i] = min(upper_bounds[i], liq_cap_val)
            elif math.isfinite(adv20_shares) and adv20_shares > 0:
                liq_cap_val = liquidity_cap(adv20_shares, price, netliq, liq_cfg)
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

    # ── Expected returns ──────────────────────────────────────────────────────
    # mu_mode (default "proxy"):
    #   "proxy"           base_mu_i = vol_i × max(2, dd+1). This keeps
    #                     mu_i > dd_aversion × vol_i so the downside-averse
    #                     utility never imposes an absolute Sharpe>dd hurdle (no
    #                     asset clears Sharpe>3); the optimizer then performs
    #                     risk-budgeted allocation up to the upper bounds — the
    #                     behaviour validated in Phase II/III. The hold/no-hold
    #                     decision belongs to the scoring/verdict layer (which
    #                     sets rule_target_weight), NOT to this optimizer.
    #   "historical_tilt" opt-in, BACKTEST-GATED. Keeps base_mu >= proxy (so the
    #                     posture is preserved) but adds a bounded rank tilt from
    #                     the cross-sectionally shrunk trailing 252d mean, so the
    #                     optimizer favours higher-return legs WHEN the vol budget
    #                     binds. A raw trailing mean must NOT be used directly: it
    #                     is mostly estimation noise and, against dd=3, collapses
    #                     every high-vol leg to zero (false liquidation).
    mu_mode = str(sizing_cfg.get("mu_mode", "proxy"))
    proxies = {s: risk_state.leg_vol.get(s, 0.2) * max(2.0, dd_aversion + 1.0) for s in syms}

    tilt: Dict[str, float] = {s: 0.0 for s in syms}
    if mu_mode == "historical_tilt" and leg_returns is not None:
        shrink = float(sizing_cfg.get("mu_shrink", 0.5))
        tilt_cap = float(sizing_cfg.get("mu_tilt_cap", 0.5))
        raw_mu = {s: _rolling_annualized_mean(leg_returns[s])
                  for s in syms if s in leg_returns}
        raw_mu = {s: v for s, v in raw_mu.items() if v is not None}
        shrunk = _shrink_expected_returns(raw_mu, shrink)
        if len(shrunk) >= 2:
            lo, hi = min(shrunk.values()), max(shrunk.values())
            span = hi - lo
            if span > 1e-12:
                # rank_frac in [0,1]; worst leg gets +0, best gets +tilt_cap
                for s, v in shrunk.items():
                    tilt[s] = tilt_cap * (v - lo) / span

    mu = np.zeros(n)
    for i, s in enumerate(syms):
        lev = float(leverage_map.get(s, 1.0))
        vol_i = risk_state.leg_vol.get(s, 0.2)
        base_mu = proxies[s] * (1.0 + tilt[s])   # >= proxy, preserves posture
        mu[i] = expected_leg_return(s, vol_i, lev, 20.0, base_mu, sizing_cfg)

    # ── Covariance and budget (single source: RiskState) ──────────────────────
    # CVaR is NOT re-imposed here: risk_state.gross_scaler already equals
    # min(vol_scaler, cvar_scaler) from the historical-sim CVaR in RiskEngine,
    # so the CVaR budget is encoded in upper_bounds. A second normal-approx CVaR
    # constraint would be both redundant and wrong (normal approx understates the
    # fat tails of leveraged ETFs). Vol is the only explicit solver constraint.
    cov = risk_state.cov
    if cov.shape[0] != n:
        cov = np.eye(n) * 0.04
    vol_budget = risk_state.vol_budget

    # ── Solve ─────────────────────────────────────────────────────────────────
    try:
        w_opt = _solve_slsqp(mu, cov, upper_bounds, vol_budget, dd_aversion)
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
) -> np.ndarray:
    """scipy SLSQP solver with an explicit annualized-vol constraint.

    CVaR is intentionally not a solver constraint: it is already enforced upstream
    via upper_bounds (risk_state.gross_scaler embeds the historical-sim CVaR
    scaler). See optimize_targets for the rationale.
    """
    from scipy.optimize import minimize

    n = len(mu)

    def neg_utility(w):
        return -(float(w @ mu) - dd_aversion * math.sqrt(max(float(w @ cov @ w), 1e-12)))

    def vol_constraint(w):
        return vol_budget - math.sqrt(max(float(w @ cov @ w), 1e-12))

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
            constraints=[{"type": "ineq", "fun": vol_constraint}],
            options={"maxiter": 200, "ftol": 1e-10},
        )
    if result.success:
        return np.clip(result.x, 0.0, upper)
    # Fallback: scale upper × 0.3, then enforce vol feasibility.
    w_fallback = np.clip(upper * 0.3, 0.0, upper)
    port_vol_ann = math.sqrt(max(float(w_fallback @ cov @ w_fallback), 1e-12))
    if port_vol_ann > vol_budget:
        w_fallback = w_fallback * (vol_budget / port_vol_ann)
    return w_fallback


def _solve_grid(
    mu: np.ndarray,
    cov: np.ndarray,
    upper: np.ndarray,
    vol_budget: float,
    dd_aversion: float,
    n: int,
    grid_steps: int = 11,
    max_points: int = 50_000,
) -> np.ndarray:
    """Deterministic grid search fallback for any dimension.

    Generalized via itertools.product so n > 3 genuinely searches instead of
    silently returning a scaled upper bound. grid_steps is reduced when the
    full grid would exceed max_points, keeping the fallback bounded. The
    all-zero weight is always feasible (vol 0 ≤ budget, utility 0), so a feasible
    solution always exists.
    """
    while grid_steps > 2 and grid_steps ** n > max_points:
        grid_steps -= 1

    grids = [np.linspace(0.0, float(upper[i]), grid_steps) for i in range(n)]
    best_u = -1e18
    best_w = np.zeros(n)
    for combo in itertools.product(*grids):
        w = np.array(combo, dtype=float)
        vol = math.sqrt(max(float(w @ cov @ w), 1e-12))
        if vol <= vol_budget:
            u = dd_averse_utility(w, mu, cov, dd_aversion)
            if u > best_u:
                best_u = u
                best_w = w.copy()
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
