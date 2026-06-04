from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from .costs import apply_cost
from .metrics import equity_metrics


@dataclass(frozen=True)
class SimulationResult:
    equity_curve: Dict[str, float]
    turnover: float
    metrics: Dict[str, object]
    rows: list[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DayDecision:
    date: str
    target_weights: Dict[str, float]

    def to_dict(self) -> Dict[str, object]:
        return {"date": self.date, "target_weights": {k: round(float(v), 8) for k, v in sorted(self.target_weights.items())}}


def simulate_rebalanced_weights(
    histories: Dict[str, pd.DataFrame],
    target_weights_by_date: Dict[str, Dict[str, float]],
    initial_capital: float = 100000.0,
    friction_bps: float = 5.0,
) -> SimulationResult:
    dates = sorted(target_weights_by_date)
    if not dates:
        return SimulationResult({}, 0.0, equity_metrics(pd.Series(dtype=float)).to_dict(), [])
    equity = float(initial_capital)
    previous_weights: Dict[str, float] = {}
    equity_curve: Dict[str, float] = {}
    rows: list[Dict[str, object]] = []
    total_turnover = 0.0
    friction = friction_bps / 10000.0

    previous_date: Optional[str] = None
    for date in dates:
        weights = {symbol: max(0.0, float(weight)) for symbol, weight in target_weights_by_date[date].items()}
        gross = sum(weights.values())
        if gross > 1.0:
            weights = {symbol: weight / gross for symbol, weight in weights.items()}
        if previous_date is not None:
            period_return = _portfolio_return(histories, previous_weights, previous_date, date)
            equity *= 1.0 + period_return
        turnover = sum(abs(weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0)) for symbol in set(weights) | set(previous_weights))
        total_turnover += turnover
        equity *= 1.0 - turnover * friction
        equity_curve[date] = round(equity, 6)
        rows.append({"date": date, "equity": round(equity, 6), "turnover": round(turnover, 6), "weights": weights})
        previous_weights = weights
        previous_date = date

    series = pd.Series(equity_curve)
    return SimulationResult(equity_curve, round(total_turnover, 6), equity_metrics(series).to_dict(), rows)


def simulate(
    decisions: list[DayDecision],
    price_panel: Dict[str, pd.Series],
    cfg: Optional[Dict[str, Any]] = None,
    *,
    initial_capital: float = 100000.0,
    enable: Optional[set[str]] = None,
) -> SimulationResult:
    if not decisions:
        return SimulationResult({}, 0.0, equity_metrics(pd.Series(dtype=float)).to_dict(), [])
    enabled = enable or {"costs"}
    ordered = sorted(decisions, key=lambda item: item.date)
    equity = float(initial_capital)
    previous_weights: Dict[str, float] = {}
    previous_date: Optional[str] = None
    equity_curve: Dict[str, float] = {}
    rows: list[Dict[str, object]] = []
    total_turnover = 0.0

    for decision in ordered:
        day = decision.date
        if previous_date is not None:
            equity *= 1.0 + _panel_portfolio_return(price_panel, previous_weights, previous_date, day)
        weights = _normalize_weights(decision.target_weights)
        turnover = sum(abs(weights.get(leg, 0.0) - previous_weights.get(leg, 0.0)) for leg in set(weights) | set(previous_weights))
        cost = apply_cost(equity * turnover, None, cfg) if "costs" in enabled else 0.0
        equity -= cost
        total_turnover += turnover
        equity_curve[day] = round(equity, 6)
        rows.append(
            {
                "date": day,
                "equity": round(equity, 6),
                "turnover": round(turnover, 6),
                "cost": round(cost, 6),
                "weights": weights,
            }
        )
        previous_weights = weights
        previous_date = day
    series = pd.Series(equity_curve)
    return SimulationResult(equity_curve, round(total_turnover, 6), equity_metrics(series).to_dict(), rows)


def buy_and_hold_weights(symbols: Iterable[str]) -> Dict[str, float]:
    symbols = list(symbols)
    if not symbols:
        return {}
    weight = 1.0 / len(symbols)
    return {symbol: weight for symbol in symbols}


def _portfolio_return(histories: Dict[str, pd.DataFrame], weights: Dict[str, float], start: str, end: str) -> float:
    total = 0.0
    for symbol, weight in weights.items():
        if weight <= 0:
            continue
        total += weight * _symbol_return(histories.get(symbol), start, end)
    return total


def _symbol_return(history: Optional[pd.DataFrame], start: str, end: str) -> float:
    if history is None or history.empty or "Close" not in history.columns:
        return 0.0
    frame = history.loc[history.index <= pd.Timestamp(end)]
    start_frame = frame.loc[frame.index <= pd.Timestamp(start)]
    if frame.empty or start_frame.empty:
        return 0.0
    start_close = float(start_frame["Close"].iloc[-1])
    end_close = float(frame["Close"].iloc[-1])
    if start_close <= 0:
        return 0.0
    return end_close / start_close - 1.0


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    cleaned = {leg: max(0.0, float(weight)) for leg, weight in weights.items()}
    gross = sum(cleaned.values())
    if gross > 1.0:
        return {leg: weight / gross for leg, weight in cleaned.items()}
    return cleaned


def _panel_portfolio_return(price_panel: Dict[str, pd.Series], weights: Dict[str, float], start: str, end: str) -> float:
    total = 0.0
    for leg, weight in weights.items():
        if weight <= 0:
            continue
        total += weight * _panel_return(price_panel.get(leg), start, end)
    return total


def _panel_return(series: Optional[pd.Series], start: str, end: str) -> float:
    if series is None or series.empty:
        return 0.0
    local = pd.to_numeric(series, errors="coerce").dropna()
    if local.empty:
        return 0.0
    local.index = pd.to_datetime(local.index)
    start_rows = local.loc[local.index <= pd.Timestamp(start)]
    end_rows = local.loc[local.index <= pd.Timestamp(end)]
    if start_rows.empty or end_rows.empty:
        return 0.0
    start_value = float(start_rows.iloc[-1])
    end_value = float(end_rows.iloc[-1])
    if start_value <= 0:
        return 0.0
    return end_value / start_value - 1.0
