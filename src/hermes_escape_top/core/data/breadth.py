from __future__ import annotations

from datetime import date
from typing import Any
from typing import Dict

import pandas as pd

from .adapters import SoftDataRecord


def component_breadth(histories: Dict[str, pd.DataFrame], as_of: str, ma_col: str = "Close", window: int = 50) -> Dict[str, object]:
    rows = {}
    available = 0
    above = 0
    for symbol, frame in sorted(histories.items()):
        local = frame.loc[frame.index <= pd.Timestamp(as_of)] if frame is not None and not frame.empty else pd.DataFrame()
        if len(local) < window or ma_col not in local.columns:
            rows[symbol] = {"available": False, "above": None}
            continue
        close = pd.to_numeric(local[ma_col], errors="coerce")
        ma = close.rolling(window).mean()
        is_above = bool(close.iloc[-1] > ma.iloc[-1])
        available += 1
        above += int(is_above)
        rows[symbol] = {"available": True, "above": is_above, "close": float(close.iloc[-1]), f"ma{window}": float(ma.iloc[-1])}
    ratio = above / available if available else None
    return {"available": available > 0, "above_ratio": ratio, "above_count": above, "component_count": available, "components": rows}


class ComponentBreadthSource:
    name = "component_breadth"
    feature_flag = "data_component_breadth"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, True)):
            return SoftDataRecord(self.name, day, None, "local_component_history", False, reason=f"feature disabled: {self.feature_flag}")
        return self.fetch(as_of, config)

    def fetch(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        from .store import LocalStore

        day = date.fromisoformat(str(as_of)[:10])
        store = LocalStore(config)
        fields: Dict[str, float | None] = {}
        all_components: set[str] = set()
        for sleeve, components in sorted(config.get("component_proxies", {}).items()):
            all_components.update(components)
            histories = {symbol: store.load_history(symbol) for symbol in components}
            prefix = sleeve.lower()
            fields[f"{prefix}_pct_above_50dma"] = _pct_above(histories, as_of, 50)
            fields[f"{prefix}_pct_above_200dma"] = _pct_above(histories, as_of, 200)
            fields[f"{prefix}_breadth_chg_5d"] = _breadth_change(histories, as_of, 50, 5)
        histories = {symbol: store.load_history(symbol) for symbol in sorted(all_components)}
        fields["aggregate_pct_above_50dma"] = _pct_above(histories, as_of, 50)
        fields["aggregate_pct_above_200dma"] = _pct_above(histories, as_of, 200)
        fields["aggregate_breadth_chg_5d"] = _breadth_change(histories, as_of, 50, 5)
        available = fields["aggregate_pct_above_50dma"] is not None and fields["aggregate_pct_above_200dma"] is not None
        return SoftDataRecord(
            self.name,
            day,
            fields["aggregate_pct_above_50dma"],
            "local_component_history",
            available,
            is_proxy=True,
            latency_days=0,
            quality_penalty=2.0 if available else 5.0,
            reason="" if available else "component history missing or warmup insufficient",
            fields=fields,
        )


def _pct_above(histories: Dict[str, pd.DataFrame], as_of: str, window: int) -> float | None:
    available = 0
    above = 0
    for frame in histories.values():
        local = _local(frame, as_of)
        if len(local) < window or "Close" not in local:
            continue
        close = pd.to_numeric(local["Close"], errors="coerce").dropna()
        if len(close) < window:
            continue
        ma = close.rolling(window).mean()
        available += 1
        above += int(float(close.iloc[-1]) > float(ma.iloc[-1]))
    return above / available if available else None


def _breadth_change(histories: Dict[str, pd.DataFrame], as_of: str, window: int, lookback: int) -> float | None:
    current = _pct_above(histories, as_of, window)
    prior_dates = []
    for frame in histories.values():
        local = _local(frame, as_of)
        if len(local) > lookback:
            prior_dates.append(local.index[-lookback - 1])
    if current is None or not prior_dates:
        return None
    prior_day = min(prior_dates).date().isoformat()
    prior = _pct_above(histories, prior_day, window)
    if prior is None:
        return None
    return current - prior


def _local(frame: pd.DataFrame, as_of: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame.loc[frame.index <= pd.Timestamp(str(as_of)[:10])]
