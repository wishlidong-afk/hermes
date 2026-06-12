from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from ..data.base import SymbolSnapshot


def build_action_context(
    payload: Dict[str, Any],
    snapshots: Dict[str, SymbolSnapshot],
) -> Dict[str, Any]:
    """Build the user-facing action layer from score/sizing/routing data.

    This intentionally separates three concerns:
      - risk temperature: score/status
      - hard valve state: physical exit triggers
      - action confidence: whether data quality is good enough to trust action
    """
    decision_layers: Dict[str, Dict[str, Any]] = {}
    action_intents: Dict[str, Dict[str, Any]] = {}
    portfolio_value = _float((payload.get("posterior_pnl") or {}).get("portfolio_value"), 100000.0)
    quality = payload.get("data_quality") or {}
    quality_score = _float(quality.get("overall_score"), 0.0)
    ibkr = payload.get("ibkr") or {}
    ibkr_stale = bool(ibkr.get("snapshot_stale")) or str(ibkr.get("source", "")).lower() not in {"tws", "disabled"}

    for symbol, score in sorted((payload.get("scores") or {}).items()):
        sizing = (payload.get("sizing") or {}).get(symbol, {})
        routing = (payload.get("routing") or {}).get(symbol, {})
        reentry = (payload.get("reentry") or {}).get(symbol, {})
        layer = _decision_layer(symbol, score, quality_score, ibkr_stale)
        intent = _action_intent(symbol, score, sizing, routing, reentry, snapshots, portfolio_value, layer)
        decision_layers[symbol] = layer
        action_intents[symbol] = intent

    return {
        "decision_layers": decision_layers,
        "action_intents": action_intents,
        "today_ops": _today_ops(action_intents, payload),
    }


def _decision_layer(symbol: str, score: Dict[str, Any], quality_score: float, ibkr_stale: bool) -> Dict[str, Any]:
    hard = list(score.get("hard_valve_hits") or [])
    missing_weight = _float(score.get("missing_weight"), 0.0)
    confidence_missing_weight = _float(score.get("confidence_missing_weight"), missing_weight)
    non_scoring_missing_weight = _float(score.get("non_scoring_missing_weight"), max(0.0, missing_weight - confidence_missing_weight))
    blind_spot = bool(score.get("blind_spot"))
    confidence_score = max(0.0, min(100.0, quality_score - confidence_missing_weight))
    reasons = []
    if confidence_missing_weight > 0:
        reasons.append(f"scored missing data weight {confidence_missing_weight:g} deducted from data quality")
    if non_scoring_missing_weight > 0:
        reasons.append(f"non-scoring placeholders tracked separately ({non_scoring_missing_weight:g} pts)")
    if blind_spot:
        confidence_score = min(confidence_score, 50.0)
        reasons.append("blind spot: missing data weight is above threshold")
    if ibkr_stale:
        confidence_score = min(confidence_score, 70.0)
        reasons.append("IBKR is snapshot/stale or unavailable")
    if confidence_score >= 85:
        level = "HIGH"
    elif confidence_score >= 70:
        level = "MEDIUM"
    elif confidence_score >= 50:
        level = "LOW"
    else:
        level = "BLOCKED"
    return {
        "symbol": symbol,
        "risk_temperature": {
            "score": _float(score.get("final_score"), 0.0),
            "status": score.get("status", "NA"),
            "module_scores": score.get("module_scores") or {},
        },
        "hard_valve_state": {
            "triggered": bool(hard),
            "count": len(hard),
            "ids": hard,
            "candidates": score.get("valve_candidates") or [],
        },
        "action_confidence": {
            "score": round(confidence_score, 2),
            "level": level,
            "quality_score": round(quality_score, 2),
            "scored_missing_weight": round(confidence_missing_weight, 2),
            "total_missing_weight": round(missing_weight, 2),
            "non_scoring_missing_weight": round(non_scoring_missing_weight, 2),
            "scored_missing_fields": score.get("confidence_missing_fields") or [],
            "non_scoring_missing_fields": score.get("non_scoring_missing_fields") or [],
            "reasons": reasons or ["data confidence acceptable for advisory use"],
        },
    }


def _action_intent(
    symbol: str,
    score: Dict[str, Any],
    sizing: Dict[str, Any],
    routing: Dict[str, Any],
    reentry: Dict[str, Any],
    snapshots: Dict[str, SymbolSnapshot],
    portfolio_value: float,
    layer: Dict[str, Any],
) -> Dict[str, Any]:
    status = str(score.get("status", "NA"))
    sell_fraction = _float(score.get("sell_fraction"), 0.0)
    sleeve_cap = _float(sizing.get("sleeve_cap"), 0.0)
    target_weight = _float(sizing.get("target_weight"), 0.0)
    route_applies = bool(routing.get("applies"))
    route_destination = str(routing.get("destination") or "-")
    route_weight_items = _route_weight_items(routing, route_destination) if route_applies else []
    hard = list(score.get("hard_valve_hits") or [])
    if route_applies:
        action = "SELL_AND_ROUTE" if sell_fraction >= 1.0 or hard else "REDUCE_AND_ROUTE"
        target_symbol = _route_target_label(route_weight_items, route_destination)
        target_weight_for_symbol = max(0.0, sleeve_cap - target_weight)
        target_notional = target_weight_for_symbol * portfolio_value
    elif target_weight > 0:
        action = "HOLD_OR_MAINTAIN"
        target_symbol = symbol
        target_weight_for_symbol = target_weight
        target_notional = target_weight * portfolio_value
    else:
        action = "STAY_OUT"
        target_symbol = symbol
        target_weight_for_symbol = 0.0
        target_notional = 0.0

    price = _price_for(target_symbol, snapshots)
    target_shares = target_notional / price if price and price > 0 else None
    reasons = _top_reasons(score, routing)
    invalidation = _invalidation(status, target_symbol, routing, reentry)
    trade_plan = _trade_plan(
        symbol=symbol,
        target_symbol=target_symbol,
        risk_target_weight=target_weight,
        route_target_weight=target_weight_for_symbol if route_applies else 0.0,
        snapshots=snapshots,
        portfolio_value=portfolio_value,
        route_applies=route_applies,
        route_weight_items=route_weight_items,
    )
    return {
        "symbol": symbol,
        "status": status,
        "action": action,
        "sell_fraction": round(sell_fraction, 6),
        "target_symbol": target_symbol,
        "target_weight": round(target_weight_for_symbol, 6),
        "target_notional": round(target_notional, 2),
        "reference_price": round(price, 4) if price else None,
        "target_shares": round(target_shares, 4) if target_shares is not None else None,
        "route_defcon": routing.get("defcon"),
        "route_reason": routing.get("reason"),
        "top_reasons": reasons,
        "invalidation": invalidation,
        "confidence_level": (layer.get("action_confidence") or {}).get("level"),
        "confidence_score": (layer.get("action_confidence") or {}).get("score"),
        "trade_plan": trade_plan,
    }


def _today_ops(action_intents: Dict[str, Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, Any]:
    actionable = [row for row in action_intents.values() if row.get("action") in {"SELL_AND_ROUTE", "REDUCE_AND_ROUTE"}]
    data_quality = payload.get("data_quality") or {}
    ibkr = payload.get("ibkr") or {}
    destinations: Dict[str, float] = {}
    for row in actionable:
        legs = [
            leg for leg in ((row.get("trade_plan") or {}).get("legs") or [])
            if str(leg.get("role") or "") == "defense_route"
        ]
        if legs:
            for leg in legs:
                symbol = str(leg.get("symbol") or "")
                if symbol:
                    destinations[symbol] = destinations.get(symbol, 0.0) + _float(leg.get("target_notional"), 0.0)
            continue
        symbol = str(row.get("target_symbol") or "")
        if symbol:
            destinations[symbol] = destinations.get(symbol, 0.0) + _float(row.get("target_notional"), 0.0)
    reasons = []
    for row in actionable:
        for reason in row.get("top_reasons") or []:
            if reason not in reasons:
                reasons.append(reason)
            if len(reasons) >= 3:
                break
        if len(reasons) >= 3:
            break
    if not reasons:
        reasons = ["No sell/routing action is currently required."]
    return {
        "requires_action": bool(actionable),
        "headline": "需要处置" if actionable else "无需主动处置",
        "action_count": len(actionable),
        "top_reasons": reasons[:3],
        "destinations": {k: round(v, 2) for k, v in sorted(destinations.items())},
        "data_quality": data_quality.get("level", "NA"),
        "data_quality_score": data_quality.get("overall_score"),
        "ibkr_source": ibkr.get("source", "disabled"),
        "ibkr_stale": bool(ibkr.get("snapshot_stale")),
        "note": "advisory only; no orders are placed",
    }


def _trade_plan(
    *,
    symbol: str,
    target_symbol: str,
    risk_target_weight: float,
    route_target_weight: float,
    snapshots: Dict[str, SymbolSnapshot],
    portfolio_value: float,
    route_applies: bool,
    route_weight_items: Iterable[tuple[str, float]] = (),
) -> Dict[str, Any]:
    legs = [_target_leg(symbol, risk_target_weight, snapshots, portfolio_value, "risk")]
    route_items = list(route_weight_items)
    if route_applies and not route_items and target_symbol and target_symbol != "-":
        route_items = [(target_symbol, 1.0)]
    if route_applies:
        for leg_symbol, share in route_items:
            legs.append(_target_leg(leg_symbol, route_target_weight * share, snapshots, portfolio_value, "defense_route"))
    return {
        "portfolio_value": round(portfolio_value, 2),
        "legs": legs,
        "total_target_weight": round(sum(_float(row.get("target_weight"), 0.0) for row in legs), 6),
        "total_target_notional": round(sum(_float(row.get("target_notional"), 0.0) for row in legs), 2),
    }


def _route_weight_items(routing: Dict[str, Any], fallback_symbol: str) -> list[tuple[str, float]]:
    raw = routing.get("weights") or {}
    items: list[tuple[str, float]] = []
    if isinstance(raw, dict):
        for symbol, value in raw.items():
            weight = _float(value, 0.0)
            if symbol and weight > 0:
                items.append((str(symbol), weight))
    total = sum(weight for _, weight in items)
    if total <= 0:
        return [(fallback_symbol, 1.0)] if fallback_symbol and fallback_symbol != "-" else []
    return [(symbol, weight / total) for symbol, weight in items]


def _route_target_label(route_weight_items: Iterable[tuple[str, float]], fallback_symbol: str) -> str:
    symbols = [symbol for symbol, _ in route_weight_items if symbol]
    if symbols:
        return "/".join(symbols)
    return fallback_symbol


def _target_leg(
    symbol: str,
    target_weight: float,
    snapshots: Dict[str, SymbolSnapshot],
    portfolio_value: float,
    role: str,
) -> Dict[str, Any]:
    price = _price_for(symbol, snapshots)
    notional = max(0.0, target_weight) * portfolio_value
    shares = notional / price if price and price > 0 else None
    return {
        "role": role,
        "symbol": symbol,
        "target_weight": round(max(0.0, target_weight), 6),
        "target_notional": round(notional, 2),
        "reference_price": round(price, 4) if price else None,
        "target_shares": round(shares, 4) if shares is not None else None,
    }


def _top_reasons(score: Dict[str, Any], routing: Dict[str, Any]) -> list[str]:
    reasons = []
    if score.get("hard_valve_hits"):
        reasons.append("Hard valves: " + ", ".join(score.get("hard_valve_hits") or []))
    if routing.get("applies"):
        reasons.append(str(routing.get("reason") or "routing active"))
    factors = []
    for module, rows in (score.get("factor_scores") or {}).items():
        for row in rows or []:
            factors.append((_float(row.get("score"), 0.0), module, row))
    factors.sort(key=lambda item: item[0], reverse=True)
    for points, module, row in factors:
        if points <= 0:
            continue
        text = f"{module}:{row.get('factor_id') or row.get('name')} +{points:g} - {row.get('explain', '')}"
        reasons.append(text.strip())
        if len(reasons) >= 3:
            break
    return reasons[:3]


def _invalidation(status: str, target_symbol: str, routing: Dict[str, Any], reentry: Dict[str, Any]) -> str:
    if routing.get("applies"):
        return "当硬阀门解除、评分降回 HOLD/WATCH 且再建仓审计通过时，本路由建议失效。"
    if status in {"HOLD", "WATCH"} and reentry.get("eligible"):
        return "若跌回雷达均线下方或逃顶分数重新升高，建仓建议失效。"
    if target_symbol in {"BOXX", "BRK.B", "QQQ", "SOXX"}:
        return "若风险腿重新满足趋势与审计条件，防守配置需要复核。"
    return "若触发硬阀门、数据置信度降为 LOW/BLOCKED 或状态升至 REDUCE 以上，本建议失效。"


def _price_for(symbol: str, snapshots: Dict[str, SymbolSnapshot]) -> Optional[float]:
    if symbol in {"-", "NA", ""}:
        return None
    aliases = {"BRK.B": "BRK.B", "BRK B": "BRK.B"}
    snap = snapshots.get(aliases.get(symbol, symbol))
    if snap is None:
        return None
    return snap.get("close")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
