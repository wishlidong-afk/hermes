from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

from ..features.volatility import ewma_volatility, returns_from


@dataclass(frozen=True)
class PortfolioRiskState:
    legs_reported: list[str]
    legs_used: list[str]
    target_weights: Dict[str, float]
    forecast_portfolio_vol: Optional[float]
    gross_scaler: float
    effective_gross_scaler: float
    portfolio_risk_cap_active: bool
    avg_pairwise_corr: Optional[float]
    corr_percentile: Optional[float]
    corr_regime: str
    binding_constraint: str
    cov_meta: Dict[str, object] = field(default_factory=dict)
    explain: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ["forecast_portfolio_vol", "avg_pairwise_corr", "corr_percentile"]:
            if payload[key] is not None:
                payload[key] = round(float(payload[key]), 6)
        payload["gross_scaler"] = round(float(payload["gross_scaler"]), 6)
        payload["effective_gross_scaler"] = round(float(payload["effective_gross_scaler"]), 6)
        return payload


def compute_portfolio_risk(
    histories: Dict[str, pd.DataFrame],
    target_weights: Dict[str, float],
    config: Dict[str, object],
    excluded_symbols: Optional[set[str]] = None,
    feature_enabled: bool = False,
) -> PortfolioRiskState:
    portfolio_cfg = config.get("portfolio", {}) if isinstance(config.get("portfolio", {}), dict) else {}
    corr_window = int(portfolio_cfg.get("corr_window", 60))
    min_periods = int(portfolio_cfg.get("min_periods", 40))
    vol_window = int(portfolio_cfg.get("vol_window", 20))
    vol_budget = float(portfolio_cfg.get("vol_budget_annual", 0.35))
    penalty = float(portfolio_cfg.get("extreme_corr_penalty", 0.7))
    corr_pct_cfg = portfolio_cfg.get("corr_regime_pct", {"elevated": 80, "extreme": 92})
    excluded_symbols = excluded_symbols or set()

    legs_reported = sorted(symbol for symbol in target_weights if symbol in histories and len(histories[symbol].dropna()) >= min_periods)
    legs_used = [symbol for symbol in legs_reported if target_weights.get(symbol, 0.0) > 0 and symbol not in excluded_symbols]
    explain: list[str] = []
    if excluded_symbols:
        explain.append("Excluded hard-valve legs from gross calculation: " + ",".join(sorted(excluded_symbols)))
    if not legs_used:
        return PortfolioRiskState(
            legs_reported=legs_reported,
            legs_used=[],
            target_weights=target_weights,
            forecast_portfolio_vol=None,
            gross_scaler=1.0,
            effective_gross_scaler=1.0,
            portfolio_risk_cap_active=False,
            avg_pairwise_corr=None,
            corr_percentile=None,
            corr_regime="UNKNOWN",
            binding_constraint="NO_ACTIVE_LEGS",
            explain=explain + ["No active legs for portfolio risk budget."],
        )

    returns = {symbol: returns_from(_close_series(histories[symbol])).dropna() for symbol in legs_reported}
    common = _common_return_frame(returns, corr_window)
    vols = {symbol: _last_vol(histories[symbol], vol_window) for symbol in legs_reported}
    if len(common) < min_periods:
        return PortfolioRiskState(
            legs_reported=legs_reported,
            legs_used=legs_used,
            target_weights=target_weights,
            forecast_portfolio_vol=None,
            gross_scaler=1.0,
            effective_gross_scaler=1.0,
            portfolio_risk_cap_active=False,
            avg_pairwise_corr=None,
            corr_percentile=None,
            corr_regime="UNKNOWN",
            binding_constraint="INSUFFICIENT_COMMON_HISTORY",
            cov_meta={"common_samples": len(common), "min_periods": min_periods, "vols": _round_dict(vols)},
            explain=explain + ["Insufficient common return history; scaler stays neutral."],
        )

    corr_raw = common.corr().fillna(0.0)
    corr = shrink_correlation(corr_raw, shrinkage=0.05)
    avg_corr = average_pairwise_corr(corr)
    corr_pct = corr_percentile_history(returns, corr_window, avg_corr, min_periods)
    corr_regime = classify_corr_regime(corr_pct, corr_pct_cfg)
    sigma = covariance_from_corr(corr.loc[legs_used, legs_used], {symbol: vols[symbol] for symbol in legs_used})
    weights = np.array([float(target_weights.get(symbol, 0.0)) for symbol in legs_used], dtype=float)
    forecast_vol = float(math.sqrt(max(0.0, weights.T @ sigma @ weights)))
    gross = 1.0 if forecast_vol <= 0 else min(1.0, max(0.0, vol_budget / forecast_vol))
    binding = "NONE"
    if gross < 1.0:
        binding = "VOL_BUDGET"
        explain.append(f"Portfolio forecast vol {forecast_vol:.2%} exceeds budget {vol_budget:.2%}.")
    if corr_regime == "EXTREME":
        gross *= penalty
        binding = "EXTREME_CORR"
        explain.append("Extreme correlation regime penalty applied.")
    effective = gross if feature_enabled else 1.0
    if not feature_enabled:
        explain.append("Portfolio risk budget feature disabled: shadow only, effective scaler=1.")
    return PortfolioRiskState(
        legs_reported=legs_reported,
        legs_used=legs_used,
        target_weights=target_weights,
        forecast_portfolio_vol=forecast_vol,
        gross_scaler=gross,
        effective_gross_scaler=effective,
        portfolio_risk_cap_active=gross < 1.0 - 1e-9 or corr_regime == "EXTREME",
        avg_pairwise_corr=avg_corr,
        corr_percentile=corr_pct,
        corr_regime=corr_regime,
        binding_constraint=binding,
        cov_meta={
            "corr_window": corr_window,
            "common_samples": len(common),
            "vol_window": vol_window,
            "vols": _round_dict(vols),
            "shrinkage_lambda": 0.05,
        },
        explain=explain,
    )


def shrink_correlation(corr: pd.DataFrame, shrinkage: float = 0.05) -> pd.DataFrame:
    arr = corr.to_numpy(dtype=float)
    target = np.eye(arr.shape[0])
    shrunk = (1.0 - shrinkage) * arr + shrinkage * target
    return pd.DataFrame(shrunk, index=corr.index, columns=corr.columns)


def covariance_from_corr(corr: pd.DataFrame, vols: Dict[str, float]) -> np.ndarray:
    vol = np.array([float(vols[symbol]) for symbol in corr.index], dtype=float)
    return np.diag(vol) @ corr.to_numpy(dtype=float) @ np.diag(vol)


def average_pairwise_corr(corr: pd.DataFrame) -> Optional[float]:
    if corr.shape[0] < 2:
        return None
    arr = corr.to_numpy(dtype=float)
    upper = arr[np.triu_indices_from(arr, k=1)]
    return float(np.nanmean(upper)) if len(upper) else None


def corr_percentile_history(
    returns: Dict[str, pd.Series],
    corr_window: int,
    current_avg: Optional[float],
    min_periods: int,
) -> Optional[float]:
    if current_avg is None:
        return None
    common = pd.concat(returns, axis=1).dropna()
    if len(common) < max(min_periods, corr_window):
        return None
    values = []
    for end in range(corr_window, len(common) + 1):
        window = common.iloc[end - corr_window : end]
        avg = average_pairwise_corr(shrink_correlation(window.corr().fillna(0.0), shrinkage=0.05))
        if avg is not None and np.isfinite(avg):
            values.append(avg)
    if not values:
        return None
    return float(sum(value <= current_avg for value in values) / len(values) * 100.0)


def classify_corr_regime(percentile: Optional[float], cfg: Dict[str, float]) -> str:
    if percentile is None:
        return "UNKNOWN"
    if percentile >= float(cfg.get("extreme", 92)):
        return "EXTREME"
    if percentile >= float(cfg.get("elevated", 80)):
        return "ELEVATED"
    return "NORMAL"


def _common_return_frame(returns: Dict[str, pd.Series], window: int) -> pd.DataFrame:
    if not returns:
        return pd.DataFrame()
    return pd.concat(returns, axis=1).dropna().tail(window)


def _close_series(frame: pd.DataFrame) -> pd.Series:
    if "Close" in frame.columns:
        return pd.to_numeric(frame["Close"], errors="coerce")
    return pd.to_numeric(frame.iloc[:, 0], errors="coerce")


def _last_vol(frame: pd.DataFrame, window: int) -> float:
    series = ewma_volatility(_close_series(frame), span=window).dropna()
    if series.empty:
        return 0.0
    return float(series.iloc[-1])


def _round_dict(values: Dict[str, float]) -> Dict[str, float]:
    return {key: round(float(value), 6) for key, value in values.items()}
