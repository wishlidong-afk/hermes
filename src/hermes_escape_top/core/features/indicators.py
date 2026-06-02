from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def indicator_frame(df: pd.DataFrame, atr_multiplier: float = 4.5, chandelier_period: int = 22) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    close = pd.to_numeric(out["Close"], errors="coerce")
    out["ma50"] = close.rolling(50).mean()
    out["ma150"] = close.rolling(150).mean()
    out["ma200"] = close.rolling(200).mean()
    out["ma220"] = close.rolling(220).mean()
    out["ema10"] = close.ewm(span=10, adjust=False).mean()
    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    out["rsi14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # Weekly RSI (matches the v25 monolith: RSI14 on W-FRI close bars, >=20 bars).
    # Per-row value = latest weekly RSI as of that date (ffill onto the daily index),
    # so the as_of snapshot picks up the monolith-equivalent scalar.
    out["rsi14_weekly"] = np.nan
    if isinstance(out.index, pd.DatetimeIndex):
        weekly = close.resample("W-FRI").last().dropna()
        if len(weekly) >= 20:
            wdelta = weekly.diff()
            wgain = wdelta.clip(lower=0).rolling(14).mean()
            wloss = (-wdelta.clip(upper=0)).rolling(14).mean()
            wrsi = 100 - 100 / (1 + wgain / wloss.replace(0, np.nan))
            out["rsi14_weekly"] = wrsi.reindex(out.index, method="ffill")
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["return_1d"] = close.pct_change(1)
    out["return_2d"] = close.pct_change(2)
    out["return_10d"] = close.pct_change(10)
    out["realized_vol20"] = close.pct_change().rolling(20).std() * math.sqrt(252)
    out["high_60d"] = close.rolling(60).max()
    out["drawdown_60d_high_pct"] = close / out["high_60d"] - 1
    if {"High", "Low", "Close"}.issubset(out.columns):
        high = pd.to_numeric(out["High"], errors="coerce")
        low = pd.to_numeric(out["Low"], errors="coerce")
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        out["atr14"] = tr.rolling(14).mean()
        out["chandelier_exit"] = high.rolling(chandelier_period).max() - atr_multiplier * out["atr14"]
        out["close_location"] = (close - low) / (high - low).replace(0, np.nan)
        body_top = out[["Open", "Close"]].max(axis=1) if "Open" in out.columns else close
        out["upper_shadow_pct"] = (high - body_top) / close
        out["support_60d_low"] = low.shift(1).rolling(60).min()
        out["support_distance_60d_pct"] = close / out["support_60d_low"] - 1.0
    if "Volume" in out.columns:
        volume = pd.to_numeric(out["Volume"], errors="coerce")
        prev_volume = volume.shift(1)
        out["volume_ma20"] = volume.rolling(20).mean()
        out["distribution_day"] = ((out["return_1d"] <= -0.002) & (volume > prev_volume)).astype(int)
        out["distribution_days_25d"] = out["distribution_day"].rolling(25).sum()
        if {"High", "Low", "Close"}.issubset(out.columns):
            high = pd.to_numeric(out["High"], errors="coerce")
            low = pd.to_numeric(out["Low"], errors="coerce")
            typical = (high + low + close) / 3.0
            denom20 = volume.rolling(20).sum().replace(0, np.nan)
            out["vwap20"] = (typical * volume).rolling(20).sum() / denom20
            denom60 = volume.rolling(60).sum().replace(0, np.nan)
            out["avwap_60d"] = (typical * volume).rolling(60).sum() / denom60
            money_flow_multiplier = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
            money_flow_volume = money_flow_multiplier * volume
            out["cmf20"] = money_flow_volume.rolling(20).sum() / denom20
            raw_money_flow = typical * volume
            typical_delta = typical.diff()
            positive_flow = raw_money_flow.where(typical_delta > 0, 0.0).rolling(14).sum()
            negative_flow = raw_money_flow.where(typical_delta < 0, 0.0).abs().rolling(14).sum()
            money_ratio = positive_flow / negative_flow.replace(0, np.nan)
            out["mfi14"] = 100 - 100 / (1 + money_ratio)
            out["ad_line"] = money_flow_volume.fillna(0.0).cumsum()
            out["ad_slope20"] = out["ad_line"].diff(20) / volume.rolling(20).sum().replace(0, np.nan)
    return out


def row_at_or_before(df: pd.DataFrame, as_of: str) -> Optional[pd.Series]:
    if df.empty:
        return None
    idx = df.index[df.index <= pd.Timestamp(as_of)]
    if len(idx) == 0:
        return None
    return df.loc[idx[-1]]
