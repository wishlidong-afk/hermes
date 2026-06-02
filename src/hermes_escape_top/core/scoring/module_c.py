from __future__ import annotations

from .registry import FactorContext, FactorDefinition


def module_c_factors() -> list[FactorDefinition]:
    return [
        FactorDefinition("C10_MACRO_TREND_STRUCTURE", "C", 10.0, ["close", "ema50", "ma50", "ma150", "ma200"], _macro_trend_structure),
        FactorDefinition("C6_SHARP_DROP", "C", 5.0, ["return_2d"], _sharp_drop, "C6"),
        FactorDefinition(
            "C7_AVWAP_PLATFORM_SUPPORT",
            "C",
            4.0,
            ["close", "avwap_anchored_20d", "support_20d_low"],
            _avwap_platform_support,
            "C7 AVWAP/platform support",
        ),
        FactorDefinition("C8_DISTRIBUTION_PRESSURE", "C", 4.0, ["distribution_days_25d"], _distribution_pressure, "C8"),
        FactorDefinition("C9_CHANDELIER_BREAK", "C", 5.0, ["close", "chandelier_exit"], _chandelier_break),
        FactorDefinition("C11_MA220_REBUILD_GAP", "C", 4.0, ["close", "ma220"], _ma220_gap),
        FactorDefinition("C12_VOL_EXPANSION", "C", 4.0, ["realized_vol20"], _vol_expansion),
    ]


def _macro_trend_structure(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("close")
    ema50 = ctx.get("ema50")
    ma50 = ctx.get("ma50")
    ma150 = ctx.get("ma150")
    ma200 = ctx.get("ma200")
    score = 0.0
    parts: list[str] = []
    if close < ema50:
        score += 3.0
        parts.append("close<EMA50")
    minervini_ok = close > ma50 > ma150 > ma200
    if not minervini_ok:
        score += 4.0
        parts.append("Minervini structure broken")
    if close < ma150 or close < ma200:
        score += 3.0
        parts.append("Weinstein 150/200D support broken")
    if not parts:
        return 0.0, "Macro trend structure intact"
    return min(score, 10.0), "; ".join(parts)


def _sharp_drop(ctx: FactorContext) -> tuple[float, str]:
    """C6 — per-symbol thresholds aligned with v25 monolith.

    MSTR moves faster; tighter triggers required to catch early-stage drops.
    FNGU/SOXL: standard leveraged-ETF thresholds.
    """
    ret = ctx.get("return_2d")
    if ctx.symbol == "MSTR":
        if ret <= -0.12:
            return 5.0, f"MSTR 2-day sharp drop: {ret:.1%}"
        if ret <= -0.06:
            return 3.0, f"MSTR 2-day drop elevated: {ret:.1%}"
        return 0.0, f"MSTR 2-day drop normal: {ret:.1%}"
    else:
        if ret <= -0.22:
            return 5.0, f"2-day sharp drop: {ret:.1%}"
        if ret <= -0.15:
            return 3.0, f"2-day drop elevated: {ret:.1%}"
        if ret <= -0.08:
            return 1.0, f"2-day drop watch: {ret:.1%}"
        return 0.0, f"2-day drop normal: {ret:.1%}"


def _avwap_platform_support(ctx: FactorContext) -> tuple[float, str]:
    """C7 — peak-anchored AVWAP (20-bar high anchor) + 20-bar support low.

    Aligned with v25 monolith's estimated_avwap_20d + platform_support_level.
    The 60-day equivalents (avwap_60d, support_60d_low) use a longer window that
    can miss near-term support breaks. The 20-bar anchor follows the most recent
    swing-high, matching how traders monitor AVWAP in practice.
    """
    close = ctx.get("close")
    avwap = ctx.get("avwap_anchored_20d")
    support = ctx.get("support_20d_low")
    if close is None:
        return 0.0, "C7 close missing"
    parts: list[str] = []
    score = 0.0
    if support is not None and close < support:
        score = max(score, 4.0)
        parts.append(f"broke 20D support {support:.2f}")
    if avwap is not None and close < avwap:
        score = max(score, 2.0)
        parts.append(f"below peak-anchored AVWAP {avwap:.2f}")
    if not parts:
        avwap_str = f"{avwap:.2f}" if avwap is not None else "n/a"
        return 0.0, f"holds AVWAP/support (avwap={avwap_str})"
    return min(score, 4.0), "C7: " + "; ".join(parts)


def _distribution_pressure(ctx: FactorContext) -> tuple[float, str]:
    days = ctx.get("distribution_days_25d")
    if days >= 8:
        return 4.0, f"Distribution pressure severe: {days:.0f}/25"
    if days >= 6:
        return 3.0, f"Distribution pressure elevated: {days:.0f}/25"
    if days >= 4:
        return 1.0, f"Distribution pressure watch: {days:.0f}/25"
    return 0.0, f"Distribution pressure quiet: {days:.0f}/25"


def _chandelier_break(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("close")
    stop = ctx.get("chandelier_exit")
    if close < stop:
        return 5.0, f"Close below 22D Chandelier 4.5x ATR: {close:.2f} < {stop:.2f}"
    return 0.0, f"Close above Chandelier stop: {close:.2f} >= {stop:.2f}"


def _ma220_gap(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("close")
    ma220 = ctx.get("ma220")
    if close <= ma220:
        return 4.0, "Close is below or equal to MA220 rebuild line"
    if close / ma220 - 1.0 < 0.03:
        return 1.0, "Close is less than 3% above MA220 rebuild line"
    return 0.0, "Close is safely above MA220 rebuild line"


def _vol_expansion(ctx: FactorContext) -> tuple[float, str]:
    vol = ctx.get("realized_vol20")
    if vol >= 1.20:
        return 4.0, f"20D realized volatility extreme: {vol:.1%}"
    if vol >= 0.85:
        return 3.0, f"20D realized volatility elevated: {vol:.1%}"
    if vol >= 0.60:
        return 1.0, f"20D realized volatility watch: {vol:.1%}"
    return 0.0, f"20D realized volatility normal: {vol:.1%}"
