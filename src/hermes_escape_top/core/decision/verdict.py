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
    # The signal level *before* any second-close hold. This is what must be fed
    # back as next close's ``previous_status`` so a persistent upgrade confirms on
    # the second close (feeding back the held WATCH would lock it at WATCH forever).
    raw_status: str = "HOLD"


def make_verdict(inputs: VerdictInput, config: Dict[str, Any], require_confirmation: bool = False) -> VerdictResult:
    if inputs.hard_valve_hits:
        return VerdictResult(
            status="EXIT",
            sell_fraction=1.0,
            hard_override=True,
            reasons=[f"Hard valve override: {','.join(inputs.hard_valve_hits)}"],
            raw_status="EXIT",
        )

    # Decision stabilizer (F1+F2): hysteresis on the status ladder + second-close
    # confirmation for soft upgrades. Flag-gated, default OFF → byte-identical to the
    # flat-threshold, no-confirmation behaviour. Hard valves above always bypass it.
    feats = config.get("features", {})
    stabilizer = bool(feats.get("use_decision_stabilizer", False))
    # The two halves of the stabilizer can be enabled independently so a
    # hysteresis-only variant (anti-chatter without the exit-deepening confirmation
    # delay) can be backtested. use_decision_stabilizer = both (back-compat).
    hysteresis_on = stabilizer or bool(feats.get("use_status_hysteresis", False))
    confirmation_on = stabilizer or bool(feats.get("use_close_confirmation", False))
    status = status_from_score(
        inputs.score,
        config,
        relief=inputs.threshold_relief,
        previous_status=inputs.previous_status if hysteresis_on else None,
        hysteresis=hysteresis_on,
    )
    reasons = [f"Base score status: {status} ({inputs.score:.2f})"]
    if hysteresis_on and inputs.previous_status:
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

    # Signal level before any second-close hold — fed back as next close's
    # previous_status so a persistent upgrade confirms (rather than re-triggering).
    raw_status = status

    confirmation_required = False
    if (require_confirmation or confirmation_on) and status in SELL_STATES:
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
        sell_fraction=sell_fraction_for(inputs.symbol, status, config, score=inputs.score),
        reasons=reasons,
        confirmation_required=confirmation_required,
        raw_status=raw_status,
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


def sell_fraction_for(symbol: str, status: str, config: Dict[str, Any], score: Optional[float] = None) -> float:
    if status in {"HOLD", "WATCH"}:
        return 0.0
    table = config.get("sell_fractions", {}).get(symbol) or config.get("sell_fractions", {}).get("default", {})
    step_frac = float(table.get(status, 0.0))
    # ② Smooth the status→fraction staircase. Default "step" = original behaviour.
    # "continuous" interpolates the fraction by the actual score between rung anchors,
    # killing the 69→70 cliff (a 1-pt score move no longer jumps the position ~35pp).
    # max(continuous, step) keeps module-forced minima (e.g. C>=18 → REDUCE) intact
    # even when the raw score sits below that rung's natural threshold.
    mode = str(config.get("sell_fraction_mode", "step"))
    if mode != "continuous" or score is None:
        return step_frac
    cont = _continuous_fraction(float(score), table, config.get("status_thresholds", {}))
    return max(0.0, min(1.0, max(cont, step_frac)))


def _continuous_fraction(score: float, table: Dict[str, Any], thresholds: Dict[str, Any]) -> float:
    """Piecewise-linear fraction through the (threshold, fraction) anchors of the
    sell rungs, sorted by threshold. Flat outside the anchor range."""
    pts = []
    for rung in ("TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"):
        if rung in thresholds and rung in table:
            pts.append((float(thresholds[rung]), float(table[rung])))
    if not pts:
        return 0.0
    pts.sort()
    if score <= pts[0][0]:
        return pts[0][1]
    if score >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= score <= x1:
            if x1 == x0:
                return y1
            return y0 + (score - x0) / (x1 - x0) * (y1 - y0)
    return pts[-1][1]


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
