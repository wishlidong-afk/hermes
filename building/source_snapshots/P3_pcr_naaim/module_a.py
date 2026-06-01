from __future__ import annotations

from .registry import FactorContext, FactorDefinition, missing_only


def module_a_factors() -> list[FactorDefinition]:
    return [
        FactorDefinition("A1_QQQ_MA200_BREAK", "A", 4.0, ["QQQ.close", "QQQ.ma200"], _qqq_ma200_break),
        missing_only("A2_CNN_FEAR_GREED", "A", "A2 cnn_fear_greed"),
        FactorDefinition("A2_AAII_BULL", "A", 2.0, ["SOFT.aaii_bull_bear_spread", "SOFT.aaii_bull_pctl"], _aaii_pressure, "A2 aaii_bull"),
        FactorDefinition("A2_NAAIM", "A", 2.0, ["SOFT.naaim_exposure", "SOFT.naaim_pctl"], _naaim_pressure, "A2 naaim"),
        FactorDefinition("A2_CBOE_EQUITY_PCR", "A", 2.0, ["SOFT.equity_pcr", "SOFT.equity_pcr_pctl"], _equity_pcr_pressure, "A2 cboe_equity_pcr"),
        FactorDefinition(
            "A3_COMPONENT_BREADTH",
            "A",
            4.0,
            ["SOFT.aggregate_pct_above_50dma", "SOFT.aggregate_pct_above_200dma", "SOFT.aggregate_breadth_chg_5d"],
            _component_breadth_pressure,
            "A3 NDX breadth",
        ),
        FactorDefinition("A5_NET_LIQUIDITY", "A", 4.0, ["SOFT.net_liq_chg10_pctl"], _net_liquidity_pressure, "A5"),
        FactorDefinition("A6_FUND_FLOW", "A", 4.0, ["QQQ.cmf20", "QQQ.mfi14", "QQQ.ad_slope20"], _fund_flow_pressure, "A6 fund flow"),
        FactorDefinition("A7_VIX_TERM_STRUCTURE", "A", 4.0, ["^VIX.close", "^VIX3M.close"], _vix_term_structure, "A7 VIX term structure"),
        FactorDefinition("A8_QQQ_DISTRIBUTION", "A", 4.0, ["QQQ.distribution_days_25d"], _qqq_distribution, "A8 market distribution"),
    ]


def _qqq_ma200_break(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("QQQ.close")
    ma200 = ctx.get("QQQ.ma200")
    if close <= ma200:
        return 4.0, "QQQ close is below or equal to MA200"
    return 0.0, "QQQ remains above MA200"


def _aaii_pressure(ctx: FactorContext) -> tuple[float, str]:
    spread = ctx.get("SOFT.aaii_bull_bear_spread")
    bull_pctl = ctx.get("SOFT.aaii_bull_pctl")
    if spread >= 0.25 or bull_pctl >= 92:
        return 2.0, f"AAII bullish pressure high: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"
    if spread >= 0.15 or bull_pctl >= 82:
        return 1.0, f"AAII bullish pressure watch: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"
    return 0.0, f"AAII sentiment not euphoric: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"


def _component_breadth_pressure(ctx: FactorContext) -> tuple[float, str]:
    above50 = ctx.get("SOFT.aggregate_pct_above_50dma")
    above200 = ctx.get("SOFT.aggregate_pct_above_200dma")
    change5d = ctx.get("SOFT.aggregate_breadth_chg_5d")
    if above50 <= 0.30 and above200 <= 0.45:
        return 4.0, f"Component breadth weak: {above50:.0%} above 50DMA, {above200:.0%} above 200DMA"
    if above50 <= 0.45 or change5d <= -0.25:
        return 3.0, f"Component breadth deterioration: {above50:.0%} above 50DMA, 5D change={change5d:.0%}"
    if above50 <= 0.60 or change5d <= -0.15:
        return 1.0, f"Component breadth watch: {above50:.0%} above 50DMA, 5D change={change5d:.0%}"
    return 0.0, f"Component breadth healthy: {above50:.0%} above 50DMA, {above200:.0%} above 200DMA"


def _vix_term_structure(ctx: FactorContext) -> tuple[float, str]:
    vix = ctx.get("^VIX.close")
    vix3m = ctx.get("^VIX3M.close")
    ratio = vix / vix3m if vix3m else 0.0
    if ratio >= 1.0:
        return 4.0, f"VIX/VIX3M backwardation ratio={ratio:.3f}"
    if ratio >= 0.96:
        return 2.0, f"VIX term structure near stress ratio={ratio:.3f}"
    return 0.0, f"VIX term structure normal ratio={ratio:.3f}"


def _fund_flow_pressure(ctx: FactorContext) -> tuple[float, str]:
    cmf = ctx.get("QQQ.cmf20")
    mfi = ctx.get("QQQ.mfi14")
    ad_slope = ctx.get("QQQ.ad_slope20")
    if cmf <= -0.20 and mfi <= 35 and ad_slope < 0:
        return 4.0, f"QQQ fund flow severe outflow: CMF20={cmf:.2f}, MFI14={mfi:.1f}, AD20={ad_slope:.2f}"
    if cmf <= -0.10 and mfi <= 45 and ad_slope < 0:
        return 3.0, f"QQQ fund flow elevated outflow: CMF20={cmf:.2f}, MFI14={mfi:.1f}, AD20={ad_slope:.2f}"
    if cmf < 0 and mfi < 50:
        return 1.0, f"QQQ fund flow watch: CMF20={cmf:.2f}, MFI14={mfi:.1f}, AD20={ad_slope:.2f}"
    return 0.0, f"QQQ fund flow normal: CMF20={cmf:.2f}, MFI14={mfi:.1f}, AD20={ad_slope:.2f}"


def _net_liquidity_pressure(ctx: FactorContext) -> tuple[float, str]:
    pctl = ctx.get("SOFT.net_liq_chg10_pctl")
    if pctl <= 10:
        return 4.0, f"FRED net liquidity 10D change in bottom decile: pctl={pctl:.1f}"
    if pctl <= 20:
        return 3.0, f"FRED net liquidity contraction elevated: pctl={pctl:.1f}"
    if pctl <= 35:
        return 1.0, f"FRED net liquidity soft watch: pctl={pctl:.1f}"
    return 0.0, f"FRED net liquidity normal: pctl={pctl:.1f}"


def _qqq_distribution(ctx: FactorContext) -> tuple[float, str]:
    days = ctx.get("QQQ.distribution_days_25d")
    if days >= 8:
        return 4.0, f"QQQ distribution days elevated: {days:.0f}/25"
    if days >= 6:
        return 3.0, f"QQQ distribution pressure: {days:.0f}/25"
    if days >= 4:
        return 1.0, f"QQQ distribution watch: {days:.0f}/25"
    return 0.0, f"QQQ distribution quiet: {days:.0f}/25"


def _naaim_pressure(ctx: FactorContext) -> tuple[float, str]:
    exposure = ctx.get("SOFT.naaim_exposure")
    pctl = ctx.get("SOFT.naaim_pctl")
    # NAAIM exposure 0-200: high values = active managers are very long → overextension risk
    if exposure >= 90 or (pctl is not None and pctl >= 90):
        return 2.0, f"NAAIM highly bullish/exposed: exposure={exposure:.1f}, pctl={pctl}"
    if exposure >= 70 or (pctl is not None and pctl >= 75):
        return 1.0, f"NAAIM bullish watch: exposure={exposure:.1f}, pctl={pctl}"
    return 0.0, f"NAAIM neutral/bearish: exposure={exposure:.1f}"


def _equity_pcr_pressure(ctx: FactorContext) -> tuple[float, str]:
    pcr = ctx.get("SOFT.equity_pcr")
    pctl = ctx.get("SOFT.equity_pcr_pctl")
    # Low equity PCR → heavy call buying → euphoria → escape-top signal
    if pcr <= 0.52 or (pctl is not None and pctl <= 8):
        return 2.0, f"Equity PCR very low (call euphoria): pcr={pcr:.3f}, pctl={pctl}"
    if pcr <= 0.62 or (pctl is not None and pctl <= 20):
        return 1.0, f"Equity PCR low watch: pcr={pcr:.3f}, pctl={pctl}"
    return 0.0, f"Equity PCR neutral: pcr={pcr:.3f}"
