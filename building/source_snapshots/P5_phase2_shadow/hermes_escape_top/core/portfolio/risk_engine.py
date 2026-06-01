"""RiskEngine -- the single source of covariance for the entire system.

Absorbs E4/E5/E11/E13/E14 from the integration architecture.
All downstream vol/CVaR/risk-contribution/factor-exposure quantities
derive from one shared cov matrix built here.

Dependencies: numpy, pandas (required); scipy/sklearn optional with fallback.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from hermes_escape_top.core.contracts import RiskState


# ---------------------------------------------------------------------------
# E5: HAR-RV volatility forecast
# ---------------------------------------------------------------------------

def har_rv_forecast(returns: pd.Series, cfg: Dict[str, Any]) -> float:
    """Heterogeneous Autoregressive Realized Variance forecast (annualized vol).

    RV_{t+1} = b0 + b_d * RV_d + b_w * mean(RV,5) + b_m * mean(RV,22)

    Falls back to EWMA if insufficient samples for OLS fit.
    """
    min_obs = int(cfg.get("har_min_obs", 66))
    ewma_lambda = float(cfg.get("ewma_lambda", 0.94))
    r = _clean_return_series(returns).values

    if len(r) < min_obs:
        return _ewma_vol(r, ewma_lambda)

    rv_daily = r ** 2
    rv_w = _rolling_mean(rv_daily, 5)
    rv_m = _rolling_mean(rv_daily, 22)

    valid_start = 22
    y = rv_daily[valid_start:]
    x_d = rv_daily[valid_start - 1 : -1]
    x_w = rv_w[valid_start - 1 : -1]
    x_m = rv_m[valid_start - 1 : -1]

    n = len(y)
    if n < 30:
        return _ewma_vol(r, ewma_lambda)

    X = np.column_stack([np.ones(n), x_d[:n], x_w[:n], x_m[:n]])
    try:
        betas, _, _, _ = np.linalg.lstsq(X, y[:n], rcond=None)
    except np.linalg.LinAlgError:
        return _ewma_vol(r, ewma_lambda)

    rv_d_last = rv_daily[-1]
    rv_w_last = float(np.mean(rv_daily[-5:]))
    rv_m_last = float(np.mean(rv_daily[-22:]))
    rv_hat = float(betas[0] + betas[1] * rv_d_last + betas[2] * rv_w_last + betas[3] * rv_m_last)
    rv_hat = max(rv_hat, 1e-10)
    return float(np.sqrt(252.0 * rv_hat))


def _ewma_vol(r: np.ndarray, lam: float) -> float:
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return 0.0
    var = r[0] ** 2
    for ret in r[1:]:
        var = lam * var + (1.0 - lam) * ret ** 2
    return float(np.sqrt(252.0 * max(var, 1e-10)))


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    cs = np.cumsum(arr)
    cs = np.insert(cs, 0, 0.0)
    out = np.empty_like(arr)
    for i in range(len(arr)):
        start = max(0, i - window + 1)
        out[i] = (cs[i + 1] - cs[start]) / (i - start + 1)
    return out


# ---------------------------------------------------------------------------
# E11: EWMA correlation forecast + Ledoit-Wolf shrinkage
# ---------------------------------------------------------------------------

def ewma_corr_forecast(returns_df: pd.DataFrame, lam: float = 0.94) -> np.ndarray:
    """EWMA-estimated correlation matrix from joint returns."""
    clean = _clean_returns_df(returns_df)
    R = clean.values.astype(float)
    n, k = R.shape
    if n < 2 or k < 2:
        return np.eye(k)
    cov = np.zeros((k, k))
    for t in range(n):
        cov = lam * cov + (1.0 - lam) * np.outer(R[t], R[t])
    d = np.sqrt(np.diag(cov))
    d = np.where(d < 1e-12, 1.0, d)
    corr = cov / np.outer(d, d)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(corr, 1.0)
    return corr


def ledoit_wolf_shrink(corr: np.ndarray, n_obs: int) -> np.ndarray:
    """Ledoit-Wolf shrinkage toward identity (sklearn preferred, handwritten fallback)."""
    corr = _finite_square_matrix(corr)
    try:
        from sklearn.covariance import LedoitWolf
        lw = LedoitWolf(assume_centered=True)
        lw.fit(np.eye(corr.shape[0]))
        shrinkage = lw.shrinkage_
    except (ImportError, Exception):
        shrinkage = _lw_shrinkage_manual(corr, n_obs)
    target = np.eye(corr.shape[0])
    shrunk = (1.0 - shrinkage) * corr + shrinkage * target
    np.fill_diagonal(shrunk, 1.0)
    return shrunk


def _lw_shrinkage_manual(corr: np.ndarray, n_obs: int) -> float:
    k = corr.shape[0]
    if k <= 1 or n_obs <= 1:
        return 1.0
    off_diag = corr.copy()
    np.fill_diagonal(off_diag, 0.0)
    sum_sq = float(np.sum(off_diag ** 2))
    rho = sum_sq / (k * (k - 1))
    shrinkage = min(1.0, max(0.0, rho / max(n_obs, 1)))
    return shrinkage


# ---------------------------------------------------------------------------
# E4: Downside correlation
# ---------------------------------------------------------------------------

def downside_corr(returns_df: pd.DataFrame, q: float = 0.10) -> np.ndarray:
    """Exceedance (left-tail) correlation: condition on portfolio below q-quantile."""
    clean = _clean_returns_df(returns_df)
    R = clean.values.astype(float)
    n, k = R.shape
    if n < 10 or k < 2:
        return np.eye(k)
    port_ret = R.mean(axis=1)
    threshold = np.quantile(port_ret, q)
    mask = port_ret <= threshold
    if mask.sum() < 5:
        return np.eye(k)
    tail = R[mask]
    corr = np.corrcoef(tail.T)
    if not np.all(np.isfinite(corr)):
        return np.eye(k)
    # Tail samples are intentionally small and can understate common risk by
    # chance. Use full-sample correlation as a conservative floor for each
    # pair so downside risk never looks safer than the ordinary regime.
    full_corr = np.corrcoef(R.T)
    if np.all(np.isfinite(full_corr)):
        corr = np.maximum(corr, full_corr)
    np.fill_diagonal(corr, 1.0)
    return corr


# ---------------------------------------------------------------------------
# E4: Portfolio CVaR
# ---------------------------------------------------------------------------

def portfolio_cvar(
    weights: np.ndarray,
    returns_df: pd.DataFrame,
    alpha: float = 0.95,
    method: str = "historical",
) -> float:
    """Portfolio CVaR (expected shortfall).

    Historical: mean of portfolio returns below VaR.
    Cornish-Fisher fallback when samples are scarce.
    """
    clean = _clean_returns_df(returns_df)
    R = clean.values.astype(float)
    n, k = R.shape
    w = np.asarray(weights, dtype=float).flatten()[:k]
    w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
    if n < 20 or k < 1:
        return 0.0
    # On macOS Accelerate, F-contiguous 2-D arrays can emit false-positive
    # matmul RuntimeWarnings even when all inputs and outputs are finite.
    # np.dot avoids that BLAS warning path for this vector product.
    port_ret = np.dot(R, w)
    port_ret = port_ret[np.isfinite(port_ret)]
    if len(port_ret) < 20:
        return 0.0
    var_level = np.quantile(port_ret, 1.0 - alpha)

    if method == "historical":
        tail = port_ret[port_ret <= var_level]
        if len(tail) == 0:
            return float(var_level)
        return float(np.mean(tail))
    else:
        mu = float(np.mean(port_ret))
        sigma = float(np.std(port_ret, ddof=1))
        if sigma < 1e-12:
            return 0.0
        skew = float(_skewness(port_ret))
        kurt = float(_kurtosis(port_ret))
        z = _cornish_fisher_quantile(1.0 - alpha, skew, kurt)
        return mu + sigma * z


def _skewness(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 3:
        return 0.0
    m = arr.mean()
    s = arr.std(ddof=1)
    if s < 1e-12:
        return 0.0
    return float(np.mean(((arr - m) / s) ** 3) * n / ((n - 1) * (n - 2)) * n)


def _kurtosis(arr: np.ndarray) -> float:
    n = len(arr)
    if n < 4:
        return 3.0
    m = arr.mean()
    s = arr.std(ddof=1)
    if s < 1e-12:
        return 3.0
    return float(np.mean(((arr - m) / s) ** 4))


def _cornish_fisher_quantile(p: float, skew: float, kurt: float) -> float:
    from math import erfinv
    z = math.sqrt(2.0) * erfinv(2.0 * p - 1.0)
    cf = (z
          + (z ** 2 - 1.0) * skew / 6.0
          + (z ** 3 - 3.0 * z) * (kurt - 3.0) / 24.0
          - (2.0 * z ** 3 - 5.0 * z) * skew ** 2 / 36.0)
    return cf


# ---------------------------------------------------------------------------
# E13: Marginal Risk Contribution
# ---------------------------------------------------------------------------

def risk_contribution(weights: np.ndarray, cov: np.ndarray) -> Dict[str, float]:
    """Per-leg risk contribution: RC_i = w_i * (cov @ w)_i / portfolio_vol.

    Sum of RC equals portfolio_vol.
    """
    w = np.asarray(weights, dtype=float).flatten()
    w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
    cov = _finite_square_matrix(cov, size=len(w))
    port_var = float(w @ cov @ w)
    port_vol = math.sqrt(max(port_var, 1e-12))
    mcr = cov @ w / port_vol
    rc = w * mcr
    return {f"leg_{i}": float(rc[i]) for i in range(len(w))}


# ---------------------------------------------------------------------------
# E14: Factor exposure (book-level)
# ---------------------------------------------------------------------------

def book_factor_beta(
    leg_returns: Dict[str, pd.Series],
    factor_returns: Dict[str, pd.Series],
    weights: Dict[str, float],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    """Per-leg beta to each factor + aggregated book-level exposure.

    Returns (leg_betas, book_exposure) where:
      leg_betas[sym][factor] = beta_i_f
      book_exposure[factor] = sum(w_i * beta_i_f)
    """
    leg_betas: Dict[str, Dict[str, float]] = {}
    book_exposure: Dict[str, float] = {f: 0.0 for f in factor_returns}

    for sym, ret in leg_returns.items():
        betas: Dict[str, float] = {}
        for fname, fret in factor_returns.items():
            aligned = pd.concat([ret, fret], axis=1).dropna()
            if len(aligned) < 30:
                betas[fname] = 0.0
                continue
            y = aligned.iloc[:, 0].values
            x = aligned.iloc[:, 1].values
            x_dm = x - x.mean()
            var_x = float(np.dot(x_dm, x_dm))
            if var_x < 1e-12:
                betas[fname] = 0.0
                continue
            betas[fname] = float(np.dot(x_dm, y - y.mean()) / var_x)
        leg_betas[sym] = betas
        w_i = weights.get(sym, 0.0)
        for fname in factor_returns:
            book_exposure[fname] += w_i * betas.get(fname, 0.0)

    return leg_betas, book_exposure


# ---------------------------------------------------------------------------
# Main assembly: build_risk_state
# ---------------------------------------------------------------------------

def build_risk_state(
    leg_returns: Dict[str, pd.Series],
    target_weights: Dict[str, float],
    factor_returns: Optional[Dict[str, pd.Series]],
    cfg: Dict[str, Any],
) -> RiskState:
    """Assemble the full RiskState from leg returns and config.

    This is the SINGLE entry point for all risk-related quantities.
    All downstream code must use the cov/corr/vol from this state.
    """
    risk_cfg = cfg.get("risk_engine", cfg)
    min_periods = int(risk_cfg.get("min_periods", 40))
    ewma_lambda = float(risk_cfg.get("ewma_lambda", 0.94))
    vol_budget = float(risk_cfg.get("vol_budget_annual", 0.35))
    cvar_budget = float(risk_cfg.get("cvar_budget", 0.08))
    extreme_corr_penalty = float(risk_cfg.get("extreme_corr_penalty", 0.70))
    downside_q = float(risk_cfg.get("downside_q", 0.10))
    cvar_alpha = float(risk_cfg.get("cvar_alpha", 0.95))
    extreme_pctl = float(risk_cfg.get("corr_regime_extreme_pctl", 92))
    elevated_pctl = float(risk_cfg.get("corr_regime_elevated_pctl", 80))
    concentration_cap = risk_cfg.get("concentration_cap", {})

    explain: List[str] = []

    clean_leg_returns = {s: _clean_return_series(r) for s, r in leg_returns.items()}
    syms = sorted(clean_leg_returns.keys())
    legs_reported = [s for s in syms if len(clean_leg_returns[s]) >= min_periods]
    legs_used = [s for s in legs_reported if target_weights.get(s, 0.0) > 0]

    if len(legs_reported) < 2:
        explain.append("insufficient legs for risk estimation; using identity fallback")
        return _fallback_risk_state(syms, target_weights, vol_budget, cvar_budget, explain)

    # Marginal vol per leg (HAR-RV preferred, EWMA fallback)
    leg_vol: Dict[str, float] = {}
    for s in legs_reported:
        leg_vol[s] = _finite_float(har_rv_forecast(clean_leg_returns[s], risk_cfg), 0.2)

    # Correlation: EWMA -> Ledoit-Wolf shrinkage
    joint_df = _clean_returns_df(pd.DataFrame({s: clean_leg_returns[s] for s in legs_reported}))
    n_obs = len(joint_df)

    if n_obs < min_periods:
        explain.append(f"joint sample {n_obs} < {min_periods}; conservative fallback")
        corr = np.eye(len(legs_reported))
        corr_regime = "UNKNOWN"
    else:
        raw_corr = ewma_corr_forecast(joint_df, ewma_lambda)
        corr = _finite_square_matrix(ledoit_wolf_shrink(raw_corr, n_obs), size=len(legs_reported))
        corr_regime = "NORMAL"

    # Covariance: D R D
    D = np.diag([leg_vol.get(s, 0.0) for s in legs_reported])
    cov = _finite_square_matrix(D @ corr @ D, size=len(legs_reported))

    # Downside correlation + corr regime
    dc = downside_corr(joint_df, downside_q) if n_obs >= min_periods else np.eye(len(legs_reported))
    if n_obs >= min_periods:
        dc_mean = _off_diag_mean(dc)
        corr_mean = _off_diag_mean(corr)
        if dc_mean > 0:
            ratio_pctl = dc_mean / max(corr_mean, 1e-6) * 100.0
            if ratio_pctl >= extreme_pctl:
                corr_regime = "EXTREME"
            elif ratio_pctl >= elevated_pctl:
                corr_regime = "ELEVATED"

    # Portfolio vol
    w_vec = np.array([target_weights.get(s, 0.0) for s in legs_reported])
    w_vec = np.nan_to_num(w_vec.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    port_var = float(w_vec @ cov @ w_vec)
    if not math.isfinite(port_var):
        port_var = 0.0
    port_vol = math.sqrt(max(port_var, 1e-12))

    # CVaR
    cvar_val = portfolio_cvar(w_vec, joint_df, cvar_alpha)

    # Scalers
    vol_scaler = min(1.0, vol_budget / max(port_vol, 1e-12))
    cvar_scaler = min(1.0, cvar_budget / max(abs(cvar_val), 1e-12))
    gross = min(vol_scaler, cvar_scaler)
    if corr_regime == "EXTREME":
        gross *= extreme_corr_penalty
        explain.append(f"EXTREME corr regime; penalty {extreme_corr_penalty}")
    gross = min(1.0, max(0.0, gross))

    # Risk contributions
    rc = risk_contribution(w_vec, cov)
    rc_named = {legs_reported[i]: v for i, (_, v) in enumerate(sorted(rc.items()))}

    # Factor betas
    if factor_returns:
        fb, be = book_factor_beta(
            {s: clean_leg_returns[s] for s in legs_reported},
            {s: _clean_return_series(r) for s, r in factor_returns.items()},
            {s: target_weights.get(s, 0.0) for s in legs_reported},
        )
    else:
        fb, be = {}, {}

    # Binding constraint
    binding = "NONE"
    if gross < 1.0:
        if vol_scaler <= cvar_scaler:
            binding = "VOL"
        else:
            binding = "CVAR"
    if corr_regime == "EXTREME":
        binding = "EXTREME_CORR"

    for sym, cap in concentration_cap.items():
        w_sym = target_weights.get(sym, 0.0)
        if w_sym > cap:
            binding = "CONCENTRATION"
            explain.append(f"{sym} weight {w_sym:.2%} exceeds cap {cap:.2%}")

    estimator_meta = {
        "n_obs": n_obs,
        "vol_model": "har_rv" if n_obs >= min_periods else "ewma",
        "corr_model": "ewma_lw",
        "shrinkage_applied": True,
    }

    return RiskState(
        cov=cov,
        corr=corr,
        downside_corr=dc,
        leg_vol=leg_vol,
        legs_used=legs_used,
        legs_reported=legs_reported,
        portfolio_vol=round(port_vol, 6),
        cvar=round(cvar_val, 6),
        vol_budget=vol_budget,
        cvar_budget=cvar_budget,
        vol_scaler=round(vol_scaler, 6),
        cvar_scaler=round(cvar_scaler, 6),
        gross_scaler=round(gross, 6),
        risk_contributions=rc_named,
        factor_betas=fb,
        book_factor_exposure=be,
        corr_regime=corr_regime,
        binding=binding,
        explain=explain,
        estimator_meta=estimator_meta,
    )


def _fallback_risk_state(
    syms: List[str],
    target_weights: Dict[str, float],
    vol_budget: float,
    cvar_budget: float,
    explain: List[str],
) -> RiskState:
    k = max(len(syms), 1)
    return RiskState(
        cov=np.eye(k) * 0.04,
        corr=np.eye(k),
        downside_corr=np.eye(k),
        leg_vol={s: 0.2 for s in syms},
        legs_used=[],
        legs_reported=[],
        portfolio_vol=0.2,
        cvar=-0.05,
        vol_budget=vol_budget,
        cvar_budget=cvar_budget,
        vol_scaler=1.0,
        cvar_scaler=1.0,
        gross_scaler=1.0,
        risk_contributions={},
        factor_betas={},
        book_factor_exposure={},
        corr_regime="UNKNOWN",
        binding="INSUFFICIENT_DATA",
        explain=explain,
        estimator_meta={"vol_model": "fallback"},
    )


def _off_diag_mean(mat: np.ndarray) -> float:
    k = mat.shape[0]
    if k < 2:
        return 0.0
    mask = ~np.eye(k, dtype=bool)
    return float(np.mean(mat[mask]))


def _clean_return_series(returns: pd.Series) -> pd.Series:
    """Numeric, finite returns only.

    Market data can arrive as object dtype, include inf from bad adjustment
    rows, or carry sparse non-numeric provider artifacts. Risk estimation is
    allowed to degrade from fewer samples, but it should never propagate those
    artifacts into covariance math.
    """
    out = pd.to_numeric(returns, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    return out[np.isfinite(out)]


def _clean_returns_df(returns_df: pd.DataFrame) -> pd.DataFrame:
    if returns_df is None or returns_df.empty:
        return pd.DataFrame()
    out = returns_df.apply(pd.to_numeric, errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    if out.empty:
        return out
    finite_mask = np.isfinite(out.to_numpy(dtype=float)).all(axis=1)
    return out.loc[finite_mask]


def _finite_square_matrix(mat: np.ndarray, size: Optional[int] = None) -> np.ndarray:
    arr = np.asarray(mat, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        k = size or (arr.shape[0] if arr.ndim >= 1 and arr.shape[0] > 0 else 1)
        return np.eye(k)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if size is not None and arr.shape[0] != size:
        return np.eye(size)
    return arr


def _finite_float(value: float, fallback: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if math.isfinite(out) else fallback
