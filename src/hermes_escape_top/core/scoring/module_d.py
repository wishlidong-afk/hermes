from __future__ import annotations

from typing import Any, Optional

from .registry import FactorContext, FactorDefinition, missing_only


ONCHAIN_MSTR_CANDIDATES = {
    "CM_EXCHANGE_INFLOW_PRESSURE": "SOFT.cm_exchange_inflow_pressure",
    "CM_EXCHANGE_NETFLOW_PRESSURE": "SOFT.cm_exchange_netflow_pressure",
}
ONCHAIN_THRESHOLD = 2.0


def module_d_factors(symbol: str, config: Optional[dict[str, Any]] = None) -> list[FactorDefinition]:
    factors = [
        FactorDefinition("D1_ASSET_MA200_BREAK", "D", 5.0, ["close", "ma200"], _asset_ma200_break),
        FactorDefinition("D2_ASSET_MA220_BREAK", "D", 3.0, ["close", "ma220"], _asset_ma220_break),
        FactorDefinition("D3_TRAILING_PEAK_DAMAGE", "D", 4.0, ["close", "ema50", "drawdown_60d_high_pct"], _trailing_peak_damage),
        FactorDefinition("D4_RADAR_CONFIRMATION", "D", 4.0, _radar_dependencies(symbol), _radar_confirmation(symbol), _radar_missing_name(symbol)),
    ]
    factors.extend(_symbol_extra_factors(symbol, config))
    return factors


def _asset_ma200_break(ctx: FactorContext) -> tuple[float, str]:
    if ctx.get("close") <= ctx.get("ma200"):
        return 5.0, "Asset close is below or equal to MA200"
    return 0.0, "Asset remains above MA200"


def _asset_ma220_break(ctx: FactorContext) -> tuple[float, str]:
    if ctx.get("close") <= ctx.get("ma220"):
        return 3.0, "Asset close is below or equal to MA220"
    return 0.0, "Asset remains above MA220"


def _trailing_peak_damage(ctx: FactorContext) -> tuple[float, str]:
    drawdown = ctx.get("drawdown_60d_high_pct")
    close = ctx.get("close")
    ema50 = ctx.get("ema50")
    if drawdown <= -0.25 and close < ema50:
        return 4.0, f"60D peak drawdown {drawdown:.1%} and close below EMA50"
    if drawdown <= -0.25:
        return 2.0, f"60D peak drawdown {drawdown:.1%}"
    return 0.0, f"60D peak drawdown not severe: {drawdown:.1%}"


def _radar_dependencies(symbol: str) -> list[str]:
    if symbol == "MSTR":
        return ["BTC-USD.close", "BTC-USD.ma200"]
    if symbol == "FNGU":
        return ["QQQ.close", "QQQ.ma200", "QQQ.ema50"]
    if symbol == "SOXL":
        return ["SOXX.close", "SOXX.ma200", "SOXX.ema50"]
    return ["close", "ma200"]


def _radar_missing_name(symbol: str) -> str:
    if symbol == "MSTR":
        return "D-M1"
    if symbol == "FNGU":
        return "D-F4"
    if symbol == "SOXL":
        return "D-S4"
    return "D radar"


def _radar_confirmation(symbol: str):
    def score(ctx: FactorContext) -> tuple[float, str]:
        if symbol == "MSTR":
            if ctx.get("BTC-USD.close") <= ctx.get("BTC-USD.ma200"):
                return 4.0, "BTC radar is below or equal to MA200"
            return 0.0, "BTC radar remains above MA200"
        if symbol == "FNGU":
            close = ctx.get("QQQ.close")
            if close <= ctx.get("QQQ.ma200"):
                return 4.0, "FNGU radar QQQ is below or equal to MA200"
            if close < ctx.get("QQQ.ema50"):
                return 2.0, "FNGU radar QQQ is below EMA50"
            return 0.0, "FNGU radar QQQ trend intact"
        if symbol == "SOXL":
            close = ctx.get("SOXX.close")
            if close <= ctx.get("SOXX.ma200"):
                return 4.0, "SOXL radar SOXX is below or equal to MA200"
            if close < ctx.get("SOXX.ema50"):
                return 2.0, "SOXL radar SOXX is below EMA50"
            return 0.0, "SOXL radar SOXX trend intact"
        if ctx.get("close") <= ctx.get("ma200"):
            return 4.0, "Generic radar below or equal to MA200"
        return 0.0, "Generic radar trend intact"

    return score


FNGU_COMPONENTS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "NFLX", "AVGO"]
SOXL_COMPONENTS = ["NVDA", "AVGO", "AMD", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "QCOM", "MU"]


def _symbol_extra_factors(symbol: str, config: Optional[dict[str, Any]]) -> list[FactorDefinition]:
    if symbol == "MSTR":
        onchain_dep = _selected_onchain_dependency(config)
        if onchain_dep:
            return [
                FactorDefinition(
                    "D_M3_BTC_RISK_COMPOSITE",
                    "D",
                    4.0,
                    ["BTC-USD.realized_vol20", "BTC-USD.return_10d", "BTC-USD.drawdown_60d_high_pct"],
                    _btc_risk_composite(onchain_dep),
                    "D-M3",
                ),
                missing_only("D_M4_BALANCE_SHEET_PROXY", "D", "D-M4"),
                missing_only("D_M5_CRYPTO_SENTIMENT", "D", "D-M5"),
            ]
        return [
            FactorDefinition(
                "D_M3_BTC_VOLATILITY_PROXY",
                "D",
                4.0,
                ["BTC-USD.realized_vol20", "BTC-USD.return_10d", "BTC-USD.drawdown_60d_high_pct"],
                _btc_microstructure_proxy,
                "D-M3",
            ),
            missing_only("D_M4_BALANCE_SHEET_PROXY", "D", "D-M4"),
            missing_only("D_M5_CRYPTO_SENTIMENT", "D", "D-M5"),
        ]
    if symbol == "FNGU":
        return [
            FactorDefinition(
                "D_F4_COMPONENT_FLOW",
                "D",
                4.0,
                _component_flow_dependencies(FNGU_COMPONENTS),
                _component_flow_score("FNGU", FNGU_COMPONENTS),
                "D-F4",
                partial_ok=True,
            )
        ]
    if symbol == "SOXL":
        return [
            FactorDefinition(
                "D_S4_COMPONENT_FLOW",
                "D",
                4.0,
                _component_flow_dependencies(SOXL_COMPONENTS),
                _component_flow_score("SOXL", SOXL_COMPONENTS),
                "D-S4",
                partial_ok=True,
            )
        ]
    return []


def _selected_onchain_dependency(config: Optional[dict[str, Any]]) -> str | None:
    if not bool((config or {}).get("features", {}).get("data_onchain_mstr", False)):
        return None
    candidate = str(((config or {}).get("onchain_mstr") or {}).get("candidate", "")).strip()
    return ONCHAIN_MSTR_CANDIDATES.get(candidate)


def _component_flow_dependencies(components: list[str]) -> list[str]:
    deps: list[str] = []
    for component in components:
        deps.extend([f"{component}.cmf20", f"{component}.mfi14", f"{component}.ad_slope20"])
    return deps


def _component_flow_score(symbol: str, components: list[str]):
    def score(ctx: FactorContext) -> tuple[float, str]:
        weak: list[str] = []
        severe: list[str] = []
        available = 0
        for component in components:
            cmf = ctx.get(f"{component}.cmf20")
            mfi = ctx.get(f"{component}.mfi14")
            ad_slope = ctx.get(f"{component}.ad_slope20")
            # Partial-eval safe: skip a constituent missing any sub-field rather
            # than crashing / zeroing the whole factor. Gates scale to the number
            # actually observed, so 8/9 components still produce a valid signal.
            if cmf is None or mfi is None or ad_slope is None:
                continue
            available += 1
            if cmf <= -0.10 and mfi <= 45 and ad_slope < 0:
                severe.append(component)
            if cmf < 0 and mfi < 50 and ad_slope < 0:
                weak.append(component)
        if available == 0:
            return 0.0, f"{symbol} component flow: no constituent data"
        cov = f"{available}/{len(components)} obs"
        severe_gate = max(2, available // 3)
        weak_gate = max(3, available // 2)
        if len(severe) >= severe_gate:
            return 4.0, f"{symbol} component flow severe: {len(severe)}/{available} severe outflow [{cov}] ({','.join(severe[:5])})"
        if len(weak) >= weak_gate:
            return 3.0, f"{symbol} component flow elevated: {len(weak)}/{available} weak outflow [{cov}] ({','.join(weak[:5])})"
        if len(weak) >= 2:
            return 1.0, f"{symbol} component flow watch: {len(weak)}/{available} weak outflow [{cov}] ({','.join(weak[:5])})"
        return 0.0, f"{symbol} component flow normal: {len(weak)}/{available} weak outflow [{cov}]"

    return score


def _btc_microstructure_proxy(ctx: FactorContext) -> tuple[float, str]:
    vol = ctx.get("BTC-USD.realized_vol20")
    ret10 = ctx.get("BTC-USD.return_10d")
    dd60 = ctx.get("BTC-USD.drawdown_60d_high_pct")
    if vol >= 0.80 and (ret10 <= -0.12 or dd60 <= -0.20):
        return 4.0, f"BTC proxy stress severe: vol20={vol:.1%}, ret10={ret10:.1%}, dd60={dd60:.1%}"
    if vol >= 0.65 and (ret10 <= -0.08 or dd60 <= -0.15):
        return 3.0, f"BTC proxy stress elevated: vol20={vol:.1%}, ret10={ret10:.1%}, dd60={dd60:.1%}"
    if vol >= 0.55 or ret10 <= -0.06 or dd60 <= -0.12:
        return 1.0, f"BTC proxy stress watch: vol20={vol:.1%}, ret10={ret10:.1%}, dd60={dd60:.1%}"
    return 0.0, f"BTC proxy stress normal: vol20={vol:.1%}, ret10={ret10:.1%}, dd60={dd60:.1%}"


def _btc_risk_composite(onchain_dependency: str):
    def score(ctx: FactorContext) -> tuple[float, str]:
        proxy_score, proxy_msg = _btc_microstructure_proxy(ctx)
        value = ctx.get(onchain_dependency)
        label = onchain_dependency.replace("SOFT.", "")
        if value is not None and value > ONCHAIN_THRESHOLD:
            return 4.0, f"BTC/on-chain composite severe: {label}={value:.2f} > {ONCHAIN_THRESHOLD:.1f}; {proxy_msg}"
        return proxy_score, f"BTC/on-chain composite uses BTC proxy: {label}={_fmt_optional(value)}; {proxy_msg}"

    return score


def _fmt_optional(value) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"
