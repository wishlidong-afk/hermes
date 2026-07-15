from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

import pandas as pd

from .costs import apply_cost
from .metrics import equity_metrics
from .simulator import DayDecision, SimulationResult, simulate


class ExecutionTiming(str, Enum):
    LEGACY_CLOSE = "legacy_close"
    NEXT_OPEN = "next_open"
    NEXT_CLOSE = "next_close"


def execution_timing_sensitivity(
    decisions: list[DayDecision],
    price_frames: Dict[str, pd.DataFrame],
    cfg: Optional[Dict[str, Any]] = None,
    *,
    initial_capital: float = 100000.0,
    stress_slippage_bps: float = 25.0,
) -> Dict[str, object]:
    if stress_slippage_bps < 0:
        raise ValueError("stress_slippage_bps must be non-negative")
    specs = (
        ("legacy_close", ExecutionTiming.LEGACY_CLOSE, 0.0, "HISTORICAL_THEORETICAL_UPPER_BOUND"),
        ("next_open", ExecutionTiming.NEXT_OPEN, 0.0, "PRIMARY_REALISTIC"),
        ("next_close", ExecutionTiming.NEXT_CLOSE, 0.0, "ONE_TRADING_DAY_DELAY"),
        ("next_open_stress", ExecutionTiming.NEXT_OPEN, float(stress_slippage_bps), "STRESS"),
    )
    scenarios = []
    for scenario_id, timing, extra_slippage_bps, role in specs:
        result = simulate_execution_timing(
            decisions,
            price_frames,
            cfg,
            timing=timing,
            initial_capital=initial_capital,
            extra_slippage_bps=extra_slippage_bps,
        )
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "timing": timing.value,
                "role": role,
                "extra_slippage_bps": extra_slippage_bps,
                "metrics": result.metrics,
                "turnover": result.turnover,
                "executed_rebalances": sum(1 for row in result.rows if float(row.get("turnover", 0.0) or 0.0) > 0),
                "base_cost": round(sum(float(row.get("base_cost", row.get("cost", 0.0)) or 0.0) for row in result.rows), 6),
                "extra_slippage_cost": round(sum(float(row.get("slippage_cost", 0.0) or 0.0) for row in result.rows), 6),
                "equity_curve": result.equity_curve,
            }
        )
    return {
        "schema_version": "execution-timing-sensitivity-v1",
        "headline_scenario": "next_open",
        "open_quality": summarize_open_quality(price_frames, decisions),
        "scenarios": scenarios,
        "notes": [
            "legacy_close is retained only as the historical/theoretical upper-bound convention.",
            "next_open assigns signal-close-to-next-open gaps to the old holdings and executes the new target at the next open.",
            "next_close delays each close-generated target until the following close.",
            "Synthetic flat OHLC rows use an explicitly labeled log-midpoint open; observed and modeled coverage must be reviewed before headline use.",
        ],
    }


def summarize_open_quality(
    price_frames: Dict[str, pd.DataFrame],
    decisions: Optional[list[DayDecision]] = None,
) -> Dict[str, object]:
    counts: Dict[str, int] = {}
    by_leg: Dict[str, Dict[str, int]] = {}
    for leg, frame in sorted(price_frames.items()):
        if frame is None or frame.empty:
            continue
        labels = frame.get("open_quality", pd.Series("UNLABELED", index=frame.index)).fillna("UNLABELED").astype(str)
        local = {str(label): int(count) for label, count in labels.value_counts().sort_index().items()}
        by_leg[leg] = local
        for label, count in local.items():
            counts[label] = counts.get(label, 0) + count
    total = sum(counts.values())
    observed = counts.get("OBSERVED", 0)
    missing = counts.get("MISSING", 0)
    modeled = sum(count for label, count in counts.items() if label.startswith("MODELED_"))
    summary = {
        "total_rows": total,
        "observed_rows": observed,
        "modeled_rows": modeled,
        "missing_rows": missing,
        "observed_share": round(observed / total, 8) if total else 0.0,
        "counts": dict(sorted(counts.items())),
        "by_leg": by_leg,
    }
    if decisions is not None:
        summary.update(_required_open_quality(price_frames, decisions))
    return summary


def _required_open_quality(
    price_frames: Dict[str, pd.DataFrame],
    decisions: list[DayDecision],
) -> Dict[str, object]:
    frames = _normalize_price_frames(price_frames)
    ordered = sorted(decisions, key=lambda item: item.date)
    counts: Dict[str, int] = {}
    by_leg: Dict[str, Dict[str, int]] = {}
    for index in range(1, len(ordered)):
        day = pd.Timestamp(ordered[index].date)
        required_legs: set[str] = set()
        for source_index in (index - 2, index - 1):
            if source_index < 0:
                continue
            required_legs.update(
                leg
                for leg, weight in ordered[source_index].target_weights.items()
                if float(weight) > 1e-12
            )
        for leg in sorted(required_legs):
            frame = frames.get(leg)
            label = "MISSING"
            if frame is not None and day in frame.index:
                open_value = pd.to_numeric(
                    pd.Series([frame.at[day, "Open"] if "Open" in frame else None]),
                    errors="coerce",
                ).iloc[0]
                if pd.notna(open_value) and float(open_value) > 0:
                    raw_label = frame.at[day, "open_quality"] if "open_quality" in frame else "UNLABELED"
                    label = str(raw_label or "UNLABELED")
            counts[label] = counts.get(label, 0) + 1
            local = by_leg.setdefault(leg, {})
            local[label] = local.get(label, 0) + 1
    total = sum(counts.values())
    observed = counts.get("OBSERVED", 0)
    modeled = sum(count for label, count in counts.items() if label.startswith("MODELED_"))
    return {
        "required_total_rows": total,
        "required_observed_rows": observed,
        "required_modeled_rows": modeled,
        "required_missing_rows": counts.get("MISSING", 0),
        "required_observed_share": round(observed / total, 8) if total else 0.0,
        "required_counts": dict(sorted(counts.items())),
        "required_by_leg": by_leg,
    }


def simulate_execution_timing(
    decisions: list[DayDecision],
    price_frames: Dict[str, pd.DataFrame],
    cfg: Optional[Dict[str, Any]] = None,
    *,
    timing: ExecutionTiming | str = ExecutionTiming.LEGACY_CLOSE,
    initial_capital: float = 100000.0,
    extra_slippage_bps: float = 0.0,
) -> SimulationResult:
    """Replay close-generated decisions at an explicit executable price point.

    ``legacy_close`` delegates to the original close-to-close simulator and is
    retained only as the historical/theoretical upper-bound convention.
    ``next_open`` and ``next_close`` delay a close-generated signal until the
    next trading day's open or close respectively.
    """

    mode = ExecutionTiming(timing)
    if extra_slippage_bps < 0:
        raise ValueError("extra_slippage_bps must be non-negative")
    ordered = sorted(decisions, key=lambda item: item.date)
    if not ordered:
        return SimulationResult({}, 0.0, equity_metrics(pd.Series(dtype=float)).to_dict(), [])
    if len({item.date for item in ordered}) != len(ordered):
        raise ValueError("decision dates must be unique")

    frames = _normalize_price_frames(price_frames)
    if mode is ExecutionTiming.LEGACY_CLOSE:
        close_panel = {leg: frame["Close"] for leg, frame in frames.items() if "Close" in frame}
        return simulate(ordered, close_panel, cfg, initial_capital=initial_capital, enable={"costs"})
    return _simulate_delayed(
        ordered,
        frames,
        cfg or {},
        timing=mode,
        initial_capital=initial_capital,
        extra_slippage_bps=extra_slippage_bps,
    )


def _simulate_delayed(
    decisions: list[DayDecision],
    price_frames: Dict[str, pd.DataFrame],
    cfg: Dict[str, Any],
    *,
    timing: ExecutionTiming,
    initial_capital: float,
    extra_slippage_bps: float,
) -> SimulationResult:
    equity = float(initial_capital)
    active_weights: Dict[str, float] = {}
    pending: Optional[DayDecision] = None
    previous_date: Optional[str] = None
    equity_curve: Dict[str, float] = {}
    rows: list[Dict[str, object]] = []
    total_turnover = 0.0

    for decision in decisions:
        day = decision.date
        signal_weights = _normalize_weights(decision.target_weights)
        turnover = 0.0
        base_cost = 0.0
        slippage_cost = 0.0
        overnight_return = 0.0
        intraday_return = 0.0
        period_return = 0.0
        executed_signal_date: Optional[str] = None

        if previous_date is not None and timing is ExecutionTiming.NEXT_OPEN:
            overnight_return = _portfolio_segment_return(
                price_frames,
                active_weights,
                previous_date,
                "Close",
                day,
                "Open",
            )
            equity *= 1.0 + overnight_return
            if pending is not None:
                active_weights, turnover, base_cost, slippage_cost = _rebalance(
                    equity,
                    active_weights,
                    pending.target_weights,
                    cfg,
                    extra_slippage_bps,
                )
                equity -= base_cost + slippage_cost
                total_turnover += turnover
                executed_signal_date = pending.date
            intraday_return = _portfolio_segment_return(price_frames, active_weights, day, "Open", day, "Close")
            equity *= 1.0 + intraday_return
            period_return = (1.0 + overnight_return) * (1.0 + intraday_return) - 1.0

        elif previous_date is not None and timing is ExecutionTiming.NEXT_CLOSE:
            period_return = _portfolio_segment_return(
                price_frames,
                active_weights,
                previous_date,
                "Close",
                day,
                "Close",
            )
            equity *= 1.0 + period_return
            if pending is not None:
                active_weights, turnover, base_cost, slippage_cost = _rebalance(
                    equity,
                    active_weights,
                    pending.target_weights,
                    cfg,
                    extra_slippage_bps,
                )
                equity -= base_cost + slippage_cost
                total_turnover += turnover
                executed_signal_date = pending.date

        pending = DayDecision(day, signal_weights)
        equity_curve[day] = round(equity, 6)
        rows.append(
            {
                "date": day,
                "equity": round(equity, 6),
                "turnover": round(turnover, 6),
                "cost": round(base_cost + slippage_cost, 6),
                "base_cost": round(base_cost, 6),
                "slippage_cost": round(slippage_cost, 6),
                "period_return": round(period_return, 10),
                "overnight_return": round(overnight_return, 10),
                "intraday_return": round(intraday_return, 10),
                "weights": active_weights,
                "signal_weights": signal_weights,
                "executed_signal_date": executed_signal_date,
                "pending_signal_date": day,
            }
        )
        previous_date = day

    series = pd.Series(equity_curve, dtype=float)
    return SimulationResult(equity_curve, round(total_turnover, 6), equity_metrics(series).to_dict(), rows)


def _rebalance(
    equity: float,
    current: Dict[str, float],
    target: Dict[str, float],
    cfg: Dict[str, Any],
    extra_slippage_bps: float,
) -> tuple[Dict[str, float], float, float, float]:
    weights = _normalize_weights(target)
    turnover = sum(abs(weights.get(leg, 0.0) - current.get(leg, 0.0)) for leg in set(weights) | set(current))
    base_cost = apply_cost(equity * turnover, None, cfg)
    slippage_cost = abs(equity * turnover) * float(extra_slippage_bps) / 10000.0
    return weights, turnover, base_cost, slippage_cost


def _portfolio_segment_return(
    price_frames: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
    start_date: str,
    start_field: str,
    end_date: str,
    end_field: str,
) -> float:
    total = 0.0
    for leg, weight in weights.items():
        if weight <= 0:
            continue
        start = _bar_value(price_frames, leg, start_date, start_field)
        end = _bar_value(price_frames, leg, end_date, end_field)
        total += float(weight) * (end / start - 1.0)
    return total


def _bar_value(price_frames: Dict[str, pd.DataFrame], leg: str, day: str, field: str) -> float:
    frame = price_frames.get(leg)
    stamp = pd.Timestamp(day)
    if frame is None or field not in frame or stamp not in frame.index:
        raise ValueError(f"{leg} missing {field} for {day}")
    value = pd.to_numeric(pd.Series([frame.at[stamp, field]]), errors="coerce").iloc[0]
    if pd.isna(value) or float(value) <= 0:
        raise ValueError(f"{leg} invalid {field} for {day}")
    return float(value)


def _normalize_price_frames(price_frames: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for leg, frame in price_frames.items():
        if frame is None or frame.empty:
            out[leg] = pd.DataFrame()
            continue
        local = frame.copy()
        local.index = pd.to_datetime(local.index, errors="coerce")
        local = local.loc[~local.index.isna()].sort_index()
        if local.index.has_duplicates:
            local = local.loc[~local.index.duplicated(keep="last")]
        for field in ["Open", "Close"]:
            if field in local:
                local[field] = pd.to_numeric(local[field], errors="coerce")
        out[leg] = local
    return out


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    cleaned = {leg: max(0.0, float(weight)) for leg, weight in weights.items()}
    gross = sum(cleaned.values())
    if gross > 1.0:
        cleaned = {leg: weight / gross for leg, weight in cleaned.items()}
    return {leg: round(weight, 8) for leg, weight in sorted(cleaned.items()) if weight > 1e-12}
