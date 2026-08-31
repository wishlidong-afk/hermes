from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from ...config import trade_symbols
from .store import LocalStore


class DecisionClockUnavailable(RuntimeError):
    """Raised when an implicit decision date lacks required market histories."""

    def __init__(self, missing_symbols: Iterable[str]) -> None:
        self.missing_symbols = tuple(sorted(str(symbol) for symbol in missing_symbols))
        super().__init__(
            "latest decision date unavailable; missing required histories: "
            + ", ".join(self.missing_symbols)
        )


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


def _decision_clock_state(
    config: Mapping[str, Any],
    symbols: Iterable[str] | None = None,
) -> tuple[dict[str, date], tuple[str, ...]]:
    required = tuple(str(symbol) for symbol in symbols) if symbols is not None else ()
    if not required:
        required = decision_gating_symbols(config)
    dates = last_bar_dates(config, required)
    missing = tuple(sorted(symbol for symbol in required if symbol not in dates))
    return dates, missing


def latest_common_history_date(
    config: Mapping[str, Any],
    symbols: Iterable[str] | None = None,
) -> str | None:
    dates, missing = _decision_clock_state(config, symbols)
    return min(dates.values()).isoformat() if dates and not missing else None


def resolve_decision_as_of(value: Any, config: Mapping[str, Any]) -> str:
    text = str(value or "").strip()
    if text and text.lower() != "latest":
        return date.fromisoformat(text[:10]).isoformat()
    dates, missing = _decision_clock_state(config)
    if missing:
        raise DecisionClockUnavailable(missing)
    return min(dates.values()).isoformat()
