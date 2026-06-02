from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

import pandas as pd

from .base import Field, SymbolSnapshot
from .store import LocalStore
from ..features.indicators import indicator_frame, row_at_or_before


OHLCV_FIELDS = ["Open", "High", "Low", "Close", "Volume"]
INDICATOR_FIELDS = [
    "ma50",
    "ma150",
    "ma200",
    "ma220",
    "ema10",
    "ema20",
    "ema50",
    "rsi14",
    "rsi14_weekly",
    "macd",
    "macd_signal",
    "return_1d",
    "return_2d",
    "return_10d",
    "realized_vol20",
    "drawdown_60d_high_pct",
    "atr14",
    "chandelier_exit",
    "vwap20",
    "avwap_60d",
    "support_60d_low",
    "support_distance_60d_pct",
    "cmf20",
    "mfi14",
    "ad_line",
    "ad_slope20",
    "distribution_days_25d",
]


@dataclass
class MarketData:
    config: Dict[str, Any]
    store: LocalStore

    def load_history(self, symbol: str) -> pd.DataFrame:
        return self.store.load_history(symbol)

    def snapshot(self, symbol: str, as_of: str) -> SymbolSnapshot:
        raw = self.load_history(symbol)
        day = date.fromisoformat(str(as_of)[:10])
        if raw.empty:
            return SymbolSnapshot(
                symbol=symbol,
                as_of=day,
                fields={
                    "history": Field("history", None, "local_csv", None),
                    "close": Field("close", None, "local_csv", None),
                    "ma200": Field("ma200", None, "local_csv", None),
                },
            )
        ind = indicator_frame(
            raw,
            atr_multiplier=float(self.config.get("atr", {}).get("multiplier", 4.5)),
            chandelier_period=int(self.config.get("atr", {}).get("chandelier_period", 22)),
        )
        row = row_at_or_before(ind, as_of)
        if row is None:
            return SymbolSnapshot(symbol=symbol, as_of=day, fields={"history": Field("history", None, "local_csv", None)})
        row_date = row.name.date()
        fields: Dict[str, Field] = {}
        row_is_proxy = _bool_value(row.get("is_proxy")) if "is_proxy" in row.index else False
        row_source = str(row.get("source") or "local_csv")
        for col in OHLCV_FIELDS:
            if col in row.index:
                fields[col.lower()] = Field(col.lower(), _finite(row[col]), row_source, row_date, is_proxy=row_is_proxy)
        fields["close"] = fields.get("close", Field("close", None, row_source, row_date, is_proxy=row_is_proxy))
        if "is_proxy" in row.index:
            fields["is_proxy"] = Field("is_proxy", 1.0 if row_is_proxy else 0.0, row_source, row_date, is_proxy=row_is_proxy)
        for col in INDICATOR_FIELDS:
            value = _finite(row[col]) if col in row.index else None
            source = f"derived_ohlcv:{row_source}" if row_is_proxy else "derived_ohlcv"
            fields[col] = Field(col, value, source, row_date, is_proxy=row_is_proxy)
        return SymbolSnapshot(symbol=symbol, as_of=day, fields=fields)

    def dated_snapshot(self, name: str, as_of: str) -> Optional[Dict[str, Any]]:
        if self.config.get("runtime", {}).get("offline_replay_mode"):
            return self.store.load_dated_snapshot(name, as_of)
        return self.store.load_dated_snapshot(name, as_of)


def _finite(value: Any) -> Optional[float]:
    try:
        out = float(value)
        if out == out and out not in {float("inf"), float("-inf")}:
            return out
    except Exception:
        return None
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
