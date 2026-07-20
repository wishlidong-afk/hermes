from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from ...config import trade_symbols


ROUTE_TRANSITION_THRESHOLD = 0.02
_CASH_RESERVOIR = "BOXX"


@dataclass(frozen=True)
class RouteTransitionResult:
    applied: bool
    reason: str
    changed_leg: Optional[str]
    direction: Optional[str]
    threshold: float
    raw_weights: Dict[str, float]
    weights: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied": self.applied,
            "reason": self.reason,
            "changed_leg": self.changed_leg,
            "direction": self.direction,
            "threshold": self.threshold,
            "raw_weights": dict(self.raw_weights),
            "weights": dict(self.weights),
        }


def route_leg_weights(
    config: Mapping[str, Any],
    sizing: Mapping[str, Mapping[str, Any]],
    routing: Mapping[str, Mapping[str, Any]],
) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for symbol in trade_symbols(dict(config)):
        cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        target = max(0.0, float(sizing.get(symbol, {}).get("target_weight", 0.0) or 0.0))
        if target:
            weights[symbol] = weights.get(symbol, 0.0) + target
        residual = max(0.0, cap - target)
        route = routing.get(symbol, {})
        route_weights = route.get("weights", {}) if route.get("applies") else {}
        if residual and route_weights:
            for leg, share in route_weights.items():
                weights[str(leg)] = weights.get(str(leg), 0.0) + residual * float(share)
        elif residual:
            weights[_CASH_RESERVOIR] = weights.get(_CASH_RESERVOIR, 0.0) + residual
    gross = sum(weights.values())
    if gross < 1.0:
        weights[_CASH_RESERVOIR] = weights.get(_CASH_RESERVOIR, 0.0) + (1.0 - gross)
    if gross > 1.0:
        weights = {leg: weight / gross for leg, weight in weights.items()}
    return _clean_weights(weights)


def apply_route_set_transition_buffer(
    config: Mapping[str, Any],
    current_weights: Mapping[str, float],
    previous_weights: Optional[Mapping[str, float]],
) -> RouteTransitionResult:
    """Suppress one sub-2pp route-set transition without touching risk legs."""
    raw = {str(leg): float(weight) for leg, weight in current_weights.items()}
    if not bool(config.get("features", {}).get("use_route_set_transition_buffer", False)):
        return _result(False, "flag_off", raw, raw)
    if not previous_weights:
        return _result(False, "no_previous_weights", raw, raw)

    previous = {str(leg): float(weight) for leg, weight in previous_weights.items()}
    risk_legs = set(trade_symbols(dict(config)))
    excluded = risk_legs | {_CASH_RESERVOIR}
    current_routes = {leg for leg, weight in raw.items() if weight > 1e-12 and leg not in excluded}
    previous_routes = {leg for leg, weight in previous.items() if weight > 1e-12 and leg not in excluded}
    changed = current_routes ^ previous_routes
    if len(changed) != 1:
        return _result(False, "not_single_route_set_change", raw, raw)

    leg = next(iter(changed))
    adjusted = dict(raw)
    if leg in current_routes:
        direction = "added"
        amount = float(raw.get(leg, 0.0))
        if amount >= ROUTE_TRANSITION_THRESHOLD:
            return _result(False, "change_not_below_threshold", raw, raw, leg, direction)
        adjusted.pop(leg, None)
        adjusted[_CASH_RESERVOIR] = adjusted.get(_CASH_RESERVOIR, 0.0) + amount
    else:
        direction = "removed"
        amount = float(previous.get(leg, 0.0))
        if amount >= ROUTE_TRANSITION_THRESHOLD:
            return _result(False, "change_not_below_threshold", raw, raw, leg, direction)
        if adjusted.get(_CASH_RESERVOIR, 0.0) + 1e-12 < amount:
            return _result(False, "insufficient_cash_reservoir", raw, raw, leg, direction)
        adjusted[leg] = amount
        adjusted[_CASH_RESERVOIR] = adjusted.get(_CASH_RESERVOIR, 0.0) - amount

    cleaned = _clean_weights(adjusted)
    for risk_leg in risk_legs:
        if cleaned.get(risk_leg, 0.0) != raw.get(risk_leg, 0.0):
            raise AssertionError(f"route transition buffer changed risk leg {risk_leg}")
    return _result(True, "suppressed_sub_2pp_transition", raw, cleaned, leg, direction)


def _result(
    applied: bool,
    reason: str,
    raw: Dict[str, float],
    weights: Dict[str, float],
    changed_leg: Optional[str] = None,
    direction: Optional[str] = None,
) -> RouteTransitionResult:
    return RouteTransitionResult(
        applied=applied,
        reason=reason,
        changed_leg=changed_leg,
        direction=direction,
        threshold=ROUTE_TRANSITION_THRESHOLD,
        raw_weights=dict(raw),
        weights=dict(weights),
    )


def _clean_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    return {
        str(leg): round(float(weight), 8)
        for leg, weight in sorted(weights.items())
        if float(weight) > 1e-12
    }
