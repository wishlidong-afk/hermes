"""MarketContext -- multi-symbol × multi-timeframe shared access layer.

Absorbs E7/E16/E17/E18/E19/E20 from the integration architecture.
Provides context-aware signals: regime transitions, weekly alignment,
lead-lag, cross-sectional RS, divergence, VRP/jump.

Dependencies: numpy, pandas (required).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from hermes_escape_top.core.contracts import Field


# ---------------------------------------------------------------------------
# MarketContext class (shared access layer)
# ---------------------------------------------------------------------------

class MarketContext:
    """Multi-symbol daily/weekly price context, no-look-ahead."""

    def __init__(self, as_of: str, store: Dict[str, pd.DataFrame], cfg: Dict[str, Any]):
        self._as_of = pd.Timestamp(as_of)
        self._store = store
        self._cfg = cfg
        self._leader_map = cfg.get("leader_map", {
            "MSTR": "BTC-USD",
            "SOXL": "SOXX",
            "FNGU": "QQQ",
        })

    def daily(self, sym: str) -> pd.DataFrame:
        df = self._store.get(sym, pd.DataFrame())
        if df.empty:
            return df
        return df.loc[df.index <= self._as_of].copy()

    def weekly(self, sym: str) -> pd.DataFrame:
        d = self.daily(sym)
        if d.empty:
            return d
        w = d.resample("W-FRI").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        return w

    def leader_of(self, sym: str) -> Optional[str]:
        return self._leader_map.get(sym)


# ---------------------------------------------------------------------------
# E7: Regime with transition probability
# ---------------------------------------------------------------------------

def regime_with_transition(
    ctx: MarketContext,
    sym: str,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Deterministic regime bucket + near-k-day transition probability.

    Regime labels: LOW_VOL_TREND, NORMAL, HIGH_VOL, CRISIS.
    Transition probability: fraction of recent windows where regime changed.
    """
    d = ctx.daily(sym)
    if d.empty or len(d) < 60:
        return {"regime": "UNKNOWN", "p_transition": 0.0, "confidence": 0.0}

    close = d["close"].values
    ret = np.diff(np.log(close))
    vol_20 = _rolling_std(ret, 20)

    if len(vol_20) == 0:
        return {"regime": "UNKNOWN", "p_transition": 0.0, "confidence": 0.0}

    vol_ann = vol_20[-1] * math.sqrt(252)

    crisis_threshold = float(cfg.get("crisis_vol", 0.50))
    high_vol_threshold = float(cfg.get("high_vol", 0.30))
    low_vol_threshold = float(cfg.get("low_vol", 0.15))

    if vol_ann >= crisis_threshold:
        regime = "CRISIS"
    elif vol_ann >= high_vol_threshold:
        regime = "HIGH_VOL"
    elif vol_ann <= low_vol_threshold:
        regime = "LOW_VOL_TREND"
    else:
        regime = "NORMAL"

    # Transition probability: count regime changes in recent k windows
    k = int(cfg.get("transition_lookback", 20))
    regimes = []
    for t in range(max(0, len(vol_20) - k), len(vol_20)):
        v = vol_20[t] * math.sqrt(252)
        if v >= crisis_threshold:
            regimes.append("CRISIS")
        elif v >= high_vol_threshold:
            regimes.append("HIGH_VOL")
        elif v <= low_vol_threshold:
            regimes.append("LOW_VOL_TREND")
        else:
            regimes.append("NORMAL")

    changes = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i - 1])
    p_transition = changes / max(len(regimes) - 1, 1)

    return {
        "regime": regime,
        "p_transition": round(p_transition, 4),
        "vol_ann": round(vol_ann, 4),
        "confidence": 0.8 if len(d) >= 252 else 0.5,
    }


# ---------------------------------------------------------------------------
# E16: Weekly alignment
# ---------------------------------------------------------------------------

def weekly_alignment(ctx: MarketContext, sym: str) -> Dict[str, Any]:
    """Check if daily and weekly trends are aligned (both bullish or both bearish).

    Upgrade requires daily + weekly same direction.
    """
    d = ctx.daily(sym)
    w = ctx.weekly(sym)
    if d.empty or w.empty or len(d) < 20 or len(w) < 10:
        return {"aligned": False, "daily_trend": "UNKNOWN", "weekly_trend": "UNKNOWN"}

    daily_close = d["close"].values
    daily_ema20 = _ema(daily_close, 20)
    daily_trend = "BULL" if daily_close[-1] > daily_ema20[-1] else "BEAR"

    weekly_close = w["close"].values
    weekly_ema10 = _ema(weekly_close, 10)
    weekly_trend = "BULL" if weekly_close[-1] > weekly_ema10[-1] else "BEAR"

    return {
        "aligned": daily_trend == weekly_trend,
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
    }


# ---------------------------------------------------------------------------
# E17: Lead-lag signal
# ---------------------------------------------------------------------------

def lead_lag_signal(
    ctx: MarketContext,
    leader: str,
    target: str,
    max_lag: int = 5,
) -> Field:
    """Cross-correlation between leader and target at various lags.

    If leader leads (positive lag with highest corr), early warning.
    """
    d_leader = ctx.daily(leader)
    d_target = ctx.daily(target)
    if d_leader.empty or d_target.empty:
        return Field(name="lead_lag", value=None, source=f"{leader}->{target}", as_of=None)

    ret_l = d_leader["close"].pct_change(fill_method=None).dropna()
    ret_t = d_target["close"].pct_change(fill_method=None).dropna()
    common = ret_l.index.intersection(ret_t.index)
    if len(common) < 30:
        return Field(name="lead_lag", value=None, source=f"{leader}->{target}", as_of=None)

    rl = ret_l.loc[common].values
    rt = ret_t.loc[common].values

    best_lag = 0
    best_corr = 0.0
    for lag in range(0, max_lag + 1):
        if lag >= len(rl):
            break
        x = rl[:len(rl) - lag] if lag > 0 else rl
        y = rt[lag:lag + len(x)] if lag > 0 else rt[:len(x)]
        if len(x) < 20:
            continue
        c = _pearson(x, y)
        if abs(c) > abs(best_corr):
            best_corr = c
            best_lag = lag

    return Field(
        name="lead_lag",
        value=round(best_corr, 4),
        source=f"{leader}->{target}@lag{best_lag}",
        as_of=common[-1].date() if len(common) > 0 else None,
    )


# ---------------------------------------------------------------------------
# E18: Cross-sectional relative strength
# ---------------------------------------------------------------------------

def cross_sectional_rs(
    ctx: MarketContext,
    sleeves: List[str],
    window: int = 20,
) -> Dict[str, float]:
    """Rank sleeves by recent relative performance. Returns RS rank [0,1]."""
    perf = {}
    for sym in sleeves:
        d = ctx.daily(sym)
        if d.empty or len(d) < window:
            perf[sym] = 0.0
            continue
        close = d["close"].values
        perf[sym] = (close[-1] / close[-window] - 1.0)

    if not perf:
        return {}

    sorted_syms = sorted(perf, key=lambda s: perf[s])
    n = len(sorted_syms)
    return {s: round(i / max(n - 1, 1), 4) for i, s in enumerate(sorted_syms)}


# ---------------------------------------------------------------------------
# E19: Divergence score
# ---------------------------------------------------------------------------

def divergence_score(
    ctx: MarketContext,
    sym: str,
    confirmers: List[str],
    window: int = 20,
) -> Field:
    """Price makes new high but confirming basket does not → divergence.

    Score in [0,1], 1 = strong divergence (bearish).
    """
    d = ctx.daily(sym)
    if d.empty or len(d) < window:
        return Field(name="divergence", value=None, source=sym, as_of=None)

    close = d["close"].values
    price_new_high = close[-1] >= max(close[-window:])

    if not price_new_high:
        return Field(name="divergence", value=0.0, source=sym, as_of=d.index[-1].date())

    diverging = 0
    total = 0
    for c in confirmers:
        cd = ctx.daily(c)
        if cd.empty or len(cd) < window:
            continue
        total += 1
        cc = cd["close"].values
        if cc[-1] < max(cc[-window:]):
            diverging += 1

    score = diverging / max(total, 1)
    return Field(name="divergence", value=round(score, 4), source=sym, as_of=d.index[-1].date())


# ---------------------------------------------------------------------------
# E20: VRP and jump detection
# ---------------------------------------------------------------------------

def vrp_and_jump(
    ctx: MarketContext,
    sym: str,
    vix_sym: str = "^VIX",
    window: int = 20,
) -> Dict[str, float]:
    """VRP = IV - RV; Jump = max(RV - BV, 0) where BV is bipower variation."""
    d = ctx.daily(sym)
    vix_d = ctx.daily(vix_sym)

    result = {"vrp": 0.0, "jump": 0.0, "rv": 0.0, "iv": 0.0}

    if d.empty or len(d) < window + 1:
        return result

    close = d["close"].values
    ret = np.diff(np.log(close))
    rv = float(np.sqrt(252 * np.mean(ret[-window:] ** 2)))
    result["rv"] = round(rv, 4)

    # Bipower variation (sum of |r_t| * |r_{t-1}|)
    abs_ret = np.abs(ret[-window:])
    if len(abs_ret) >= 2:
        bv = float(np.sqrt(252 * (math.pi / 2) * np.mean(abs_ret[1:] * abs_ret[:-1])))
        result["jump"] = round(max(rv - bv, 0.0), 4)

    if not vix_d.empty and len(vix_d) > 0:
        iv = float(vix_d["close"].values[-1]) / 100.0
        result["iv"] = round(iv, 4)
        result["vrp"] = round(iv - rv, 4)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    if n < window:
        return np.array([float(np.std(arr))]) if n > 1 else np.array([0.0])
    out = np.empty(n - window + 1)
    for i in range(len(out)):
        out[i] = float(np.std(arr[i : i + window], ddof=1))
    return out


def _ema(arr: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = x.mean(), y.mean()
    dx, dy = x - mx, y - my
    denom = math.sqrt(float(np.dot(dx, dx) * np.dot(dy, dy)))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(dx, dy) / denom)
