from __future__ import annotations

from .registry import FactorContext, FactorDefinition, missing_only


def module_b_factors() -> list[FactorDefinition]:
    return [
        FactorDefinition("B1_RSI_OVERHEAT", "B", 5.0, ["rsi14"], _rsi_overheat),
        FactorDefinition("B2_MA200_EXTENSION", "B", 5.0, ["close", "ma200"], _ma200_extension),
        FactorDefinition("B3_POST_PEAK_DAMAGE", "B", 5.0, ["drawdown_60d_high_pct"], _post_peak_damage),
        FactorDefinition("B4_CBOE_OPTIONS_STRESS", "B", 6.0, ["SOFT.vvix_pctl", "SOFT.skew_index", "SOFT.skew_pctl"], _cboe_options_stress, "B4 options"),
        missing_only("B5_SOCIAL_EUPHORIA", "B", "B5 social"),
        missing_only("B6_VALUATION_HEAT", "B", "B6 valuation"),
    ]


def _fmt_rsi(value) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else "n/a"


def _rsi_overheat(ctx: FactorContext) -> tuple[float, str]:
    """B1 RSI overheat — daily + second-timeframe, per-symbol (v25-aligned).

    Mirrors the production monolith: MSTR combines daily + its own weekly RSI;
    FNGU/SOXL combine daily + their radar's (FNGS/SOXX) daily RSI. Per-symbol
    daily thresholds (leveraged ETFs need a higher bar). The previous daily-only
    single threshold was blind to weekly/radar overheating — the dangerous
    false-HOLD failure mode for a top-escape defense system. Capped at max (5).
    """
    daily = ctx.get("rsi14")
    pts = 0.0
    if ctx.symbol == "MSTR":
        if daily is not None and daily > 82:
            pts += 4.0
        elif daily is not None and daily > 75:
            pts += 2.0
        weekly = ctx.get("rsi14_weekly")
        if weekly is not None and weekly > 78:
            pts += 2.0
        elif weekly is not None and weekly > 72:
            pts += 1.0
        second = f"weekly={_fmt_rsi(weekly)}"
    else:
        if daily is not None and daily > 85:
            pts += 4.0
        elif daily is not None and daily > 78:
            pts += 2.0
        radar_sym = "FNGS" if ctx.symbol == "FNGU" else "SOXX"
        rrsi = ctx.get(f"{radar_sym}.rsi14")
        if rrsi is not None and rrsi > 80:
            pts += 2.0
        elif rrsi is not None and rrsi > 72:
            pts += 1.0
        second = f"radar({radar_sym})={_fmt_rsi(rrsi)}"
    return min(pts, 5.0), f"B1 RSI daily={_fmt_rsi(daily)}, {second}"


def _ma200_extension(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("close")
    ma200 = ctx.get("ma200")
    extension = close / ma200 - 1.0 if ma200 else 0.0
    if extension >= 0.80:
        return 5.0, f"Price extension above MA200 is extreme: {extension:.1%}"
    if extension >= 0.50:
        return 3.0, f"Price extension above MA200 is high: {extension:.1%}"
    if extension >= 0.30:
        return 1.0, f"Price extension above MA200 is watch level: {extension:.1%}"
    return 0.0, f"Price extension above MA200 normal: {extension:.1%}"


def _post_peak_damage(ctx: FactorContext) -> tuple[float, str]:
    drawdown = ctx.get("drawdown_60d_high_pct")
    if drawdown <= -0.30:
        return 5.0, f"Post-peak drawdown severe: {drawdown:.1%}"
    if drawdown <= -0.20:
        return 3.0, f"Post-peak drawdown elevated: {drawdown:.1%}"
    if drawdown <= -0.12:
        return 1.0, f"Post-peak drawdown watch: {drawdown:.1%}"
    return 0.0, f"Post-peak damage contained: {drawdown:.1%}"


def _cboe_options_stress(ctx: FactorContext) -> tuple[float, str]:
    vvix_pctl = ctx.get("SOFT.vvix_pctl")
    skew = ctx.get("SOFT.skew_index")
    skew_pctl = ctx.get("SOFT.skew_pctl")
    if vvix_pctl >= 95 and (skew >= 155 or skew_pctl >= 95):
        return 6.0, f"VVIX and SKEW both extreme: vvix_pctl={vvix_pctl:.1f}, skew={skew:.1f}, skew_pctl={skew_pctl:.1f}"
    if vvix_pctl >= 90 or skew >= 160 or skew_pctl >= 92:
        return 4.0, f"CBOE options stress elevated: vvix_pctl={vvix_pctl:.1f}, skew={skew:.1f}, skew_pctl={skew_pctl:.1f}"
    if vvix_pctl >= 80 or skew >= 150 or skew_pctl >= 80:
        return 2.0, f"CBOE options stress watch: vvix_pctl={vvix_pctl:.1f}, skew={skew:.1f}, skew_pctl={skew_pctl:.1f}"
    return 0.0, f"CBOE options stress normal: vvix_pctl={vvix_pctl:.1f}, skew={skew:.1f}, skew_pctl={skew_pctl:.1f}"
