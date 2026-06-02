"""E27 Tax / Wash-Sale Awareness -- advisory-only tax optimization.

Provides:
  - Wash-sale detection (30-day lookback on substantially identical securities)
  - Tax-lot optimization (HIFO / specific-ID for loss harvesting)
  - After-tax return estimation for execution plan tie-breaking

All outputs are advisory; no trades are executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TaxLot:
    symbol: str
    shares: float
    cost_basis: float        # per share
    acquired: date
    is_short_term: bool      # held < 1 year

    @property
    def total_cost(self) -> float:
        return self.shares * self.cost_basis


@dataclass(frozen=True)
class WashSaleCheck:
    symbol: str
    is_wash_sale: bool
    reason: str
    blocked_loss: float      # loss that would be disallowed
    lookback_sells: List[Dict[str, Any]]


@dataclass(frozen=True)
class TaxLotRecommendation:
    lots_to_sell: List[TaxLot]
    total_shares: float
    realized_gain: float     # positive = gain, negative = loss
    short_term_portion: float
    long_term_portion: float
    method: str              # HIFO, FIFO, SPECIFIC


def wash_sale_check(
    symbol: str,
    sell_date: date,
    recent_trades: List[Dict[str, Any]],
    substantially_identical: Optional[List[str]] = None,
) -> WashSaleCheck:
    """Check if selling symbol on sell_date would trigger IRS wash-sale rule.

    Wash sale: selling at a loss and buying the same (or substantially identical)
    security within 30 days before or after the sale.

    recent_trades: list of {symbol, date, action(buy/sell), shares, price}
    """
    if substantially_identical is None:
        substantially_identical = []

    check_symbols = {symbol} | set(substantially_identical)
    window_start = sell_date - timedelta(days=30)
    window_end = sell_date + timedelta(days=30)

    lookback_buys = []
    for trade in recent_trades:
        trade_date = trade.get("date")
        if isinstance(trade_date, str):
            trade_date = date.fromisoformat(trade_date)
        trade_sym = trade.get("symbol", "")
        action = trade.get("action", "")

        if (trade_sym in check_symbols
                and action == "buy"
                and window_start <= trade_date <= window_end):
            lookback_buys.append(trade)

    if lookback_buys:
        return WashSaleCheck(
            symbol=symbol,
            is_wash_sale=True,
            reason=f"{len(lookback_buys)} buy(s) of {check_symbols} within 30-day window",
            blocked_loss=0.0,
            lookback_sells=lookback_buys,
        )

    return WashSaleCheck(
        symbol=symbol,
        is_wash_sale=False,
        reason="no substantially identical purchases within 30-day window",
        blocked_loss=0.0,
        lookback_sells=[],
    )


def tax_lot_optimize(
    lots: List[TaxLot],
    shares_to_sell: float,
    current_price: float,
    method: str = "HIFO",
) -> TaxLotRecommendation:
    """Select which tax lots to sell to minimize tax impact.

    Methods:
      HIFO: Highest-In, First-Out (maximizes loss / minimizes gain)
      FIFO: First-In, First-Out
      SPECIFIC: caller provides order (passthrough)
    """
    if not lots or shares_to_sell <= 0:
        return TaxLotRecommendation(
            lots_to_sell=[], total_shares=0.0,
            realized_gain=0.0, short_term_portion=0.0,
            long_term_portion=0.0, method=method,
        )

    if method == "HIFO":
        sorted_lots = sorted(lots, key=lambda l: -l.cost_basis)
    elif method == "FIFO":
        sorted_lots = sorted(lots, key=lambda l: l.acquired)
    else:
        sorted_lots = list(lots)

    selected = []
    remaining = shares_to_sell
    total_gain = 0.0
    st_gain = 0.0
    lt_gain = 0.0

    for lot in sorted_lots:
        if remaining <= 0:
            break
        take = min(lot.shares, remaining)
        gain = take * (current_price - lot.cost_basis)
        total_gain += gain
        if lot.is_short_term:
            st_gain += gain
        else:
            lt_gain += gain

        selected.append(TaxLot(
            symbol=lot.symbol,
            shares=take,
            cost_basis=lot.cost_basis,
            acquired=lot.acquired,
            is_short_term=lot.is_short_term,
        ))
        remaining -= take

    return TaxLotRecommendation(
        lots_to_sell=selected,
        total_shares=round(shares_to_sell - remaining, 6),
        realized_gain=round(total_gain, 2),
        short_term_portion=round(st_gain, 2),
        long_term_portion=round(lt_gain, 2),
        method=method,
    )


def after_tax_return(
    pretax_gain: float,
    short_term_rate: float = 0.37,
    long_term_rate: float = 0.20,
    is_short_term: bool = True,
) -> float:
    """Estimate after-tax return for execution plan tie-breaking."""
    rate = short_term_rate if is_short_term else long_term_rate
    tax = max(0.0, pretax_gain) * rate
    return round(pretax_gain - tax, 2)
