"""IBKR executions reader — read-only fill history for reentry confirmations."""
from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "executions_cache.json"
_DEFAULT_LOOKBACK_DAYS = 21
_DEFAULT_CACHE_MAX_AGE_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class ExecutionRecord:
    exec_id: str
    symbol: str
    side: str
    shares: float
    price: float
    time: str
    account: str = ""
    order_id: Optional[int] = None
    perm_id: Optional[int] = None
    currency: str = "USD"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionSnapshot:
    records: List[ExecutionRecord] = field(default_factory=list)
    sync_time: str = ""
    source: str = "tws"  # tws | snapshot | unavailable
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    error: Optional[str] = None
    snapshot_age_seconds: Optional[float] = None
    snapshot_stale: bool = False
    client_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [row.to_dict() for row in self.records]
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ExecutionSnapshot":
        data = dict(payload)
        records = [ExecutionRecord(**row) for row in data.pop("records", [])]
        return cls(records=records, **data)


def read_executions(config: Optional[Dict[str, Any]] = None) -> ExecutionSnapshot:
    """Read recent executions from TWS/Gateway, falling back to local cache."""
    cfg = (config or {}).get("ibkr", {})
    if not bool(cfg.get("enabled", True)):
        return ExecutionSnapshot(source="disabled", sync_time=_now(), error="IBKR disabled")
    exec_cfg = cfg.get("executions", {}) if isinstance(cfg.get("executions"), dict) else {}
    if not bool(exec_cfg.get("enabled", True)):
        return ExecutionSnapshot(source="disabled", sync_time=_now(), error="IBKR executions disabled")

    host = cfg.get("host", "127.0.0.1")
    ports = cfg.get("ports", [4001, 4002, 7496, 7497])
    client_id = int(exec_cfg.get("client_id", int(cfg.get("client_id", 992)) + 50))
    client_id_retry_count = max(1, int(cfg.get("client_id_retry_count", 8)))
    connect_timeout = float(cfg.get("connect_timeout", 5))
    preflight_timeout = float(cfg.get("preflight_timeout", min(connect_timeout, 0.5)))
    lookback_days = int(exec_cfg.get("lookback_days", _DEFAULT_LOOKBACK_DAYS))
    cache_max_age = float(exec_cfg.get("cache_max_age_seconds", _DEFAULT_CACHE_MAX_AGE_SECONDS))

    open_ports = [int(port) for port in ports if _tcp_port_open(host, int(port), preflight_timeout)]
    if not open_ports:
        return _load_cache(
            error=f"Could not connect to TWS on any of {ports}",
            max_age_seconds=cache_max_age,
        )

    try:
        created_loop = _ensure_thread_event_loop()
        from ib_insync import ExecutionFilter, IB

        ib = IB()
        try:
            connected = False
            connected_client_id = client_id
            last_error = ""
            for port in open_ports:
                for candidate in _candidate_client_ids(client_id, client_id_retry_count):
                    try:
                        ib.connect(host, port, clientId=candidate, readonly=True, timeout=connect_timeout)
                        connected = True
                        connected_client_id = candidate
                        break
                    except Exception as exc:
                        last_error = str(exc)
                        if _client_id_in_use(exc):
                            continue
                        break
                if connected:
                    break
            if not connected:
                raise ConnectionError(f"Could not connect to TWS on {open_ports}: {last_error}")

            filt = ExecutionFilter()
            since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            # IBKR accepts local/TWS time strings; leave account/symbol empty to read all recent fills.
            filt.time = since.strftime("%Y%m%d %H:%M:%S")
            fills = ib.reqExecutions(filt)
            records = [_record_from_fill(fill) for fill in fills]
            snap = ExecutionSnapshot(
                records=records,
                sync_time=_now(),
                source="tws",
                lookback_days=lookback_days,
                snapshot_age_seconds=0.0,
                snapshot_stale=False,
                client_id=connected_client_id,
            )
            _save_cache(snap)
            return snap
        finally:
            try:
                ib.disconnect()
            finally:
                del ib
                _close_thread_event_loop(created_loop)
    except Exception as exc:
        return _load_cache(error=str(exc), max_age_seconds=cache_max_age)


def _record_from_fill(fill: Any) -> ExecutionRecord:
    contract = fill.contract
    execution = fill.execution
    return ExecutionRecord(
        exec_id=str(getattr(execution, "execId", "") or ""),
        symbol=str(getattr(contract, "symbol", "") or ""),
        side=str(getattr(execution, "side", "") or "").upper(),
        shares=float(getattr(execution, "shares", 0.0) or 0.0),
        price=float(getattr(execution, "price", 0.0) or 0.0),
        time=_exec_time(getattr(execution, "time", None)),
        account=str(getattr(execution, "acctNumber", "") or ""),
        order_id=int(getattr(execution, "orderId", 0) or 0),
        perm_id=int(getattr(execution, "permId", 0) or 0),
        currency=str(getattr(contract, "currency", "USD") or "USD"),
    )


def _exec_time(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _save_cache(snapshot: ExecutionSnapshot) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _load_cache(error: Optional[str], max_age_seconds: float) -> ExecutionSnapshot:
    if _CACHE_PATH.exists():
        try:
            snap = ExecutionSnapshot.from_dict(json.loads(_CACHE_PATH.read_text(encoding="utf-8")))
            snap.source = "snapshot"
            age = _age_seconds(snap.sync_time)
            snap.snapshot_age_seconds = age
            snap.snapshot_stale = bool(age is None or age > max_age_seconds)
            snap.error = _snapshot_error(error, snap.snapshot_stale, age, max_age_seconds)
            return snap
        except Exception:
            pass
    return ExecutionSnapshot(
        source="unavailable",
        sync_time="",
        error=error or "no executions cache available",
        snapshot_age_seconds=None,
        snapshot_stale=True,
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


def _ensure_thread_event_loop() -> Optional[asyncio.AbstractEventLoop]:
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


def _tcp_port_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _age_seconds(sync_time: str) -> Optional[float]:
    if not sync_time:
        return None
    try:
        stamped = datetime.fromisoformat(sync_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamped.astimezone(timezone.utc)).total_seconds())


def _snapshot_error(error: Optional[str], stale: bool, age_seconds: Optional[float], max_age_seconds: float) -> Optional[str]:
    parts = []
    if error:
        parts.append(error)
    if stale:
        parts.append("executions cache stale" if age_seconds is None else f"executions cache stale: age {age_seconds:.0f}s exceeds {max_age_seconds:.0f}s")
    return "; ".join(parts) if parts else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
