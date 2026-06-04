from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional

import pandas as pd

from ..data.base import SymbolSnapshot
from ..features.indicators import indicator_frame
from ..scoring.result import ScoreResult


SELL_OR_LOCK_STATUSES = {"TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"}


@dataclass(frozen=True)
class ReentryPlan:
    symbol: str
    eligible: bool
    tranche: str
    allocation_fraction: float
    locked_reason: str
    explain: list[str]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["allocation_fraction"] = round(float(payload["allocation_fraction"]), 6)
        return payload


def build_reentry_plan(
    symbol: str,
    score: ScoreResult,
    snapshots: Dict[str, SymbolSnapshot],
    histories: Dict[str, pd.DataFrame],
    config: Dict[str, object],
    days_since_last_sell: int = 0,
    t1_active: bool = False,
    t2_active: bool = False,
) -> ReentryPlan:
    reentry_cfg = config.get("reentry", {}) if isinstance(config.get("reentry", {}), dict) else {}
    time_lock = int(reentry_cfg.get("time_lock_days", 11))
    score_unlock = float(reentry_cfg.get("score_unlock", 19))
    c_unlock = float(reentry_cfg.get("c_module_unlock", 5))
    tranches = list(reentry_cfg.get("tranches", [0.30, 0.30, 0.40]))

    if score.hard_valve_hits or score.status in SELL_OR_LOCK_STATUSES:
        return _locked(symbol, "active_sell_or_hard_valve", ["Sell signal or hard valve is active; reentry is locked."])
    if days_since_last_sell < time_lock:
        return _locked(symbol, "time_lock", [f"Days since last sell {days_since_last_sell} < required {time_lock}."])
    if score.final_score >= score_unlock:
        return _locked(symbol, "score_lock", [f"Final score {score.final_score:.2f} >= unlock threshold {score_unlock:.2f}."])
    if score.module_scores.get("C", 0.0) >= c_unlock or score.module_scores.get("D", 0.0) >= c_unlock:
        return _locked(symbol, "structure_lock", ["C/D module risk has not cleared."])

    radar = _radar_symbol(symbol)
    radar_snap = snapshots.get(radar)
    if radar_snap is None:
        return _locked(symbol, "missing_radar", [f"Radar snapshot {radar} is missing."])

    close = radar_snap.get("close")
    ema20 = radar_snap.get("ema20")
    macd = radar_snap.get("macd")
    signal = radar_snap.get("macd_signal")
    if close is None or ema20 is None or macd is None or signal is None:
        return _locked(symbol, "missing_indicator", [f"Radar {radar} lacks close/EMA20/MACD fields."])

    if not t1_active:
        if close > ema20 and macd > signal and (macd <= 0 or abs(macd / close) <= 0.01):
            return ReentryPlan(symbol, True, "T1", float(tranches[0]), "", [f"{radar} close>EMA20 and MACD crossed up near zero."])
        return _locked(symbol, "await_t1", [f"{radar} has not triggered T1 recon entry."])

    if t1_active and not t2_active:
        prior_high = _prior_high_close(histories.get(radar), radar_snap.as_of.isoformat(), 20)
        if prior_high is not None and close > prior_high and close > ema20:
            return ReentryPlan(symbol, True, "T2", float(tranches[1]), "", [f"{radar} broke prior 20D high close."])
        return _locked(symbol, "await_t2", [f"{radar} has not broken prior 20D high close."])

    if t2_active and _market_one_year_high(snapshots, histories):
        return ReentryPlan(symbol, True, "T3", float(tranches[2]), "", ["QQQ/SPY confirmed 252D high; T3 enabled."])
    return _locked(symbol, "reserve_t3", ["T1/T2 active but T3 reserve remains parked until market 252D high."])


def _locked(symbol: str, reason: str, explain: list[str]) -> ReentryPlan:
    return ReentryPlan(symbol=symbol, eligible=False, tranche="LOCKED", allocation_fraction=0.0, locked_reason=reason, explain=explain)


def _radar_symbol(symbol: str) -> str:
    if symbol == "SOXL":
        return "SOXX"
    if symbol == "FNGU":
        return "QQQ"
    return symbol


def _prior_high_close(frame: Optional[pd.DataFrame], as_of: str, window: int) -> Optional[float]:
    if frame is None or frame.empty or "Close" not in frame.columns:
        return None
    local = frame.loc[frame.index < pd.Timestamp(as_of)].tail(window)
    if len(local) < window:
        return None
    return float(local["Close"].max())


def _market_one_year_high(snapshots: Dict[str, SymbolSnapshot], histories: Dict[str, pd.DataFrame]) -> bool:
    for symbol in ["QQQ", "SPY"]:
        snap = snapshots.get(symbol)
        frame = histories.get(symbol)
        if snap is None or frame is None or frame.empty or "Close" not in frame.columns:
            continue
        prior = _prior_high_close(indicator_frame(frame), snap.as_of.isoformat(), 252)
        close = snap.get("close")
        if prior is not None and close is not None and close >= prior:
            return True
    return False
