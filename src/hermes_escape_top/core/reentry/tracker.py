"""Reentry State Tracker -- persistent 3-3-4 tranche state management.

Manages T1/T2/T3 tranche lifecycle: locked → scouting → confirmed → full.
Three-lock gate: time_lock(11d) + sentiment_lock(<19) + structure_lock(C<5, divergence cleared).
Any active sell signal or hard-valve forces re-lock.

State is serializable to JSON for persistence across sessions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class TrancheState:
    symbol: str
    phase: str          # LOCKED, T1_ELIGIBLE, T1_ACTIVE, T2_ELIGIBLE, T2_ACTIVE, T3_ELIGIBLE, T3_ACTIVE
    last_sell_date: Optional[str] = None
    t1_entry_date: Optional[str] = None
    t1_entry_price: Optional[float] = None
    t2_entry_date: Optional[str] = None
    t2_entry_price: Optional[float] = None
    t3_entry_date: Optional[str] = None
    t3_entry_price: Optional[float] = None
    lock_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TrancheState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LockCheck:
    time_lock_clear: bool
    sentiment_lock_clear: bool
    structure_lock_clear: bool
    all_clear: bool
    reasons: List[str]


def check_three_locks(
    state: TrancheState,
    as_of: date,
    total_score: float,
    c_score: float,
    divergence_active: bool,
    has_sell_signal: bool,
    has_hard_valve: bool,
    cfg: Dict[str, Any],
) -> LockCheck:
    """Check the three-lock gate for reentry eligibility.

    Locks:
      1. Time: >= 11 trading days since last sell
      2. Sentiment: total_score < 19
      3. Structure: C < 5 and divergence cleared

    Active sell signal or hard valve forces lock regardless.
    """
    min_days = int(cfg.get("reentry_time_lock_days", 11))
    sentiment_threshold = float(cfg.get("reentry_sentiment_threshold", 19))
    c_threshold = float(cfg.get("reentry_c_threshold", 5))

    reasons = []

    # Force lock on active signals
    if has_sell_signal:
        reasons.append("active sell signal forces lock")
        return LockCheck(False, False, False, False, reasons)
    if has_hard_valve:
        reasons.append("hard valve forces lock")
        return LockCheck(False, False, False, False, reasons)

    # Time lock
    time_clear = False
    if state.last_sell_date is not None:
        last_sell = date.fromisoformat(state.last_sell_date)
        days_since = _business_days_between(last_sell, as_of)
        if days_since >= min_days:
            time_clear = True
        else:
            reasons.append(f"time lock: {days_since}/{min_days} trading days")
    else:
        time_clear = True

    # Sentiment lock
    sentiment_clear = total_score < sentiment_threshold
    if not sentiment_clear:
        reasons.append(f"sentiment lock: score {total_score} >= {sentiment_threshold}")

    # Structure lock
    c_clear = c_score < c_threshold
    div_clear = not divergence_active
    structure_clear = c_clear and div_clear
    if not c_clear:
        reasons.append(f"structure lock: C={c_score} >= {c_threshold}")
    if not div_clear:
        reasons.append("structure lock: divergence still active")

    all_clear = time_clear and sentiment_clear and structure_clear
    return LockCheck(time_clear, sentiment_clear, structure_clear, all_clear, reasons)


def advance_tranche(
    state: TrancheState,
    lock_check: LockCheck,
    as_of: date,
    radar_price: float,
    radar_ema20: float,
    radar_macd_cross: bool,
    radar_20d_high: float,
    benchmark_new_high: bool,
    cfg: Dict[str, Any],
) -> TrancheState:
    """Advance tranche state based on lock check and market conditions.

    T1 (30%): radar > EMA20 + MACD golden cross near zero
    T2 (30%): T1 profitable + radar breaks 20d high + above EMA20
    T3 (40%): T1/T2 profitable + benchmark (QQQ/SPY) 252d new high
    """
    if not lock_check.all_clear:
        return TrancheState(
            symbol=state.symbol,
            phase="LOCKED",
            last_sell_date=state.last_sell_date,
            lock_reasons=lock_check.reasons,
        )

    phase = state.phase

    # T1 eligibility
    if phase in ("LOCKED", "T1_ELIGIBLE"):
        t1_ok = radar_price > radar_ema20 and radar_macd_cross
        if t1_ok:
            return TrancheState(
                symbol=state.symbol,
                phase="T1_ACTIVE",
                last_sell_date=state.last_sell_date,
                t1_entry_date=as_of.isoformat(),
                t1_entry_price=radar_price,
            )
        return TrancheState(
            symbol=state.symbol,
            phase="T1_ELIGIBLE",
            last_sell_date=state.last_sell_date,
            lock_reasons=["T1: waiting for radar > EMA20 + MACD cross"],
        )

    # T2 eligibility
    if phase == "T1_ACTIVE":
        t1_profitable = state.t1_entry_price is not None and radar_price > state.t1_entry_price
        t2_ok = t1_profitable and radar_price >= radar_20d_high and radar_price > radar_ema20
        if t2_ok:
            return TrancheState(
                symbol=state.symbol,
                phase="T2_ACTIVE",
                last_sell_date=state.last_sell_date,
                t1_entry_date=state.t1_entry_date,
                t1_entry_price=state.t1_entry_price,
                t2_entry_date=as_of.isoformat(),
                t2_entry_price=radar_price,
            )
        return state

    # T3 eligibility
    if phase == "T2_ACTIVE":
        t1_ok = state.t1_entry_price is not None and radar_price > state.t1_entry_price
        t2_ok = state.t2_entry_price is not None and radar_price > state.t2_entry_price
        t3_ok = t1_ok and t2_ok and benchmark_new_high
        if t3_ok:
            return TrancheState(
                symbol=state.symbol,
                phase="T3_ACTIVE",
                last_sell_date=state.last_sell_date,
                t1_entry_date=state.t1_entry_date,
                t1_entry_price=state.t1_entry_price,
                t2_entry_date=state.t2_entry_date,
                t2_entry_price=state.t2_entry_price,
                t3_entry_date=as_of.isoformat(),
                t3_entry_price=radar_price,
            )
        return state

    return state


def serialize_states(states: Dict[str, TrancheState]) -> str:
    return json.dumps({s: st.to_dict() for s, st in states.items()}, indent=2)


def deserialize_states(data: str) -> Dict[str, TrancheState]:
    raw = json.loads(data)
    return {s: TrancheState.from_dict(d) for s, d in raw.items()}


def _business_days_between(start: date, end: date) -> int:
    count = 0
    current = start + timedelta(days=1)
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count
