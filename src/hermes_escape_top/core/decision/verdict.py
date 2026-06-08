from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


STATUS_LADDER = ["HOLD", "WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"]
SELL_STATES = {"TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"}


@dataclass(frozen=True)
class VerdictInput:
    symbol: str
    score: float
    module_scores: Dict[str, float]
    hard_valve_hits: list[str] = field(default_factory=list)
    missing_weight: float = 0.0
    red_light_count: int = 0
    qqq_below_ema20: bool = False
    previous_status: Optional[str] = None
    threshold_relief: float = 0.0


@dataclass(frozen=True)
class VerdictResult:
    status: str
    sell_fraction: float
    reasons: list[str]
    hard_override: bool = False
    confirmation_required: bool = False


def make_verdict(inputs: VerdictInput, config: Dict[str, Any], require_confirmation: bool = False) -> VerdictResult:
    if inputs.hard_valve_hits:
        return VerdictResult(
            status="EXIT",
            sell_fraction=1.0,
            hard_override=True,
            reasons=[f"Hard valve override: {','.join(inputs.hard_valve_hits)}"],
        )

    # Decision stabilizer (F1+F2): hysteresis on the status ladder + second-close
    # confirmation for soft upgrades. Flag-gated, default OFF → byte-identical to the
    # flat-threshold, no-confirmation behaviour. Hard valves above always bypass it.
    stabilizer = bool(config.get("features", {}).get("use_decision_stabilizer", False))
    status = status_from_score(
        inputs.score,
        config,
        relief=inputs.threshold_relief,
        previous_status=inputs.previous_status if stabilizer else None,
        hysteresis=stabilizer,
    )
    reasons = [f"Base score status: {status} ({inputs.score:.2f})"]
    if stabilizer and inputs.previous_status:
        reasons.append(f"Hysteresis active (prev={inputs.previous_status})")
    if inputs.threshold_relief > 0:
        reasons.append(f"Arm-then-fire: leading macro armed, thresholds eased {inputs.threshold_relief:.1f}")
    modules = inputs.module_scores

    if modules.get("C", 0.0) >= 18:
        status = at_least(status, "REDUCE")
        reasons.append("C module >=18: minimum REDUCE")
    if modules.get("B", 0.0) >= 18 and modules.get("C", 0.0) >= 12:
        status = at_least(status, "DEFENSIVE_EXIT")
        reasons.append("B module >=18 and C module >=12: minimum DEFENSIVE_EXIT")
    if inputs.red_light_count >= 4:
        status = at_least(status, "REDUCE")
        reasons.append("Red-light factor count >=4: minimum REDUCE")
    if inputs.symbol in {"FNGU", "SOXL"} and inputs.qqq_below_ema20:
        status = at_least(status, "TRIM")
        reasons.append("Leveraged sleeve while QQQ below EMA20: minimum TRIM")
    if inputs.missing_weight > float(config.get("missing", {}).get("blind_spot_threshold", 30)):
        status = upgrade_one(status)
        reasons.append("Missing data weight exceeds blind-spot threshold: upgrade one level")

    confirmation_required = False
    if (require_confirmation or stabilizer) and status in SELL_STATES:
        previous = inputs.previous_status or "HOLD"
        if risk_rank(previous) < risk_rank(status):
            confirmation_required = True
            reasons.append("Soft sell signal requires second close confirmation")
            # Hold at the previous confirmed level (spec: 保留上一已确认级别), but
            # surface at least WATCH so the pending signal is visible. When the
            # previous level was already a sell-state this avoids wrongly
            # de-escalating it down to WATCH.
            status = at_least(previous, "WATCH")

    return VerdictResult(
        status=status,
        sell_fraction=sell_fraction_for(inputs.symbol, status, config),
        reasons=reasons,
        confirmation_required=confirmation_required,
    )


def status_from_score(
    score: float,
    config: Dict[str, Any],
    relief: float = 0.0,
    previous_status: Optional[str] = None,
    hysteresis: bool = False,
) -> str:
    """Map score to status. ``relief`` (arm-then-fire) lowers every threshold so a
    given technical score triggers a more defensive status earlier — but only the
    WATCH..EXIT ladder thresholds, never below WATCH.

    When ``hysteresis`` is on and a ``previous_status`` is given, a rung that the
    symbol was already at (or above) uses the lower ``exit`` threshold instead of
    the ``enter`` threshold, making de-escalation sticky (anti-chatter). With
    ``hysteresis=False`` / ``previous_status=None`` (defaults) the result is the
    original flat-threshold behaviour byte-for-byte."""
    thresholds = config.get("status_thresholds", {})
    if not (hysteresis and previous_status):
        selected = "HOLD"
        for status, threshold in sorted(thresholds.items(), key=lambda item: float(item[1])):
            eff = float(threshold) - (relief if status != "WATCH" else 0.0)
            if score >= eff:
                selected = status
        return selected

    hcfg = config.get("hysteresis", {})
    enter = hcfg.get("enter", {})
    exit_ = hcfg.get("exit", {})
    prev_rank = risk_rank(previous_status)
    selected = "HOLD"
    for status, base in sorted(thresholds.items(), key=lambda item: float(item[1])):
        enter_thr = float(enter.get(status, base))
        exit_thr = float(exit_.get(status, base))
        # Sticky: if we were already at/above this rung, only leave it below the
        # (lower) exit threshold; otherwise require the (higher) enter threshold.
        chosen = exit_thr if prev_rank >= risk_rank(status) else enter_thr
        eff = chosen - (relief if status != "WATCH" else 0.0)
        if score >= eff:
            selected = status
    return selected


def sell_fraction_for(symbol: str, status: str, config: Dict[str, Any]) -> float:
    if status in {"HOLD", "WATCH"}:
        return 0.0
    table = config.get("sell_fractions", {}).get(symbol) or config.get("sell_fractions", {}).get("default", {})
    return float(table.get(status, 0.0))


def at_least(status: str, minimum: str) -> str:
    return status if risk_rank(status) >= risk_rank(minimum) else minimum


def upgrade_one(status: str) -> str:
    idx = min(len(STATUS_LADDER) - 1, risk_rank(status) + 1)
    return STATUS_LADDER[idx]


def risk_rank(status: str) -> int:
    try:
        return STATUS_LADDER.index(status)
    except ValueError:
        return 0
