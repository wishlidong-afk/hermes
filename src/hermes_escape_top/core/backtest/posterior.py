from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

import pandas as pd


@dataclass(frozen=True)
class IdealPnlRow:
    sleeve: str
    symbol: str
    target_weight: float
    notional: float
    previous_close: Optional[float]
    current_close: Optional[float]
    shares: float
    pnl: float
    return_pct: Optional[float]
    data_available: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ["target_weight", "notional", "previous_close", "current_close", "shares", "pnl", "return_pct"]:
            if payload[key] is not None:
                payload[key] = round(float(payload[key]), 6)
        return payload


def ideal_previous_day_pnl(
    sleeve: str,
    symbol: str,
    target_weight: float,
    history: pd.DataFrame,
    as_of: str,
    portfolio_value: float = 100000.0,
) -> IdealPnlRow:
    notional = float(portfolio_value) * float(target_weight)
    if symbol in {"-", "BOXX", "CASH"} or notional <= 0:
        return IdealPnlRow(sleeve, symbol, float(target_weight), notional, None, None, 0.0, 0.0, 0.0, True, "No market-risk leg.")
    if history is None or history.empty or "Close" not in history.columns:
        return IdealPnlRow(sleeve, symbol, float(target_weight), notional, None, None, 0.0, 0.0, None, False, "Missing price history.")
    local = history.loc[history.index <= pd.Timestamp(as_of)].copy()
    if len(local) < 2:
        return IdealPnlRow(sleeve, symbol, float(target_weight), notional, None, None, 0.0, 0.0, None, False, "Need at least two trading closes.")
    previous = float(local["Close"].iloc[-2])
    current = float(local["Close"].iloc[-1])
    if previous <= 0:
        return IdealPnlRow(sleeve, symbol, float(target_weight), notional, previous, current, 0.0, 0.0, None, False, "Invalid previous close.")
    shares = notional / previous
    pnl = shares * (current - previous)
    ret = current / previous - 1.0
    return IdealPnlRow(sleeve, symbol, float(target_weight), notional, previous, current, shares, pnl, ret, True)


def escape_posterior_pnl(
    sizing: Dict[str, Dict[str, object]],
    histories: Dict[str, pd.DataFrame],
    as_of: str,
    portfolio_value: float = 100000.0,
) -> Dict[str, IdealPnlRow]:
    rows = {}
    for symbol, decision in sorted(sizing.items()):
        weight = float(decision.get("target_weight", 0.0))
        rows[symbol] = ideal_previous_day_pnl(symbol, symbol, weight, histories.get(symbol, pd.DataFrame()), as_of, portfolio_value)
    return rows


def mirror_posterior_pnl(
    mirror_decisions: Dict[str, object],
    histories: Dict[str, pd.DataFrame],
    as_of: str,
    portfolio_value: float = 100000.0,
) -> Dict[str, IdealPnlRow]:
    rows = {}
    for sleeve, decision in sorted(mirror_decisions.items()):
        selected = str(decision.selected_symbol)
        weight = float(decision.target_weight)
        rows[sleeve] = ideal_previous_day_pnl(sleeve, selected, weight, histories.get(selected, pd.DataFrame()), as_of, portfolio_value)
    return rows
