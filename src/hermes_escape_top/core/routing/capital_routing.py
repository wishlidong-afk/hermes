from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd

from ..data.base import SymbolSnapshot
from ..scoring.result import ScoreResult


SELL_STATUSES = {"REDUCE", "DEFENSIVE_EXIT", "EXIT"}


@dataclass(frozen=True)
class RoutingDecision:
    applies: bool
    defcon: str
    destination: str
    weights: Dict[str, float]
    reason: str

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["weights"] = {key: round(float(value), 6) for key, value in self.weights.items()}
        return payload


@dataclass(frozen=True)
class BrkbDefenseState:
    degraded: bool
    reason: str
    corr_to_spy: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        if payload["corr_to_spy"] is not None:
            payload["corr_to_spy"] = round(float(payload["corr_to_spy"]), 6)
        return payload


def route_capital(
    symbol: str,
    score: ScoreResult,
    config: Dict[str, Any],
    snapshots: Optional[Dict[str, SymbolSnapshot]] = None,
    histories: Optional[Dict[str, pd.DataFrame]] = None,
) -> RoutingDecision:
    should_route = score.status in SELL_STATUSES or bool(score.hard_valve_hits)
    if not should_route:
        return RoutingDecision(False, "NONE", "-", {}, "No capital routing: status does not require selling and no hard valve hit.")

    a_total = float(score.module_scores.get("A", 0.0))
    a1 = _factor_max(score, "A1_")
    a5 = _factor_max(score, "A5_")
    a7 = _factor_max(score, "A7_")
    a8 = _factor_max(score, "A8_")
    core_a = a1 + a5 + a7 + a8
    nuclear = (
        a_total >= 12
        or core_a >= 8
        or a1 >= 4
        or a5 >= 4
        or a7 >= 4
        or a8 >= 4
    )
    if nuclear:
        routing = config.get("routing", {}).get("defcon1", {})
        weights = {"BOXX": float(routing.get("BOXX", 1.0))}
        trend_weight = float(routing.get("TREND", 0.0))
        if trend_weight:
            weights[str(routing.get("trend_symbol", "DBMF"))] = trend_weight
        return RoutingDecision(
            True,
            "DEFCON1",
            "BOXX",
            weights,
            "Macro/liquidity nuclear condition: route sell proceeds to BOXX defensive sleeve.",
        )

    internal_break = (
        float(score.module_scores.get("D", 0.0)) >= 10
        or bool(score.hard_valve_hits)
        or _factor_max(score, "C8_") >= 3
        or _factor_max(score, "C6_") >= 3
    )
    if internal_break:
        defcon2 = config.get("routing", {}).get("defcon2", {})
        primary = str(defcon2.get("primary", "BRK.B"))
        fallback = str(defcon2.get("fallback", "BOXX"))
        brkb_state = evaluate_brkb_defense(snapshots or {}, histories or {}, config)
        if primary == "BRK.B" and brkb_state.degraded:
            return RoutingDecision(
                True,
                "DEFCON2",
                fallback,
                {fallback: 1.0},
                f"Internal break, but BRK.B defense sleeve degraded: {brkb_state.reason}; route to fallback.",
            )
        return RoutingDecision(
            True,
            "DEFCON2",
            primary,
            {primary: 1.0},
            "Internal break or hard valve: route sell proceeds to value-defense sleeve.",
        )

    mapping = config.get("routing", {}).get("defcon3", {})
    destination = str(mapping.get(symbol, "BOXX"))
    return RoutingDecision(
        True,
        "DEFCON3",
        destination,
        {destination: 1.0},
        "Routine risk reduction: route sell proceeds to corresponding 1x defensive instrument.",
    )


def _factor_max(score: ScoreResult, prefix: str) -> float:
    best = 0.0
    for rows in score.factor_scores.values():
        for row in rows:
            factor_id = str(row.get("factor_id", ""))
            if factor_id.startswith(prefix):
                best = max(best, float(row.get("score", 0.0) or 0.0))
    return best


def evaluate_brkb_defense(
    snapshots: Dict[str, SymbolSnapshot],
    histories: Dict[str, pd.DataFrame],
    config: Dict[str, Any],
) -> BrkbDefenseState:
    brkb = snapshots.get("BRK.B")
    if brkb is not None:
        close = brkb.get("close")
        ma200 = brkb.get("ma200")
        if close is not None and ma200 is not None and close <= ma200:
            return BrkbDefenseState(True, "BRK.B close <= MA200")
    brkb_hist = histories.get("BRK.B")
    spy_hist = histories.get("SPY")
    corr_window = int(config.get("routing", {}).get("defcon2", {}).get("brkb_corr_window", 60))
    corr_threshold = float(config.get("routing", {}).get("defcon2", {}).get("brkb_corr_threshold", 0.85))
    if brkb_hist is None or spy_hist is None or brkb_hist.empty or spy_hist.empty:
        return BrkbDefenseState(False, "BRK.B beta monitor unavailable")
    common = pd.concat(
        {
            "BRK.B": pd.to_numeric(brkb_hist["Close"], errors="coerce").pct_change(),
            "SPY": pd.to_numeric(spy_hist["Close"], errors="coerce").pct_change(),
        },
        axis=1,
    ).dropna().tail(corr_window)
    if len(common) < max(20, corr_window // 2):
        return BrkbDefenseState(False, "BRK.B/SPY common history insufficient")
    corr = float(common["BRK.B"].corr(common["SPY"]))
    if corr >= corr_threshold:
        return BrkbDefenseState(True, f"BRK.B/SPY correlation {corr:.2f} >= {corr_threshold:.2f}", corr)
    return BrkbDefenseState(False, f"BRK.B/SPY correlation {corr:.2f} below threshold", corr)
