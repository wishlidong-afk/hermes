"""IBKR reconciliation (N6-T02) — actual vs ideal position comparison.

Compares real IBKR positions against the pipeline's ideal target weights.
Produces a human-readable report for each trade symbol and route leg.
Never modifies positions or places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from hermes_escape_top.ibkr.positions import PositionSnapshot


# Symbols that can appear as route destinations (DEFCON 1/2/3 legs)
ROUTE_LEGS = {
    "BOXX", "BRK B", "BRK.B",   # DEFCON 1/2
    "SOXX", "SMH",               # SOXL → 1x (DEFCON 3)
    "QQQ",                       # FNGU/MSTR → 1x (DEFCON 3)
    "BIL", "SHV", "DBMF",        # cash-like / trend legs
}


@dataclass
class SymbolDelta:
    symbol: str
    ideal_weight: float         # from pipeline sizing
    actual_weight: float        # from IBKR (market_value / net_liq)
    delta_weight: float         # actual - ideal  (positive = over, negative = under)
    ideal_notional: float       # ideal_weight × net_liq
    actual_notional: float      # actual market value
    actual_shares: float
    avg_cost: float
    unrealized_pnl_est: float   # (actual_weight - ideal_weight) * net_liq as rough est
    status: str                 # MATCH | OVER | UNDER | MISSING | EXTRA
    note: str = ""


@dataclass
class ReconcileReport:
    account_id: str
    net_liq: float
    sync_time: str
    source: str
    trade_symbols: List[SymbolDelta] = field(default_factory=list)
    route_legs: List[SymbolDelta] = field(default_factory=list)
    extra_positions: List[SymbolDelta] = field(default_factory=list)
    total_ideal_exposure: float = 0.0
    total_actual_exposure: float = 0.0
    max_abs_delta: float = 0.0
    all_within_tolerance: bool = False
    error: Optional[str] = None
    snapshot_age_seconds: Optional[float] = None
    snapshot_stale: bool = False
    client_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["trade_symbols"] = [asdict(s) for s in self.trade_symbols]
        d["route_legs"] = [asdict(s) for s in self.route_legs]
        d["extra_positions"] = [asdict(s) for s in self.extra_positions]
        return d


def reconcile(
    snapshot: PositionSnapshot,
    pipeline_sizing: Dict[str, Dict[str, Any]],
    pipeline_routing: Optional[Dict[str, Dict[str, Any]]] = None,
    tolerance: float = 0.01,    # 1% weight tolerance for MATCH
) -> ReconcileReport:
    """Compare IBKR actual positions with pipeline ideal sizing.

    Args:
        snapshot:          Live IBKR positions from read_positions()
        pipeline_sizing:   payload["sizing"] — {symbol: {target_weight, ...}}
        pipeline_routing:  payload["routing"] — {symbol: {destination, ...}}
        tolerance:         Weight delta below which status = MATCH (default 1%)

    Returns:
        ReconcileReport with per-symbol deltas and summary statistics.
    """
    nl = snapshot.net_liq
    actual = snapshot.position_dict()

    trade_syms = sorted(pipeline_sizing.keys())
    ideal_weights: Dict[str, float] = {}
    for sym in trade_syms:
        ideal_weights[sym] = float(
            pipeline_sizing.get(sym, {}).get("target_weight", 0.0) or 0.0
        )

    # Collect expected route leg destinations.  Route legs receive the residual
    # sleeve capital (sleeve cap minus risky target), not the risky target itself.
    route_targets: Dict[str, float] = {}
    if pipeline_routing:
        for sym, rout in pipeline_routing.items():
            if rout.get("applies") is False:
                continue
            dest = str(rout.get("destination", "") or "")
            if dest and dest not in ("HOLD", "NONE", "-", ""):
                row = pipeline_sizing.get(sym, {})
                target_w = float(row.get("target_weight", 0.0) or 0.0)
                sleeve_cap = float(
                    row.get(
                        "sleeve_cap",
                        row.get("rule_sleeve_cap", row.get("reference_sleeve_cap", target_w)),
                    )
                    or 0.0
                )
                residual = max(0.0, sleeve_cap - target_w)
                weights = rout.get("weights") if isinstance(rout.get("weights"), dict) else {}
                if weights:
                    for leg, share in weights.items():
                        leg_name = str(leg)
                        route_targets[leg_name] = route_targets.get(leg_name, 0.0) + residual * float(share)
                else:
                    route_targets[dest] = route_targets.get(dest, 0.0) + residual

    # Build deltas for trade symbols
    trade_deltas: List[SymbolDelta] = []
    accounted: set = set()

    for sym in trade_syms:
        ideal_w = ideal_weights[sym]
        pos = actual.get(sym) or actual.get(sym.replace(".", " "))
        act_mv = pos.market_value if pos else 0.0
        act_qty = pos.quantity if pos else 0.0
        act_cost = pos.avg_cost if pos else 0.0
        act_w = act_mv / nl if nl > 0 else 0.0
        delta = act_w - ideal_w
        status = _status(ideal_w, act_w, tolerance)
        trade_deltas.append(SymbolDelta(
            symbol=sym, ideal_weight=ideal_w, actual_weight=act_w,
            delta_weight=delta, ideal_notional=ideal_w * nl,
            actual_notional=act_mv, actual_shares=act_qty,
            avg_cost=act_cost, unrealized_pnl_est=delta * nl,
            status=status,
            note=_note(status, delta, nl),
        ))
        if pos:
            accounted.add(sym)
            accounted.add(sym.replace(".", " "))

    # Route legs
    route_deltas: List[SymbolDelta] = []
    for dest, ideal_w in sorted(route_targets.items()):
        canon = dest.replace(".", " ")
        pos = actual.get(dest) or actual.get(canon)
        act_mv = pos.market_value if pos else 0.0
        act_qty = pos.quantity if pos else 0.0
        act_cost = pos.avg_cost if pos else 0.0
        act_w = act_mv / nl if nl > 0 else 0.0
        delta = act_w - ideal_w
        status = _status(ideal_w, act_w, tolerance)
        route_deltas.append(SymbolDelta(
            symbol=dest, ideal_weight=ideal_w, actual_weight=act_w,
            delta_weight=delta, ideal_notional=ideal_w * nl,
            actual_notional=act_mv, actual_shares=act_qty,
            avg_cost=act_cost, unrealized_pnl_est=delta * nl,
            status=status, note=f"route leg ({_note(status, delta, nl)})",
        ))
        if pos:
            accounted.add(dest)
            accounted.add(canon)

    # Extra positions not expected by the system
    extra_deltas: List[SymbolDelta] = []
    for sym, pos in actual.items():
        if sym not in accounted and not pos.is_option:
            # Check if it's a known route leg
            is_route = sym in ROUTE_LEGS or sym.replace(" ", ".") in ROUTE_LEGS
            act_w = pos.market_value / nl if nl > 0 else 0.0
            extra_deltas.append(SymbolDelta(
                symbol=sym, ideal_weight=0.0, actual_weight=act_w,
                delta_weight=act_w, ideal_notional=0.0,
                actual_notional=pos.market_value,
                actual_shares=pos.quantity, avg_cost=pos.avg_cost,
                unrealized_pnl_est=0.0,
                status="ROUTE_LEG" if is_route else "EXTRA",
                note="known route leg" if is_route else "not in current pipeline",
            ))

    all_deltas = trade_deltas + route_deltas
    max_abs = max((abs(d.delta_weight) for d in all_deltas), default=0.0)
    total_ideal = sum(d.ideal_weight for d in all_deltas)
    total_actual = sum(d.actual_weight for d in all_deltas)

    return ReconcileReport(
        account_id=snapshot.account_id,
        net_liq=nl,
        sync_time=snapshot.sync_time,
        source=snapshot.source,
        trade_symbols=trade_deltas,
        route_legs=route_deltas,
        extra_positions=extra_deltas,
        total_ideal_exposure=total_ideal,
        total_actual_exposure=total_actual,
        max_abs_delta=round(max_abs, 4),
        all_within_tolerance=max_abs <= tolerance,
        error=snapshot.error,
        snapshot_age_seconds=snapshot.snapshot_age_seconds,
        snapshot_stale=snapshot.snapshot_stale,
        client_id=snapshot.client_id,
    )


def _status(ideal: float, actual: float, tol: float) -> str:
    delta = actual - ideal
    if ideal == 0 and actual == 0:
        return "MATCH"
    if ideal == 0 and actual > 0:
        return "EXTRA"
    if actual == 0 and ideal > 0:
        return "MISSING"
    if abs(delta) <= tol:
        return "MATCH"
    return "OVER" if delta > 0 else "UNDER"


def _note(status: str, delta: float, nl: float) -> str:
    if status == "MATCH":
        return "within tolerance"
    notional = abs(delta * nl)
    direction = "over" if delta > 0 else "under"
    return f"{direction} by {abs(delta):.1%} (${notional:,.0f})"
