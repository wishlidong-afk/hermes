"""IBKR positions reader (N6-T01) — read-only, absolutely no order placement.

Reads actual account positions and account summary from TWS/Gateway via ib_insync.
Falls back to a local JSON snapshot when TWS is not connected.
All position data is tagged with a sync_time so consumers know staleness.
"""
from __future__ import annotations

import json
import socket
import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_escape_top.core.safe_io import atomic_write_text

_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "positions_cache.json"
)
_DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 15 * 60


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
    snapshot_age_seconds: Optional[float] = None
    snapshot_stale: bool = False
    client_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["positions"] = [asdict(p) for p in self.positions]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PositionSnapshot":
        payload = dict(d)
        positions = [PositionRecord(**p) for p in payload.pop("positions", [])]
        return cls(positions=positions, **payload)

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
    client_id_retry_count = max(1, int(cfg.get("client_id_retry_count", 8)))
    connect_timeout = float(cfg.get("connect_timeout", 5))
    preflight_timeout = float(cfg.get("preflight_timeout", min(connect_timeout, 0.5)))
    snapshot_max_age = float(cfg.get("snapshot_max_age_seconds", _DEFAULT_SNAPSHOT_MAX_AGE_SECONDS))

    open_ports = []
    last_error = ""
    for port in ports:
        if _tcp_port_open(host, int(port), preflight_timeout):
            open_ports.append(int(port))
        else:
            last_error = f"No TCP listener on {host}:{port}"

    if not open_ports:
        detail = f": {last_error}" if last_error else ""
        return _load_snapshot(
            error=f"Could not connect to TWS on any of {ports}{detail}",
            max_age_seconds=snapshot_max_age,
        )

    try:
        created_loop = _ensure_thread_event_loop()
        from ib_insync import IB
        ib = IB()
        try:
            connected = False
            connected_client_id = client_id
            for port in open_ports:
                for candidate_client_id in _candidate_client_ids(client_id, client_id_retry_count):
                    try:
                        ib.connect(
                            host,
                            port,
                            clientId=candidate_client_id,
                            readonly=True,
                            timeout=connect_timeout,
                        )
                        connected = True
                        connected_client_id = candidate_client_id
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        if _client_id_in_use(exc):
                            continue
                        break
                if connected:
                    break

            if not connected:
                detail = f": {last_error}" if last_error else ""
                raise ConnectionError(f"Could not connect to TWS on any of {open_ports}{detail}")

            snapshot = _read_from_tws(ib, config, connected_client_id)
        finally:
            try:
                ib.disconnect()
            finally:
                del ib
                _close_thread_event_loop(created_loop)
        return snapshot

    except Exception as exc:
        return _load_snapshot(error=str(exc), max_age_seconds=snapshot_max_age)


def _ensure_thread_event_loop() -> Optional[asyncio.AbstractEventLoop]:
    """ib_insync's sync API needs an event loop in worker threads."""
    try:
        asyncio.get_event_loop()
        return None
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _close_thread_event_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    if loop is None:
        return
    if not loop.is_closed():
        loop.run_until_complete(asyncio.sleep(0))
        loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    asyncio.set_event_loop(None)


def _read_from_tws(ib: Any, config: Optional[Dict[str, Any]], client_id: int) -> PositionSnapshot:
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
        snapshot_age_seconds=0.0,
        snapshot_stale=False,
        client_id=client_id,
    )
    _save_snapshot(snap)
    return snap


def _save_snapshot(snap: PositionSnapshot) -> None:
    atomic_write_text(_SNAPSHOT_PATH, json.dumps(snap.to_dict(), indent=2, default=str))


DEMO_ACCOUNT_ID = "DEMO-MOCK"


def _is_real_snapshot() -> bool:
    """True only when an existing snapshot looks like genuine TWS-sourced data."""
    if not _SNAPSHOT_PATH.exists():
        return False
    try:
        d = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    account = str(d.get("account_id", "")).upper()
    source = str(d.get("source", "")).lower()
    if account in {DEMO_ACCOUNT_ID, "DEMO", "UNKNOWN", ""}:
        return False
    # A real account id that wasn't written by the demo path → treat as real.
    return source in {"tws", "snapshot"}


def write_demo_snapshot(force: bool = False) -> Dict[str, Any]:
    """Write a clearly-labelled DEMO positions snapshot so the reconcile panel
    has data to show when no TWS is connected.

    Safety: refuses to overwrite a real (TWS-sourced) snapshot unless ``force``.
    The account id is ``DEMO-MOCK`` and net_liq is a round demo figure, so it can
    never be mistaken for live positions. Read-only w.r.t. the brokerage.
    """
    if _is_real_snapshot() and not force:
        return {
            "ok": False,
            "reason": "REFUSED_REAL_SNAPSHOT",
            "message": "既有快照像真实持仓，拒绝覆盖（demo 仅在无真实快照时写入）。",
            "path": str(_SNAPSHOT_PATH),
        }
    net_liq = 100_000.0
    demo_positions = [
        PositionRecord("MSTR", "STK", 30.0, 250.0, 9_300.0),
        PositionRecord("FNGU", "STK", 400.0, 28.0, 12_800.0),
        PositionRecord("SOXL", "STK", 60.0, 240.0, 15_600.0),
        PositionRecord("BOXX", "STK", 180.0, 115.0, 21_000.0),
    ]
    gross = sum(p.market_value for p in demo_positions)
    snap = PositionSnapshot(
        account_id=DEMO_ACCOUNT_ID,
        net_liq=net_liq,
        gross_position_value=gross,
        total_cash=net_liq - gross,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        positions=demo_positions,
        sync_time=datetime.now(timezone.utc).isoformat(),
        source="snapshot",
        error="演示快照（mock）— 非真实持仓，仅用于驱动对账面板",
        snapshot_age_seconds=0.0,
        snapshot_stale=False,
        client_id=None,
    )
    _save_snapshot(snap)
    return {
        "ok": True,
        "account_id": DEMO_ACCOUNT_ID,
        "net_liq": net_liq,
        "positions": len(demo_positions),
        "path": str(_SNAPSHOT_PATH),
        "message": "已写入 DEMO 持仓快照；下次评分/刷新后对账面板将显示演示数据。",
    }


def _load_snapshot(error: Optional[str] = None, max_age_seconds: float = _DEFAULT_SNAPSHOT_MAX_AGE_SECONDS) -> PositionSnapshot:
    if _SNAPSHOT_PATH.exists():
        try:
            d = json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
            snap = PositionSnapshot.from_dict(d)
            snap.source = "snapshot"
            age = _snapshot_age_seconds(snap.sync_time)
            snap.snapshot_age_seconds = age
            snap.snapshot_stale = bool(age is None or age > max_age_seconds)
            snap.error = _snapshot_error(error, snap.snapshot_stale, age, max_age_seconds)
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
        snapshot_age_seconds=None,
        snapshot_stale=True,
        client_id=None,
        error=error or "no snapshot available",
    )


def _candidate_client_ids(base_client_id: int, retry_count: int) -> List[int]:
    return [int(base_client_id) + offset for offset in range(max(1, int(retry_count)))]


def _client_id_in_use(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        ("clientid" in text and "in use" in text)
        or ("client id" in text and "in use" in text)
        or ("326" in text and "client" in text)
    )


def _snapshot_age_seconds(sync_time: str) -> Optional[float]:
    if not sync_time:
        return None
    try:
        stamped = datetime.fromisoformat(sync_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamped.astimezone(timezone.utc)).total_seconds())


def _snapshot_error(
    error: Optional[str],
    stale: bool,
    age_seconds: Optional[float],
    max_age_seconds: float,
) -> Optional[str]:
    parts = []
    if error:
        parts.append(error)
    if stale:
        if age_seconds is None:
            parts.append("snapshot stale: missing sync_time")
        else:
            parts.append(
                f"snapshot stale: age {age_seconds:.0f}s exceeds {max_age_seconds:.0f}s"
            )
    return "; ".join(parts) if parts else None


def _tcp_port_open(host: str, port: int, timeout: float) -> bool:
    """Return whether a TWS/Gateway TCP port is listening before ib_insync connects."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _is_numeric(s: str) -> bool:
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False
