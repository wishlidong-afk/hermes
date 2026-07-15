from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from ...config import trade_symbols
from .store import LocalStore


def decision_gating_symbols(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Symbols whose common close defines the strategy decision date."""
    symbols = set(trade_symbols(dict(config)))
    symbols.update({"QQQ", "SPY"})
    return tuple(sorted(symbols))


def last_bar_dates(
    config: Mapping[str, Any],
    symbols: Iterable[str] | None = None,
) -> dict[str, date]:
    store = LocalStore(dict(config))
    out: dict[str, date] = {}
    for symbol in symbols or decision_gating_symbols(config):
        history = store.load_history(symbol)
        if history is None or getattr(history, "empty", True):
            continue
        last = history.index[-1]
        out[str(symbol)] = last.date() if hasattr(last, "date") else date.fromisoformat(str(last)[:10])
    return out


def latest_common_history_date(
    config: Mapping[str, Any],
    symbols: Iterable[str] | None = None,
) -> str | None:
    dates = last_bar_dates(config, symbols)
    return min(dates.values()).isoformat() if dates else None


def resolve_decision_as_of(value: Any, config: Mapping[str, Any]) -> str:
    text = str(value or "").strip()
    if text and text.lower() != "latest":
        return date.fromisoformat(text[:10]).isoformat()
    return latest_common_history_date(config) or date.today().isoformat()
