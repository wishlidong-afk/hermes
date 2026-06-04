from __future__ import annotations

from typing import Any, Dict


def apply_cost(trade_notional: float, atr_pct: float | None = None, cfg: Dict[str, Any] | None = None) -> float:
    config = cfg or {}
    costs = config.get("costs", {})
    round_trip_bps = float(costs.get("round_trip_bps", 10.0))
    fixed_slip_bps = float(costs.get("fixed_slippage_bps", 0.0))
    atr_slip_k = float(costs.get("atr_slippage_k", 0.0))
    atr_component_bps = max(0.0, float(atr_pct or 0.0)) * atr_slip_k * 10000.0
    total_bps = round_trip_bps + max(fixed_slip_bps, atr_component_bps)
    return abs(float(trade_notional)) * total_bps / 10000.0
