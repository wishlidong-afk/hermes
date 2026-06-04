"""IBKR positions reader (N6-T01) — read-only, absolutely no order placement.

Reads actual account positions and account summary from TWS/Gateway via ib_insync.
Falls back to a local JSON snapshot when TWS is not connected.
All position data is tagged with a sync_time so consumers know staleness.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "positions_cache.json"
)


@dataclass
class PositionRecord:
    symbol: str
    sec_type: str           # STK, OPT, FUT, …
    quantity: float
    avg_cost: float
    market_value: float     # may be 0 if price unavailable offline
    currency: str = "USD"
    is_option: bool = False


@dataclass
class PositionSnapshot:
    account_id: str
    net_liq: float
    gross_position_value: float
    total_cash: float
    unrealized_pnl: float
    realized_pnl: float
    positions: List[PositionRecord] = field(default_factory=list)
    sync_time: str = ""
    source: str = "tws"     # "tws" | "snapshot"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["positions"] = [asdict(p) for p in self.positions]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PositionSnapshot":
        positions = [PositionRecord(**p) for p in d.pop("positions", [])]
        return cls(positions=positions, **d)

    def position_weight(self, symbol: str) -> float:
        """Return actual weight (market_value / net_liq) for a symbol."""
        if self.net_liq <= 0:
            return 0.0
        mv = sum(p.market_value for p in self.positions if p.symbol == symbol)
        return mv / self.net_liq

    def position_dict(self) -> Dict[str, PositionRecord]:
        return {p.symbol: p for p in self.positions}


def read_positions(config: Optional[Dict[str, Any]] = None) -> PositionSnapshot:
    """Read live positions from TWS; fall back to snapshot on connection failure.

    Iron rule: this function NEVER places orders. It is strictly read-only.
    """
    cfg = (config or {}).get("ibkr", {})
    host = cfg.get("host", "127.0.0.1")
    ports = cfg.get("ports", [4001, 4002, 7496, 7497])
    client_id = int(cfg.get("client_id", 991))

    try:
        from ib_insync import IB
        ib = IB()
        connected = False
        for port in ports:
            try:
                ib.connect(host, port, clientId=client_id, readonly=True, timeout=5)
                connected = True
                break
            except Exception:
                continue

        if not connected:
            raise ConnectionError(f"Could not connect to TWS on any of {ports}")

        try:
            return _read_from_tws(ib, config)
        finally:
            ib.disconnect()

    except Exception as exc:
        return _load_snapshot(error=str(exc))


def _read_from_tws(ib: Any, config: Optional[Dict[str, Any]]) -> PositionSnapshot:
    """Internal: read from connected IB instance."""
    acct_vals = ib.accountValues()
    acct_map = {
        v.tag: float(v.value)
        for v in acct_vals
        if v.currency in ("USD", "") and v.value not in ("", None)
        and _is_numeric(v.value)
    }

    net_liq = acct_map.get("NetLiquidation", 0.0)
    gross_pv = acct_map.get("GrossPositionValue", 0.0)
    cash = acct_map.get("TotalCashValue", 0.0)
    upnl = acct_map.get("UnrealizedPnL", 0.0)
    rpnl = acct_map.get("RealizedPnL", 0.0)

    accounts = ib.managedAccounts()
    account_id = accounts[0] if accounts else "unknown"

    raw_positions = ib.positions()
    records = []
    for p in raw_positions:
        c = p.contract
        sym = c.symbol
        sec = c.secType
        qty = float(p.position)
        cost = float(p.avgCost)
        # Market value: quantity × last price × multiplier (options)
        # For options, use signed qty × cost × multiplier.
        # Broker already returns signed quantity (negative = short).
        mult = float(c.multiplier) if c.multiplier else 1.0
        mv = qty * cost * (mult if sec == "OPT" else 1.0)
        # Note: short options have negative qty → mv is negative (correctly reduces gross PV)
        records.append(PositionRecord(
            symbol=sym,
            sec_type=sec,
            quantity=qty,
            avg_cost=cost,
            market_value=mv,
            currency=c.currency or "USD",
            is_option=(sec == "OPT"),
        ))

    snap = PositionSnapshot(
        account_id=account_id,
        net_liq=net_liq,
        gross_position_value=gross_pv,
        total_cash=cash,
        unrealized_pnl=upnl,
        realized_pnl=rpnl,
        positions=records,
        sync_time=datetime.now(timezone.utc).isoformat(),
        source="tws",
    )
    _save_snapshot(snap)
    return snap


def _save_snapshot(snap: PositionSnapshot) -> None:
    _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SNAPSHOT_PATH.write_text(
        json.dumps(snap.to_dict(), indent=2, default=str), encoding="utf-8"
    )


def _load_snapshot(error: Optional[str] = None) -> PositionSnapshot:
    if _SNAPSHOT_PATH.exists():
        try:
            d = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            snap = PositionSnapshot.from_dict(d)
            snap.source = "snapshot"
            snap.error = error
            return snap
        except Exception:
            pass
    return PositionSnapshot(
        account_id="unknown",
        net_liq=0.0,
        gross_position_value=0.0,
        total_cash=0.0,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        sync_time="",
        source="unavailable",
        error=error or "no snapshot available",
    )


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
