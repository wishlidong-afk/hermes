from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


TRADING_DAYS = 252


@dataclass(frozen=True)
class VolatilitySnapshot:
    realized_vol: Optional[float]
    forecast_vol: Optional[float]
    baseline_vol: Optional[float]
    relative_scaler: float


def returns_from(values: pd.Series) -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    valid = series.dropna()
    if valid.empty:
        return series
    # Equity prices in this system are far above return magnitudes. If the
    # input already looks like returns, keep it as-is.
    if float(valid.abs().median()) > 2.0:
        return series.pct_change(fill_method=None)
    return series


def realized_volatility(values: pd.Series, window: int = 20, annualize: bool = True) -> pd.Series:
    rets = returns_from(values)
    vol = rets.rolling(window, min_periods=window).std(ddof=0)
    if annualize:
        vol = vol * math.sqrt(TRADING_DAYS)
    return vol


def ewma_volatility(
    values: pd.Series,
    span: int = 20,
    min_periods: int = 20,
    annualize: bool = True,
) -> pd.Series:
    rets = returns_from(values)
    vol = rets.ewm(span=span, adjust=False, min_periods=min_periods).std(bias=False)
    if annualize:
        vol = vol * math.sqrt(TRADING_DAYS)
    return vol


def forecast_volatility(values: pd.Series, method: str = "ewma", span: int = 20, annualize: bool = True) -> pd.Series:
    if method == "ewma":
        return ewma_volatility(values, span=span, annualize=annualize)
    if method == "realized":
        return realized_volatility(values, window=span, annualize=annualize)
    raise ValueError(f"unsupported volatility forecast method: {method}")


def baseline_realized_volatility(
    values: pd.Series,
    baseline_window: int = 252,
    realized_window: int = 20,
    stat: str = "median_20d_realized",
) -> pd.Series:
    realized = realized_volatility(values, window=realized_window, annualize=True)
    rolling = realized.rolling(baseline_window, min_periods=max(20, baseline_window // 4))
    if stat == "median_20d_realized":
        return rolling.median()
    if stat == "mean_20d_realized":
        return rolling.mean()
    if stat.startswith("q"):
        quantile = float(stat[1:]) / 100.0
        return rolling.quantile(quantile)
    raise ValueError(f"unsupported baseline volatility stat: {stat}")


def relative_vol_scaler(forecast: Optional[float], baseline: Optional[float], floor: float = 0.25) -> float:
    if forecast is None or baseline is None:
        return 1.0
    if not np.isfinite(forecast) or not np.isfinite(baseline) or forecast <= 0 or baseline <= 0:
        return 1.0
    return float(min(1.0, max(floor, baseline / forecast)))


def volatility_snapshot(
    values: pd.Series,
    forecast_method: str = "ewma",
    forecast_span: int = 20,
    baseline_window: int = 252,
    baseline_stat: str = "median_20d_realized",
    floor: float = 0.25,
) -> VolatilitySnapshot:
    realized = realized_volatility(values, window=20)
    forecast = forecast_volatility(values, method=forecast_method, span=forecast_span)
    baseline = baseline_realized_volatility(values, baseline_window=baseline_window, stat=baseline_stat)
    realized_last = _last_finite(realized)
    forecast_last = _last_finite(forecast)
    baseline_last = _last_finite(baseline)
    return VolatilitySnapshot(
        realized_vol=realized_last,
        forecast_vol=forecast_last,
        baseline_vol=baseline_last,
        relative_scaler=relative_vol_scaler(forecast_last, baseline_last, floor=floor),
    )


def _last_finite(values: pd.Series) -> Optional[float]:
    valid = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])
