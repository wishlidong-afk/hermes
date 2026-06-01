from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from hermes_escape_top.core.contracts import ConfidenceState


def compute_confidence(
    data_conf: Optional[float],
    failover_state: Optional[Dict[str, Any]],
    staleness_days: Optional[float],
    drift_state: Optional[Dict[str, Any]],
    fragility: Optional[float],
    disagreement: Optional[float],
    cfg: Dict[str, Any],
) -> ConfidenceState:
    """Compute the system-wide decision confidence bucket.

    The confidence spine is deliberately conservative: missing sub-signals are
    not treated as safe, but as neutral/uncertain 0.5 components with notes.
    """

    conf_cfg = cfg.get("confidence", cfg)
    tau_stale = max(1e-9, float(conf_cfg.get("tau_stale", 3.0)))
    drift_psi_threshold = max(1e-9, float(conf_cfg.get("drift_psi_threshold", 0.25)))
    weakest_weight = _clip(float(conf_cfg.get("weakest_weight", 0.60)))
    normal_threshold = float(conf_cfg.get("normal_threshold", 0.80))
    caution_threshold = float(conf_cfg.get("caution_threshold", 0.55))

    notes: List[str] = []
    components = {
        "data": _component(data_conf, "data_conf", notes),
        "source": _source_component(failover_state, notes),
        "stale": _stale_component(staleness_days, tau_stale, notes),
        "drift": _drift_component(drift_state, drift_psi_threshold, notes),
        "fragility": 1.0 - _component(fragility, "fragility", notes),
        "agreement": 1.0 - _component(disagreement, "disagreement", notes),
    }
    components = {key: _clip(value) for key, value in components.items()}

    weakest_link = min(components, key=lambda key: components[key])
    weakest = components[weakest_link]
    geo = _geomean(components.values())
    confidence = _clip(weakest_weight * weakest + (1.0 - weakest_weight) * geo)

    if confidence >= normal_threshold:
        mode = "NORMAL"
    elif confidence >= caution_threshold:
        mode = "CAUTION"
    else:
        mode = "DEGRADED"
        notes.append("decision confidence degraded; human confirmation recommended")

    return ConfidenceState(
        decision_confidence=round(float(confidence), 6),
        mode=mode,
        components={key: round(float(value), 6) for key, value in components.items()},
        weakest_link=weakest_link,
        notes=notes,
    )


def _component(value: Optional[float], name: str, notes: List[str]) -> float:
    if value is None:
        notes.append(f"{name} missing; using neutral 0.5")
        return 0.5
    try:
        f = float(value)
    except (TypeError, ValueError):
        notes.append(f"{name} invalid; using neutral 0.5")
        return 0.5
    if not math.isfinite(f):
        notes.append(f"{name} non-finite; using neutral 0.5")
        return 0.5
    return _clip(f)


def _source_component(failover_state: Optional[Dict[str, Any]], notes: List[str]) -> float:
    if failover_state is None:
        notes.append("failover_state missing; using neutral 0.5")
        return 0.5
    if bool(failover_state.get("is_degraded", False)):
        rank = failover_state.get("active_source_rank")
        notes.append(f"source failover active; rank={rank}")
        return 0.70
    return 1.0


def _stale_component(staleness_days: Optional[float], tau_stale: float, notes: List[str]) -> float:
    if staleness_days is None:
        notes.append("staleness_days missing; using neutral 0.5")
        return 0.5
    try:
        days = max(0.0, float(staleness_days))
    except (TypeError, ValueError):
        notes.append("staleness_days invalid; using neutral 0.5")
        return 0.5
    if not math.isfinite(days):
        notes.append("staleness_days non-finite; using neutral 0.5")
        return 0.5
    return math.exp(-days / tau_stale)


def _drift_component(drift_state: Optional[Dict[str, Any]], psi_threshold: float, notes: List[str]) -> float:
    if drift_state is None:
        notes.append("drift_state missing; using neutral 0.5")
        return 0.5
    if bool(drift_state.get("alert", False)):
        notes.append("drift alert active")
        return 0.0
    psi = _component(drift_state.get("psi", 0.0), "drift_psi", notes)
    return 1.0 - _clip(psi / psi_threshold)


def _geomean(values) -> float:
    vals = [max(1e-9, float(value)) for value in values]
    return math.exp(sum(math.log(value) for value in vals) / len(vals))


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
