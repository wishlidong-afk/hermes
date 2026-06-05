from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class FlowMetrics:
    symbol: str
    as_of: str
    cmf20: Optional[float]
    mfi14: Optional[float]
    ad_slope20: Optional[float]
    outflow_days_5d: Optional[int]
    legacy_signed_5d: Optional[float]
    severity: str
    source: str = "ohlcv_cmf_mfi_ad"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def money_flow_metrics(symbol: str, history: pd.DataFrame, as_of: str) -> FlowMetrics:
    frame = history.loc[history.index <= pd.Timestamp(as_of)].copy()
    if frame.empty or not {"High", "Low", "Close", "Volume"}.issubset(frame.columns):
        return FlowMetrics(symbol, as_of, None, None, None, None, None, "MISSING")
    cmf = chaikin_money_flow(frame, 20)
    mfi = money_flow_index(frame, 14)
    ad_line = accumulation_distribution_line(frame)
    ad_slope = rolling_slope(ad_line, 20)
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    signed = (close.diff().apply(np.sign).fillna(0.0) * close * volume).rolling(5).sum()
    outflow_days = ((cmf < 0) & (mfi < 50)).tail(5).sum()
    latest_cmf = _last(cmf)
    latest_mfi = _last(mfi)
    latest_ad = _last(ad_slope)
    severity = classify_flow_severity(latest_cmf, latest_mfi, latest_ad, int(outflow_days))
    return FlowMetrics(
        symbol=symbol,
        as_of=frame.index[-1].date().isoformat(),
        cmf20=latest_cmf,
        mfi14=latest_mfi,
        ad_slope20=latest_ad,
        outflow_days_5d=int(outflow_days),
        legacy_signed_5d=_last(signed),
        severity=severity,
    )


def basket_flow(symbols: Iterable[str], histories: Dict[str, pd.DataFrame], as_of: str) -> Dict[str, Any]:
    rows = [money_flow_metrics(sym, histories.get(sym, pd.DataFrame()), as_of) for sym in symbols]
    available = [row for row in rows if row.severity != "MISSING"]
    freshness = _basket_freshness(rows, as_of)
    if not available:
        return {"available": False, "severity": "MISSING", **freshness, "components": [row.to_dict() for row in rows]}
    cmf_values = [row.cmf20 for row in available if row.cmf20 is not None]
    mfi_values = [row.mfi14 for row in available if row.mfi14 is not None]
    severe = sum(1 for row in available if row.severity in {"ABNORMAL", "SEVERE"})
    severity = "SEVERE" if severe >= max(2, len(available) // 2) else ("ABNORMAL" if severe else "NORMAL")
    return {
        "available": True,
        "severity": severity,
        "avg_cmf20": float(np.mean(cmf_values)) if cmf_values else None,
        "avg_mfi14": float(np.mean(mfi_values)) if mfi_values else None,
        "abnormal_components": severe,
        "component_count": len(available),
        **freshness,
        "components": [row.to_dict() for row in rows],
    }


def _basket_freshness(rows: list[FlowMetrics], requested_as_of: str) -> Dict[str, Any]:
    requested = pd.Timestamp(str(requested_as_of)[:10])
    component_dates = []
    stale_components = []
    for row in rows:
        if row.severity == "MISSING":
            stale_components.append({"symbol": row.symbol, "as_of": row.as_of, "stale_days": None, "severity": row.severity})
            continue
        try:
            day = pd.Timestamp(str(row.as_of)[:10])
        except Exception:
            stale_components.append({"symbol": row.symbol, "as_of": row.as_of, "stale_days": None, "severity": row.severity})
            continue
        component_dates.append(day)
        stale_days = max(0, int((requested - day).days))
        if stale_days > 0:
            stale_components.append({"symbol": row.symbol, "as_of": row.as_of, "stale_days": stale_days, "severity": row.severity})
    if not component_dates:
        return {"component_min_as_of": None, "component_max_stale_days": None, "stale_components": stale_components}
    min_day = min(component_dates)
    max_stale = max(0, int((requested - min_day).days))
    return {
        "component_min_as_of": min_day.date().isoformat(),
        "component_max_stale_days": max_stale,
        "stale_components": stale_components,
    }


def chaikin_money_flow(frame: pd.DataFrame, window: int = 20) -> pd.Series:
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    denominator = (high - low).replace(0, np.nan)
    multiplier = ((close - low) - (high - close)) / denominator
    mfv = multiplier.fillna(0.0) * volume
    return mfv.rolling(window).sum() / volume.rolling(window).sum().replace(0, np.nan)


def money_flow_index(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    direction = typical.diff()
    positive = raw_flow.where(direction > 0, 0.0).rolling(window).sum()
    negative = raw_flow.where(direction < 0, 0.0).rolling(window).sum()
    ratio = positive / negative.replace(0, np.nan)
    mfi = 100 - 100 / (1 + ratio)
    mfi = mfi.mask((negative == 0) & (positive > 0), 100.0)
    mfi = mfi.mask((positive == 0) & (negative > 0), 0.0)
    return mfi


def accumulation_distribution_line(frame: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    close = pd.to_numeric(frame["Close"], errors="coerce")
    volume = pd.to_numeric(frame["Volume"], errors="coerce")
    denominator = (high - low).replace(0, np.nan)
    multiplier = ((close - low) - (high - close)) / denominator
    return (multiplier.fillna(0.0) * volume).cumsum()


def rolling_slope(series: pd.Series, window: int = 20) -> pd.Series:
    def slope(values: np.ndarray) -> float:
        x = np.arange(len(values), dtype=float)
        if np.isnan(values).any() or len(values) < 2:
            return np.nan
        return float(np.polyfit(x, values, 1)[0])

    return series.rolling(window).apply(slope, raw=True)


def classify_flow_severity(cmf: Optional[float], mfi: Optional[float], ad_slope: Optional[float], outflow_days_5d: int) -> str:
    if cmf is None or mfi is None:
        return "MISSING"
    if cmf <= -0.20 and mfi <= 35 and outflow_days_5d >= 4:
        return "SEVERE"
    if cmf <= -0.10 and mfi <= 45 and (ad_slope is None or ad_slope < 0):
        return "ABNORMAL"
    if cmf < 0 and mfi < 50:
        return "WATCH"
    return "NORMAL"


def _last(series: pd.Series) -> Optional[float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return None
    value = float(clean.iloc[-1])
    return value if value == value else None
