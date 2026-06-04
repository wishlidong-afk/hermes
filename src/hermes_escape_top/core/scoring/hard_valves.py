from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Optional

import pandas as pd

from ..data.base import SymbolSnapshot
from ..features.indicators import indicator_frame


@dataclass(frozen=True)
class HardValveResult:
    triggered: bool
    ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)

    def to_dict(self) -> dict[str, object]:
        return {"triggered": self.triggered, "ids": self.ids, "reason": self.reason}


def evaluate_hard_valves(
    symbol: str,
    snapshots: Dict[str, SymbolSnapshot],
    total_score: float = 0.0,
    c_score: float = 0.0,
    histories: Optional[Dict[str, pd.DataFrame]] = None,
) -> HardValveResult:
    histories = histories or {}
    ids: list[str] = []
    reasons: list[str] = []
    close = _v(snapshots, symbol, "close")
    ma200 = _v(snapshots, symbol, "ma200")
    ema10 = _v(snapshots, symbol, "ema10")
    ema20 = _v(snapshots, symbol, "ema20")
    ema50 = _v(snapshots, symbol, "ema50")
    chandelier = _v(snapshots, symbol, "chandelier_exit")
    drawdown = _v(snapshots, symbol, "drawdown_60d_high_pct")
    r1 = _v(snapshots, symbol, "return_1d")
    r2 = _v(snapshots, symbol, "return_2d")
    as_of = snapshots[symbol].as_of.isoformat() if symbol in snapshots else None

    if symbol == "MSTR":
        if _lte(close, ma200):
            ids.append("H-M1")
            reasons.append("MSTR close <= MA200")
        if r1 is not None and r1 <= -0.15 and close is not None and ema10 is not None and close < ema10:
            ids.append("H-M2")
            reasons.append("MSTR <= -15% and below EMA10")
        if r2 is not None and r2 <= -0.22:
            ids.append("H-M3")
            reasons.append("MSTR 2d <= -22%")
        if _lt(_v(snapshots, "BTC-USD", "close"), _v(snapshots, "BTC-USD", "ma50")) and _below_ema_days(
            "MSTR", histories, as_of, "ema20", 2
        ):
            ids.append("H-M4")
            reasons.append("BTC below MA50 and MSTR two days below EMA20")
        if total_score >= 80 and c_score >= 5:
            ids.append("H-M5")
            reasons.append("TotalScore>=80 with technical trigger")
        if _trailing_stop(close, chandelier, ema20, drawdown, -0.18):
            ids.append("H-M6")
            reasons.append("MSTR 22d Chandelier 4.5x ATR trailing stop breached after 18% peak drawdown")

    elif symbol == "FNGU":
        if _lte(_v(snapshots, "QQQ", "close"), _v(snapshots, "QQQ", "ma200")):
            ids.append("H-F1")
            reasons.append("QQQ close <= MA200")
        if _lte(_radar_value(snapshots, ["FNGS", "^NYFANG"], "close"), _radar_value(snapshots, ["FNGS", "^NYFANG"], "ma200")):
            ids.append("H-F2")
            reasons.append("FNGS/NYFANG close <= MA200")
        if r1 is not None and r1 <= -0.15:
            ids.append("H-F3")
            reasons.append("FNGU daily <= -15%")
        if r2 is not None and r2 <= -0.22:
            ids.append("H-F4")
            reasons.append("FNGU 2d <= -22%")
        if _below_ema_days("QQQ", histories, as_of, "ema50", 3) or _below_ema_days_any(["FNGS", "^NYFANG"], histories, as_of, "ema50", 3):
            ids.append("H-F5")
            reasons.append("QQQ or FNGS/NYFANG three days below EMA50")
        if _trailing_stop(close, chandelier, ema20, drawdown, -0.12):
            ids.append("H-F6")
            reasons.append("FNGU 22d Chandelier 4.5x ATR trailing stop breached after 12% peak drawdown")
        if _macro_curve_stress(snapshots):
            ids.append("H-F7")
            reasons.append("QQQ below EMA50 with 5+ distribution days and VIX curve stress")

    elif symbol == "SOXL":
        if _lte(_v(snapshots, "QQQ", "close"), _v(snapshots, "QQQ", "ma200")):
            ids.append("H-S1")
            reasons.append("QQQ close <= MA200")
        if _lte(_radar_value(snapshots, ["SOXX", "SMH", "^SOX"], "close"), _radar_value(snapshots, ["SOXX", "SMH", "^SOX"], "ma200")):
            ids.append("H-S2")
            reasons.append("SOXX/SMH/SOX close <= MA200")
        if r1 is not None and r1 <= -0.15:
            ids.append("H-S3")
            reasons.append("SOXL daily <= -15%")
        if r2 is not None and r2 <= -0.22:
            ids.append("H-S4")
            reasons.append("SOXL 2d <= -22%")
        if _below_ema_days_any(["SOXX", "SMH"], histories, as_of, "ema50", 3):
            ids.append("H-S5")
            reasons.append("SOXX/SMH three days below EMA50")
        if drawdown is not None and drawdown <= -0.25 and close is not None and ema50 is not None and close < ema50:
            ids.append("H-S6")
            reasons.append("SOXL 60d peak drawdown <= -25% and close below EMA50")
        if _trailing_stop(close, chandelier, ema20, drawdown, -0.12):
            ids.append("H-S7")
            reasons.append("SOXL 22d Chandelier 4.5x ATR trailing stop breached after 12% peak drawdown")
        if _macro_curve_stress(snapshots):
            ids.append("H-S8")
            reasons.append("QQQ below EMA50 with 5+ distribution days and VIX curve stress")

    return HardValveResult(triggered=bool(ids), ids=ids, reasons=reasons)


def _v(snapshots: Dict[str, SymbolSnapshot], symbol: str, field: str) -> Optional[float]:
    snap = snapshots.get(symbol)
    return None if snap is None else snap.get(field)


def _lte(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and left <= right


def _lt(left: Optional[float], right: Optional[float]) -> bool:
    return left is not None and right is not None and left < right


def _radar_value(snapshots: Dict[str, SymbolSnapshot], symbols: Iterable[str], field: str) -> Optional[float]:
    for symbol in symbols:
        value = _v(snapshots, symbol, field)
        if value is not None:
            return value
    return None


def _trailing_stop(
    close: Optional[float],
    chandelier: Optional[float],
    ema20: Optional[float],
    drawdown: Optional[float],
    threshold: float,
) -> bool:
    return (
        close is not None
        and chandelier is not None
        and ema20 is not None
        and drawdown is not None
        and close < chandelier
        and close < ema20
        and drawdown <= threshold
    )


def _below_ema_days_any(
    symbols: Iterable[str],
    histories: Dict[str, pd.DataFrame],
    as_of: Optional[str],
    ema_col: str,
    days: int,
) -> bool:
    return any(_below_ema_days(symbol, histories, as_of, ema_col, days) for symbol in symbols)


def _below_ema_days(
    symbol: str,
    histories: Dict[str, pd.DataFrame],
    as_of: Optional[str],
    ema_col: str,
    days: int,
) -> bool:
    frame = histories.get(symbol)
    if frame is None or frame.empty or as_of is None:
        return False
    local = frame.copy()
    if ema_col not in local.columns:
        local = indicator_frame(local)
    if "Close" not in local.columns or ema_col not in local.columns:
        return False
    local = local.loc[local.index <= pd.Timestamp(as_of)].tail(days)
    if len(local) < days:
        return False
    return bool((local["Close"] < local[ema_col]).all())


def _macro_curve_stress(snapshots: Dict[str, SymbolSnapshot]) -> bool:
    qqq_close = _v(snapshots, "QQQ", "close")
    qqq_ema50 = _v(snapshots, "QQQ", "ema50")
    qdist25 = _v(snapshots, "QQQ", "distribution_days_25d")
    vix = _v(snapshots, "^VIX", "close")
    vix3m = _v(snapshots, "^VIX3M", "close")
    ratio = vix / vix3m if vix is not None and vix3m else None
    return (
        qqq_close is not None
        and qqq_ema50 is not None
        and qdist25 is not None
        and ratio is not None
        and qqq_close < qqq_ema50
        and qdist25 >= 5
        and ratio >= 0.96
    )
