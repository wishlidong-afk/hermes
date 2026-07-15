from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceMetrics:
    final_value: float
    cagr: Optional[float]
    max_drawdown: float
    max_drawdown_start: Optional[str]
    max_drawdown_end: Optional[str]
    sharpe: Optional[float]
    sortino: Optional[float]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ["final_value", "cagr", "max_drawdown", "sharpe", "sortino"]:
            if payload[key] is not None:
                payload[key] = round(float(payload[key]), 6)
        return payload


def equity_metrics(equity: pd.Series, periods_per_year: int = 252) -> PerformanceMetrics:
    series = pd.to_numeric(equity, errors="coerce").dropna()
    if series.empty:
        return PerformanceMetrics(0.0, None, 0.0, None, None, None, None)
    returns = series.pct_change(fill_method=None).dropna()
    cagr = _cagr(series, periods_per_year)
    dd, start, end = max_drawdown(series)
    sharpe = _sharpe(returns, periods_per_year)
    sortino = _sortino(returns, periods_per_year)
    return PerformanceMetrics(float(series.iloc[-1]), cagr, dd, start, end, sharpe, sortino)


def compute_metrics(equity: pd.Series, benchmark: Optional[pd.Series] = None, trades: Optional[list[Dict[str, Any]]] = None) -> Dict[str, object]:
    perf = equity_metrics(equity).to_dict()
    max_dd = float(perf.get("max_drawdown") or 0.0)
    cagr = perf.get("cagr")
    perf["calmar"] = round(float(cagr) / abs(max_dd), 6) if cagr is not None and max_dd < 0 else None
    perf["turnover"] = _turnover(trades or [])
    if benchmark is not None and not benchmark.empty:
        bench = equity_metrics(benchmark).to_dict()
        perf["benchmark_cagr"] = bench.get("cagr")
        perf["benchmark_max_drawdown"] = bench.get("max_drawdown")
        bdd = float(bench.get("max_drawdown") or 0.0)
        perf["drawdown_reduction"] = round(abs(bdd) - abs(max_dd), 6)
        pcagr = float(cagr or 0.0)
        bcagr = float(bench.get("cagr") or 0.0)
        drag = bcagr - pcagr
        perf["cagr_drag"] = round(drag, 6)
        perf["insurance_ratio"] = round((abs(bdd) - abs(max_dd)) / drag, 6) if drag > 0 else None
    return perf


def max_drawdown(equity: pd.Series) -> tuple[float, Optional[str], Optional[str]]:
    series = pd.to_numeric(equity, errors="coerce").dropna()
    if series.empty:
        return 0.0, None, None
    peak = series.cummax()
    drawdown = series / peak - 1.0
    end = drawdown.idxmin()
    start = series.loc[:end].idxmax()
    return float(drawdown.loc[end]), _idx_to_str(start), _idx_to_str(end)


def _cagr(series: pd.Series, periods_per_year: int) -> Optional[float]:
    if len(series) < 2 or series.iloc[0] <= 0:
        return None
    years = (len(series) - 1) / periods_per_year
    if years <= 0:
        return None
    return float((series.iloc[-1] / series.iloc[0]) ** (1.0 / years) - 1.0)


def _sharpe(returns: pd.Series, periods_per_year: int) -> Optional[float]:
    if returns.empty:
        return None
    std = returns.std(ddof=0)
    if std == 0 or not np.isfinite(std):
        return None
    return float(returns.mean() / std * math.sqrt(periods_per_year))


def _sortino(returns: pd.Series, periods_per_year: int) -> Optional[float]:
    downside = returns[returns < 0]
    if returns.empty or downside.empty:
        return None
    std = downside.std(ddof=0)
    if std == 0 or not np.isfinite(std):
        return None
    return float(returns.mean() / std * math.sqrt(periods_per_year))


def _idx_to_str(value) -> str:
    return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)


def _turnover(trades: list[Dict[str, Any]]) -> float:
    total = 0.0
    for trade in trades:
        total += abs(float(trade.get("turnover", trade.get("notional", 0.0)) or 0.0))
    return round(total, 6)
