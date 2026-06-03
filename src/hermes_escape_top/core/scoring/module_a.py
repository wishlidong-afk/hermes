from __future__ import annotations

from .registry import FactorContext, FactorDefinition, missing_only


def module_a_factors() -> list[FactorDefinition]:
    return [
        FactorDefinition("A1_QQQ_MA200_BREAK", "A", 4.0, ["QQQ.close", "QQQ.ma200"], _qqq_ma200_break),
        FactorDefinition("A1_VIX_COMPLACENCY", "A", 4.0, ["^VIX.close"], _vix_complacency, "A1 VIX"),
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
        FactorDefinition(
            "A4_QQQ_STRETCH",
            "A",
            4.0,
            ["QQQ.close", "QQQ.ema20", "QQQ.rsi14"],
            _qqq_stretch,
            "A4 QQQ stretch",
        ),
        FactorDefinition("A5_NET_LIQUIDITY", "A", 4.0, ["SOFT.net_liq_chg10_pctl"], _net_liquidity_pressure, "A5"),
        FactorDefinition("A6_FUND_FLOW", "A", 4.0, ["QQQ.cmf20", "QQQ.mfi14", "QQQ.ad_slope20"], _fund_flow_pressure, "A6 fund flow"),
        FactorDefinition("A7_VIX_TERM_STRUCTURE", "A", 4.0, ["^VIX.close", "^VIX3M.close"], _vix_term_structure, "A7 VIX term structure"),
        FactorDefinition("A8_QQQ_DISTRIBUTION", "A", 4.0,
                         ["QQQ.distribution_days_25d", "SPY.distribution_days_25d"],
                         _qqq_distribution, "A8 market distribution"),
    ]


def _qqq_ma200_break(ctx: FactorContext) -> tuple[float, str]:
    close = ctx.get("QQQ.close")
    ma200 = ctx.get("QQQ.ma200")
    if close <= ma200:
        return 4.0, "QQQ close is below or equal to MA200"
    return 0.0, "QQQ remains above MA200"


def _vix_complacency(ctx: FactorContext) -> tuple[float, str]:
    """A1 VIX complacency — low volatility warns of overextension.

    Mirrors the v25 monolith's A1 VIX rule (SKILL.md §3/A1):
      VIX < 13 → 4 pts (extreme complacency)
      VIX < 16 → 2 pts (low volatility watch)
    Also scores elevated VIX under stress (same spec):
      VIX > 30 and QQQ < EMA50 → 4 pts
      VIX > 25 and QQQ < EMA20 → 2 pts
    Take maximum.

    This factor was missing from the package, causing Module A to under-score
    by up to 4 pts when markets are in a low-VIX complacency regime.
    """
    vix = ctx.get("^VIX.close")
    if vix is None:
        return 0.0, "VIX unavailable"

    # Low-VIX complacency (escape-top risk: market too calm before a drop)
    if vix < 13:
        low_score, low_reason = 4.0, f"VIX extreme complacency: {vix:.2f}"
    elif vix < 16:
        low_score, low_reason = 2.0, f"VIX low/calm: {vix:.2f}"
    else:
        low_score, low_reason = 0.0, ""

    # Stress-spike (secondary: rising fear + trend break)
    qqq_close = ctx.get("QQQ.close")
    ema20 = ctx.get("QQQ.ema20")
    ema50 = ctx.get("QQQ.ema50")
    if vix > 30 and qqq_close is not None and ema50 is not None and qqq_close < ema50:
        stress_score, stress_reason = 4.0, f"VIX stress spike {vix:.1f} + QQQ<EMA50"
    elif vix > 25 and qqq_close is not None and ema20 is not None and qqq_close < ema20:
        stress_score, stress_reason = 2.0, f"VIX elevated {vix:.1f} + QQQ<EMA20"
    else:
        stress_score, stress_reason = 0.0, ""

    if low_score >= stress_score:
        return low_score, low_reason or f"VIX normal: {vix:.2f}"
    return stress_score, stress_reason


def _aaii_pressure(ctx: FactorContext) -> tuple[float, str]:
    spread = ctx.get("SOFT.aaii_bull_bear_spread")
    bull_pctl = ctx.get("SOFT.aaii_bull_pctl")
    if spread >= 0.25 or bull_pctl >= 92:
        return 2.0, f"AAII bullish pressure high: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"
    if spread >= 0.15 or bull_pctl >= 82:
        return 1.0, f"AAII bullish pressure watch: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"
    return 0.0, f"AAII sentiment not euphoric: spread={spread:.1%}, bull_pctl={bull_pctl:.1f}"


def _component_breadth_pressure(ctx: FactorContext) -> tuple[float, str]:
    """A3: NDX breadth OVERHEAT or ACUTE DETERIORATION — take the maximum.

    Overheat (universal rallies breed complacency):
      >50DMA > 80% → 4,  > 70% → 2
      >200DMA > 85% → 4, > 75% → 2

    Acute deterioration (breadth collapse warns of distribution):
      5D change < -25pp → 4,  < -15pp → 2

    Matches the SKILL.md spec (Section 3 / A3).
    Previously the package ONLY scored deterioration (low breadth), treating
    high breadth as "healthy" — this was the root cause of the Module A gap.
    """
    above50 = ctx.get("SOFT.aggregate_pct_above_50dma") or 0.0
    above200 = ctx.get("SOFT.aggregate_pct_above_200dma") or 0.0
    change5d = ctx.get("SOFT.aggregate_breadth_chg_5d") or 0.0

    # Overheat side: too many stocks above moving averages
    if above50 >= 0.80 or above200 >= 0.85:
        overheat_score = 4.0
        overheat_reason = f"breadth overheat: {above50:.0%} >50DMA, {above200:.0%} >200DMA"
    elif above50 >= 0.70 or above200 >= 0.75:
        overheat_score = 2.0
        overheat_reason = f"breadth elevated: {above50:.0%} >50DMA, {above200:.0%} >200DMA"
    else:
        overheat_score = 0.0
        overheat_reason = f"breadth normal: {above50:.0%} >50DMA"

    # Deterioration side: breadth collapsing
    if change5d <= -0.25:
        deteri_score = 4.0
        deteri_reason = f"breadth collapse 5D={change5d:.0%}"
    elif change5d <= -0.15:
        deteri_score = 2.0
        deteri_reason = f"breadth deterioration 5D={change5d:.0%}"
    else:
        deteri_score = 0.0
        deteri_reason = ""

    if overheat_score >= deteri_score:
        return overheat_score, f"A3 {overheat_reason}"
    return deteri_score, f"A3 {deteri_reason}"


def _qqq_stretch(ctx: FactorContext) -> tuple[float, str]:
    """A4: QQQ technical stretch above EMA20 or RSI overheat — take the maximum.

    Distance from EMA20: >10% → 4,  >6% → 2
    RSI14:              > 78  → 4, > 72  → 2

    This factor was MISSING from the package (exists in monolith and SKILL.md).
    Absence caused Module A to under-score by up to 4 pts, which masked
    market overheat signals and caused FNGU/SOXL status mismatches.
    """
    close = ctx.get("QQQ.close")
    ema20 = ctx.get("QQQ.ema20")
    rsi14 = ctx.get("QQQ.rsi14")

    dist_score, dist_reason = 0.0, ""
    if close is not None and ema20 is not None and ema20 > 0:
        dist_pct = (close - ema20) / ema20
        if dist_pct > 0.10:
            dist_score = 4.0
            dist_reason = f"QQQ dist20={dist_pct:.1%} extreme"
        elif dist_pct > 0.06:
            dist_score = 2.0
            dist_reason = f"QQQ dist20={dist_pct:.1%} watch"

    rsi_score, rsi_reason = 0.0, ""
    if rsi14 is not None:
        if rsi14 > 78:
            rsi_score = 4.0
            rsi_reason = f"QQQ RSI={rsi14:.1f} extreme"
        elif rsi14 > 72:
            rsi_score = 2.0
            rsi_reason = f"QQQ RSI={rsi14:.1f} watch"

    if dist_score >= rsi_score:
        if dist_score == 0:
            return 0.0, f"QQQ dist20={((close-ema20)/ema20):.1%}, RSI={rsi14:.1f}" if (close and ema20 and rsi14) else "QQQ stretch normal"
        return dist_score, f"A4 {dist_reason}, RSI={rsi14:.1f if rsi14 else 'n/a'}"
    return rsi_score, f"A4 {rsi_reason}, dist20={((close-ema20)/ema20):.1%}" if (close and ema20) else f"A4 {rsi_reason}"


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
    """A8: market distribution-day pressure — max of QQQ and SPY (monolith parity)."""
    qqq_days = ctx.get("QQQ.distribution_days_25d")
    spy_days = ctx.get("SPY.distribution_days_25d")
    candidates = [d for d in (qqq_days, spy_days) if d is not None]
    days = max(candidates) if candidates else 0.0
    label = f"QQQ {qqq_days if qqq_days is not None else 'NA'}/25, SPY {spy_days if spy_days is not None else 'NA'}/25"
    if days >= 6:
        return 4.0, f"market distribution elevated: {label}"
    if days >= 5:
        return 3.0, f"market distribution pressure: {label}"
    if days >= 4:
        return 2.0, f"market distribution watch: {label}"
    return 0.0, f"market distribution quiet: {label}"


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
