from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

import pandas as pd

from ..core.data.base import SymbolSnapshot


@dataclass(frozen=True)
class MirrorLegDecision:
    sleeve: str
    risk_symbol: str
    base_symbol: str
    selected_symbol: str
    sleeve_cap: float
    target_weight: float
    cycle: str
    reason: str
    allocations: Dict[str, float] = field(default_factory=dict)
    rule_checks: Dict[str, Optional[bool]] = field(default_factory=dict)
    metrics: Dict[str, Optional[float]] = field(default_factory=dict)
    stop_rules: list[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["sleeve_cap"] = round(float(payload["sleeve_cap"]), 6)
        payload["target_weight"] = round(float(payload["target_weight"]), 6)
        payload["allocations"] = {symbol: round(float(weight), 6) for symbol, weight in sorted(self.allocations.items())}
        payload["metrics"] = {
            key: (round(float(value), 6) if value is not None else None)
            for key, value in sorted(self.metrics.items())
        }
        return payload


def build_mirror_plan(
    snapshots: Dict[str, SymbolSnapshot],
    config: Dict[str, object],
    histories: Optional[Dict[str, pd.DataFrame]] = None,
    as_of: Optional[str] = None,
) -> Dict[str, MirrorLegDecision]:
    histories = histories or {}
    return {
        "FNGU_QQQ": _fngu_qqq_leg(snapshots, histories, as_of, 0.20),
        "SOXL_SOXX": _soxl_soxx_leg(snapshots, histories, as_of, 0.30),
    }


def _fngu_qqq_leg(
    snapshots: Dict[str, SymbolSnapshot],
    histories: Dict[str, pd.DataFrame],
    as_of: Optional[str],
    cap: float,
) -> MirrorLegDecision:
    qqq = snapshots.get("QQQ")
    vix = _value(snapshots, "^VIX", "close")
    if qqq is None:
        return _cash_decision("FNGU_QQQ", "FNGU", "QQQ", cap, "Missing QQQ radar.")
    close = qqq.get("close")
    ema20 = qqq.get("ema20")
    ema50 = qqq.get("ema50")
    rsi14 = qqq.get("rsi14")
    macd = qqq.get("macd")
    macd_signal = qqq.get("macd_signal")
    if None in {close, ema20, ema50, rsi14, macd, macd_signal}:
        return _cash_decision("FNGU_QQQ", "FNGU", "QQQ", cap, "QQQ lacks close/EMA20/EMA50/RSI/MACD.")

    hist = _history_until(histories.get("QQQ"), as_of)
    ret5 = _pct_return(hist, 5)
    volume_ratio = _volume_ratio(hist, 20)
    up3 = _consecutive_up(hist, 3)
    macd_bull = macd > macd_signal
    trend_ok = close > ema20 and close > ema50 and ema20 > ema50
    entry_ok = trend_ok and _ge(ret5, 0.03) and _ge(volume_ratio, 1.2) and _lt(vix, 25) and rsi14 < 70 and macd_bull
    risk_warning = close < ema20 or _gt(vix, 30)

    checks = {
        "QQQ 收盘 > EMA20": close > ema20,
        "QQQ 收盘 > EMA50": close > ema50,
        "EMA20 > EMA50": ema20 > ema50,
        "近5日涨幅 >= 3%": _ge(ret5, 0.03),
        "成交量放大 >= 20%": _ge(volume_ratio, 1.2),
        "VIX < 25": _lt(vix, 25),
        "RSI14 < 70": rsi14 < 70,
        "MACD 多头": macd_bull,
        "连续3日上涨": up3,
        "风险预警: VIX>30 或跌破 EMA20": risk_warning,
    }
    metrics = {
        "QQQ_close": close,
        "QQQ_ema20": ema20,
        "QQQ_ema50": ema50,
        "QQQ_return_5d": ret5,
        "QQQ_volume_ratio_20d": volume_ratio,
        "QQQ_rsi14": rsi14,
        "QQQ_macd": macd,
        "QQQ_macd_signal": macd_signal,
        "VIX": vix,
    }
    if risk_warning:
        return _decision(
            sleeve="FNGU_QQQ",
            risk_symbol="FNGU",
            base_symbol="QQQ",
            cap=cap,
            cycle="RISK_WARNING",
            sleeve_weights={"QQQ": 0.50, "FNGU": 0.0},
            reason="VIX 高于 30 或 QQQ 跌破 EMA20；清 FNGU，仅保留 QQQ 防守仓。",
            checks=checks,
            metrics=metrics,
            stop_rules=_fngu_stop_rules(),
        )
    if entry_ok and up3:
        return _decision(
            sleeve="FNGU_QQQ",
            risk_symbol="FNGU",
            base_symbol="QQQ",
            cap=cap,
            cycle="STRONG_TREND",
            sleeve_weights={"QQQ": 0.60, "FNGU": 0.50},
            reason="QQQ 满足入场共振并连续 3 日上涨；执行强趋势杠杆配置。",
            checks=checks,
            metrics=metrics,
            stop_rules=_fngu_stop_rules(),
        )
    if trend_ok and _lt(vix, 25) and rsi14 < 70 and macd_bull:
        return _decision(
            sleeve="FNGU_QQQ",
            risk_symbol="FNGU",
            base_symbol="QQQ",
            cap=cap,
            cycle="WEAK_TREND",
            sleeve_weights={"QQQ": 0.70, "FNGU": 0.20},
            reason="QQQ 趋势仍在，但动能/量能未达到强趋势；使用弱趋势配置。",
            checks=checks,
            metrics=metrics,
            stop_rules=_fngu_stop_rules(),
        )
    return _decision(
        sleeve="FNGU_QQQ",
        risk_symbol="FNGU",
        base_symbol="QQQ",
        cap=cap,
        cycle="CHOP",
        sleeve_weights={"QQQ": 0.80, "FNGU": 0.0},
        reason="均线/动能未形成明确方向；震荡市禁止长持 FNGU。",
        checks=checks,
        metrics=metrics,
        stop_rules=_fngu_stop_rules(),
    )


def _soxl_soxx_leg(
    snapshots: Dict[str, SymbolSnapshot],
    histories: Dict[str, pd.DataFrame],
    as_of: Optional[str],
    cap: float,
) -> MirrorLegDecision:
    soxx = snapshots.get("SOXX")
    vix = _value(snapshots, "^VIX", "close")
    if soxx is None:
        return _cash_decision("SOXL_SOXX", "SOXL", "SOXX", cap, "Missing SOXX radar.")
    close = soxx.get("close")
    ema50 = soxx.get("ema50")
    ma200 = soxx.get("ma200")
    rsi14 = soxx.get("rsi14")
    macd = soxx.get("macd")
    macd_signal = soxx.get("macd_signal")
    if None in {close, ema50, ma200, rsi14, macd, macd_signal}:
        return _cash_decision("SOXL_SOXX", "SOXL", "SOXX", cap, "SOXX lacks close/EMA50/MA200/RSI/MACD.")

    soxx_hist = _history_until(histories.get("SOXX"), as_of)
    spy_hist = _history_until(histories.get("SPY"), as_of)
    ret10 = _pct_return(soxx_hist, 10)
    volume_ratio = _volume_ratio(soxx_hist, 20)
    rs20 = _relative_strength(soxx_hist, spy_hist, 20)
    up5 = _consecutive_up(soxx_hist, 5)
    below_ema50_3 = _below_level_days(soxx_hist, ema50, 3)
    macd_bull = macd > macd_signal
    large_reversal = _large_reversal(soxx_hist)
    entry_ok = close > ema50 and close > ma200 and ema50 > ma200 and _ge(ret10, 0.08) and _ge(volume_ratio, 1.3) and _gt(rs20, 1.1) and rsi14 < 75 and macd_bull
    risk_warning = _gt(vix, 30) or large_reversal

    checks = {
        "SOXX 收盘 > EMA50": close > ema50,
        "SOXX 收盘 > MA200": close > ma200,
        "EMA50 > MA200": ema50 > ma200,
        "近10日涨幅 >= 8%": _ge(ret10, 0.08),
        "成交量放大 >= 30%": _ge(volume_ratio, 1.3),
        "相对 SPY 强弱 RS > 1.1": _gt(rs20, 1.1),
        "RSI14 < 75": rsi14 < 75,
        "MACD 金叉/多头": macd_bull,
        "连续5日上涨": up5,
        "衰退: 跌破 EMA50 且3日未收回": below_ema50_3,
        "逃顶: 高开低走大K且放量2倍": large_reversal,
        "逃顶: VIX > 30": _gt(vix, 30),
    }
    metrics = {
        "SOXX_close": close,
        "SOXX_ema50": ema50,
        "SOXX_ma200": ma200,
        "SOXX_return_10d": ret10,
        "SOXX_volume_ratio_20d": volume_ratio,
        "SOXX_rs20_vs_spy": rs20,
        "SOXX_rsi14": rsi14,
        "SOXX_macd": macd,
        "SOXX_macd_signal": macd_signal,
        "VIX": vix,
    }
    if below_ema50_3:
        return _decision(
            sleeve="SOXL_SOXX",
            risk_symbol="SOXL",
            base_symbol="SOXX",
            cap=cap,
            cycle="DECLINE",
            sleeve_weights={"SOXX": 0.30, "SOXL": 0.0},
            reason="SOXX 跌破 EMA50 且 3 日未收回；清 SOXL，SOXX 降至防御仓。",
            checks=checks,
            metrics=metrics,
            stop_rules=_soxl_stop_rules(),
        )
    if risk_warning:
        return _decision(
            sleeve="SOXL_SOXX",
            risk_symbol="SOXL",
            base_symbol="SOXX",
            cap=cap,
            cycle="RISK_WARNING",
            sleeve_weights={"SOXX": 1.0, "SOXL": 0.0},
            reason="VIX 或高开低走放量 K 线触发逃顶警报；清 SOXL，保留 SOXX。",
            checks=checks,
            metrics=metrics,
            stop_rules=_soxl_stop_rules(),
        )
    if entry_ok and up5:
        return _decision(
            sleeve="SOXL_SOXX",
            risk_symbol="SOXL",
            base_symbol="SOXX",
            cap=cap,
            cycle="STRONG_BOOM",
            sleeve_weights={"SOXX": 0.40, "SOXL": 0.60},
            reason="SOXX 满足繁荣周期共振并连续 5 日上涨；执行强繁荣配置。",
            checks=checks,
            metrics=metrics,
            stop_rules=_soxl_stop_rules(),
        )
    if close > ema50 and close > ma200 and ema50 > ma200 and rsi14 < 75 and macd_bull:
        return _decision(
            sleeve="SOXL_SOXX",
            risk_symbol="SOXL",
            base_symbol="SOXX",
            cap=cap,
            cycle="WEAK_BOOM",
            sleeve_weights={"SOXX": 0.50, "SOXL": 0.50},
            reason="SOXX 长趋势向上但量价强度不足；执行弱繁荣均衡配置。",
            checks=checks,
            metrics=metrics,
            stop_rules=_soxl_stop_rules(),
        )
    return _decision(
        sleeve="SOXL_SOXX",
        risk_symbol="SOXL",
        base_symbol="SOXX",
        cap=cap,
        cycle="CHOP",
        sleeve_weights={"SOXX": 1.0, "SOXL": 0.0},
        reason="均线缠绕或趋势强度不足；震荡周期清 SOXL，仅持 SOXX。",
        checks=checks,
        metrics=metrics,
        stop_rules=_soxl_stop_rules(),
    )


def _decision(
    sleeve: str,
    risk_symbol: str,
    base_symbol: str,
    cap: float,
    cycle: str,
    sleeve_weights: Dict[str, float],
    reason: str,
    checks: Dict[str, Optional[bool]],
    metrics: Dict[str, Optional[float]],
    stop_rules: list[str],
) -> MirrorLegDecision:
    allocations = {
        symbol: round(max(0.0, float(weight)) * cap, 8)
        for symbol, weight in sleeve_weights.items()
        if max(0.0, float(weight)) > 0
    }
    target_weight = round(sum(allocations.values()), 8)
    selected = _primary_symbol(allocations, risk_symbol, base_symbol)
    return MirrorLegDecision(
        sleeve=sleeve,
        risk_symbol=risk_symbol,
        base_symbol=base_symbol,
        selected_symbol=selected,
        sleeve_cap=cap,
        target_weight=target_weight,
        cycle=cycle,
        reason=reason,
        allocations=allocations,
        rule_checks=checks,
        metrics=metrics,
        stop_rules=stop_rules,
    )


def _cash_decision(sleeve: str, risk_symbol: str, base_symbol: str, cap: float, reason: str) -> MirrorLegDecision:
    return MirrorLegDecision(
        sleeve=sleeve,
        risk_symbol=risk_symbol,
        base_symbol=base_symbol,
        selected_symbol="BOXX",
        sleeve_cap=cap,
        target_weight=cap,
        cycle="CASH",
        reason=reason,
        allocations={"BOXX": cap},
        rule_checks={},
        metrics={},
        stop_rules=[],
    )


def _primary_symbol(allocations: Dict[str, float], risk_symbol: str, base_symbol: str) -> str:
    if allocations.get(risk_symbol, 0.0) > 0:
        return risk_symbol
    if allocations.get(base_symbol, 0.0) > 0:
        return base_symbol
    if allocations.get("BOXX", 0.0) > 0:
        return "BOXX"
    return max(allocations, key=allocations.get) if allocations else "BOXX"


def _fngu_stop_rules() -> list[str]:
    return [
        "FNGU 单笔亏损 >= 8%：强制止损。",
        "QQQ 跌破 EMA20：清 FNGU，QQQ 降至风险预警配置。",
        "FNGU 盈利 15% 减 50%，盈利 25% 清仓。",
        "QQQ 盈利 8% 减 30%，盈利 15% 减 50%。",
        "FNGU 单次持仓不超过 15 个交易日。",
        "禁止在震荡市长持 FNGU；重大数据前避免重仓。",
    ]


def _soxl_stop_rules() -> list[str]:
    return [
        "SOXL 单笔亏损 >= 15%：强制止损。",
        "SOXX 跌破 EMA50：清 SOXL，SOXX 降仓。",
        "SOXL 盈利 30% 减 50%，盈利 50% 清仓。",
        "SOXX 盈利 15% 减 30%，盈利 25% 减 50%。",
        "SOXL 单次持仓不超过 20 个交易日。",
        "高开低走大 K + 成交量 2 倍、VIX 飙升、PE 分位>80% 时执行逃顶审计；PE 分位当前未接入。",
    ]


def _value(snapshots: Dict[str, SymbolSnapshot], symbol: str, field_name: str) -> Optional[float]:
    snap = snapshots.get(symbol)
    return snap.get(field_name) if snap else None


def _history_until(history: Optional[pd.DataFrame], as_of: Optional[str]) -> pd.DataFrame:
    if history is None or history.empty:
        return pd.DataFrame()
    if as_of is None:
        return history.copy()
    return history.loc[history.index <= pd.Timestamp(str(as_of)[:10])].copy()


def _pct_return(history: pd.DataFrame, days: int) -> Optional[float]:
    if history.empty or "Close" not in history.columns or len(history) <= days:
        return None
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if len(close) <= days or close.iloc[-days - 1] <= 0:
        return None
    return float(close.iloc[-1] / close.iloc[-days - 1] - 1.0)


def _volume_ratio(history: pd.DataFrame, window: int) -> Optional[float]:
    if history.empty or "Volume" not in history.columns or len(history) < window + 1:
        return None
    volume = pd.to_numeric(history["Volume"], errors="coerce").dropna()
    if len(volume) < window + 1:
        return None
    avg = float(volume.iloc[-window - 1 : -1].mean())
    if avg <= 0:
        return None
    return float(volume.iloc[-1] / avg)


def _consecutive_up(history: pd.DataFrame, days: int) -> bool:
    if history.empty or "Close" not in history.columns or len(history) < days + 1:
        return False
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().tail(days + 1)
    if len(close) < days + 1:
        return False
    return bool((close.diff().dropna() > 0).all())


def _below_level_days(history: pd.DataFrame, level: Optional[float], days: int) -> bool:
    if level is None or history.empty or "Close" not in history.columns or len(history) < days:
        return False
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().tail(days)
    if len(close) < days:
        return False
    return bool((close < float(level)).all())


def _relative_strength(left: pd.DataFrame, right: pd.DataFrame, days: int) -> Optional[float]:
    lret = _pct_return(left, days)
    rret = _pct_return(right, days)
    if lret is None or rret is None or 1.0 + rret <= 0:
        return None
    return float((1.0 + lret) / (1.0 + rret))


def _large_reversal(history: pd.DataFrame) -> bool:
    if history.empty or len(history) < 21 or not {"Open", "High", "Close", "Volume"}.issubset(history.columns):
        return False
    row = history.iloc[-1]
    prev = history.iloc[-2]
    volume_ratio = _volume_ratio(history, 20)
    try:
        high_open = float(row["Open"]) > float(prev["Close"]) * 1.01
        bearish = float(row["Close"]) < float(row["Open"])
        wide_bar = (float(row["High"]) - float(row["Close"])) / float(row["Close"]) >= 0.02
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    return bool(high_open and bearish and wide_bar and _ge(volume_ratio, 2.0))


def _ge(value: Optional[float], threshold: float) -> bool:
    return value is not None and value >= threshold


def _gt(value: Optional[float], threshold: float) -> bool:
    return value is not None and value > threshold


def _lt(value: Optional[float], threshold: float) -> bool:
    return value is not None and value < threshold
