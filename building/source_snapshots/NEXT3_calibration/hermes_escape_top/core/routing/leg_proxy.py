from __future__ import annotations

from typing import Dict, Iterable, Optional

import pandas as pd

from ...config import load_config
from ..data.store import LocalStore


PROXY_MAP = {
    "BOXX": [("2022-12-31", "BIL"), (None, "BOXX")],
    "DBMF": [("2019-05-07", "trend_synth"), (None, "DBMF")],
}


def leg_price_series(
    leg: str,
    as_of_range: Iterable[str] | pd.DatetimeIndex,
    histories: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.Series:
    dates = pd.DatetimeIndex(pd.to_datetime(list(as_of_range))).sort_values()
    if dates.empty:
        return pd.Series(dtype=float)
    history_map = histories if histories is not None else _load_default_histories(leg)
    if leg not in PROXY_MAP:
        return _normalized_direct_series(leg, dates, history_map)
    out: list[float] = []
    prev_value: Optional[float] = None
    prev_source: Optional[str] = None
    trend_synth = _trend_synth_series(dates, history_map) if any(source == "trend_synth" for _cutoff, source in PROXY_MAP.get(leg, [])) else pd.Series(dtype=float)
    for day in dates:
        source = _source_for_date(leg, day)
        if source == "trend_synth":
            source_value = float(trend_synth.loc[day]) if day in trend_synth.index else None
        else:
            source_value = _close_at_or_before(history_map.get(source), day)
        if prev_value is None or source_value is None:
            value = 100.0 if prev_value is None else prev_value
        elif source != prev_source:
            value = prev_value
        else:
            prev_source_value = _previous_source_value(source, history_map, dates, day, trend_synth=trend_synth)
            if prev_source_value and prev_source_value > 0:
                value = prev_value * (source_value / prev_source_value)
            else:
                value = prev_value
        out.append(float(value))
        prev_value = float(value)
        prev_source = source
    return pd.Series(out, index=dates, name=leg)


def leg_proxy_metadata(leg: str, as_of_range: Iterable[str] | pd.DatetimeIndex) -> pd.DataFrame:
    dates = pd.DatetimeIndex(pd.to_datetime(list(as_of_range))).sort_values()
    rows = []
    for day in dates:
        source = _source_for_date(leg, day) if leg in PROXY_MAP else leg
        rows.append({"date": day.date().isoformat(), "leg": leg, "source": source, "is_proxy": source != leg})
    return pd.DataFrame(rows)


def _source_for_date(leg: str, day: pd.Timestamp) -> str:
    for cutoff, source in PROXY_MAP.get(leg, []):
        if cutoff is None or day <= pd.Timestamp(cutoff):
            return source
    return leg


def _normalized_direct_series(leg: str, dates: pd.DatetimeIndex, histories: Dict[str, pd.DataFrame]) -> pd.Series:
    values = []
    first = None
    for day in dates:
        close = _close_at_or_before(histories.get(leg), day)
        if close is None:
            values.append(values[-1] if values else 100.0)
            continue
        if first is None:
            first = close
        values.append(100.0 * close / first if first else 100.0)
    return pd.Series(values, index=dates, name=leg)


def _trend_synth_series(dates: pd.DatetimeIndex, histories: Dict[str, pd.DataFrame]) -> pd.Series:
    qqq = histories.get("QQQ", pd.DataFrame())
    if qqq.empty or "Close" not in qqq:
        return pd.Series([100.0] * len(dates), index=dates, name="trend_synth")
    frame = qqq.loc[qqq.index <= dates.max()].copy()
    close = pd.to_numeric(frame["Close"], errors="coerce")
    ma200 = close.rolling(200, min_periods=60).mean()
    returns = close.pct_change().fillna(0.0)
    synth_returns = returns.where(close >= ma200, -0.25 * returns.abs())
    synth = (1.0 + synth_returns).cumprod() * 100.0
    out = []
    for day in dates:
        past = synth.loc[synth.index <= day]
        out.append(float(past.iloc[-1]) if not past.empty else 100.0)
    series = pd.Series(out, index=dates, name="trend_synth")
    first = float(series.iloc[0]) if not series.empty else 100.0
    return series / first * 100.0 if first else series


def _previous_source_value(
    source: str,
    histories: Dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    day: pd.Timestamp,
    *,
    trend_synth: Optional[pd.Series] = None,
) -> Optional[float]:
    previous_dates = dates[dates < day]
    if previous_dates.empty:
        return None
    prev_day = previous_dates[-1]
    if source == "trend_synth":
        synth = trend_synth if trend_synth is not None else _trend_synth_series(dates, histories)
        return float(synth.loc[prev_day]) if prev_day in synth.index else None
    return _close_at_or_before(histories.get(source), prev_day)


def _close_at_or_before(history: Optional[pd.DataFrame], day: pd.Timestamp) -> Optional[float]:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    frame = history.loc[history.index <= day]
    if frame.empty:
        return None
    value = float(frame["Close"].iloc[-1])
    return value if value == value else None


def _load_default_histories(leg: str) -> Dict[str, pd.DataFrame]:
    config = load_config()
    store = LocalStore(config)
    symbols = {leg}
    for _cutoff, source in PROXY_MAP.get(leg, []):
        if source is not None and source != "trend_synth":
            symbols.add(source)
    symbols.add("QQQ")
    return {symbol: store.load_history(symbol) for symbol in sorted(symbols)}
