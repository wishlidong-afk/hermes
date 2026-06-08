from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from ..config import load_config, resolve_path, trade_symbols
from ..core.data.manifest import verify_manifest, write_manifest
from ..core.data.store import safe_symbol
from ..core.data.state_store import write_refresh_run
from ..pipeline import score_pipeline
from ..scripts.backfill_history import all_backfill_symbols, backfill


def refresh_score_with_market_data(requested_as_of: Any = "latest") -> Dict[str, Any]:
    """Refresh OHLCV first, then score the newest locally available trading day."""
    started = time.perf_counter()
    steps = []
    config = load_config()
    history_dir = resolve_path(config, "history_dir")
    state_db_path = resolve_path(config, "archive_dir") / "hermes_state.sqlite"
    symbols = all_backfill_symbols(config)
    latest_before = latest_history_date(config, _critical_symbols(config))
    stale_flow_symbols = _stale_symbols(config, _flow_symbols(config), latest_before) if latest_before else []
    if _history_is_fresh(latest_before) and not stale_flow_symbols:
        refresh = {}
        history_refreshed = False
        skip_reason = f"core history already fresh at {latest_before}"
        steps.append(_step("history_refresh", "SKIPPED", started, reason=skip_reason, symbols_requested=0))
    else:
        step_start = time.perf_counter()
        refresh_symbols = symbols if not _history_is_fresh(latest_before) else stale_flow_symbols
        refresh = backfill(
            refresh_symbols,
            start=(date.today() - timedelta(days=500)).isoformat(),
            end=None,
            store_dir=history_dir,
            repair_overlap_days=5,
        )
        history_refreshed = True
        skip_reason = "" if refresh_symbols == symbols else f"core fresh; refreshed stale flow symbols: {','.join(stale_flow_symbols)}"
        steps.append(_step(
            "history_refresh",
            "OK",
            step_start,
            symbols_requested=len(refresh_symbols),
            symbols_updated=sum(1 for item in refresh.values() if item.updated),
            reason=skip_reason,
        ))
    manifest_start = time.perf_counter()
    manifest_info = _refresh_manifest(config, history_refreshed)
    steps.append(_step(
        "manifest_freeze",
        manifest_info["status"],
        manifest_start,
        refrozen=manifest_info.get("refrozen"),
        in_sync=manifest_info.get("in_sync"),
        pre_in_sync=manifest_info.get("pre_in_sync"),
    ))
    as_of = latest_history_date(config, _critical_symbols(config)) or _normalize_as_of(requested_as_of)
    score_start = time.perf_counter()
    payload = score_pipeline(as_of)
    steps.append(_step("score_pipeline", "OK", score_start, as_of=as_of))
    soft = payload.get("soft_data") or {}
    soft_records = soft.get("records") or {}
    steps.append(_step(
        "soft_data_snapshot",
        "OK" if soft_records else "MISSING",
        score_start,
        records=len(soft_records),
        proxy_count=sum(1 for row in soft_records.values() if row.get("is_proxy")),
        latency_count=sum(1 for row in soft_records.values() if int(row.get("latency_days") or 0) > 0),
    ))
    flow = payload.get("flow") or {}
    ibkr = payload.get("ibkr") or {}
    steps.append(_step(
        "flow_snapshot",
        "OK" if flow.get("component_baskets") else "MISSING",
        score_start,
        baskets=list((flow.get("component_baskets") or {}).keys()),
    ))
    steps.append(_step(
        "ibkr_snapshot",
        "OK" if ibkr.get("source") == "tws" else "DEGRADED",
        score_start,
        source=ibkr.get("source"),
        stale=ibkr.get("snapshot_stale"),
        error=ibkr.get("error"),
    ))
    steps.append(_step(
        "audit_write",
        "OK" if payload.get("audit_log_path") and payload.get("state") else "MISSING",
        score_start,
        audit_log_path=payload.get("audit_log_path"),
        state_db_path=(payload.get("state") or {}).get("db_path"),
        score_run_id=(payload.get("state") or {}).get("score_run_id"),
    ))
    web_ready = all(payload.get(key) for key in ["today_ops", "action_intents", "data_quality_breakdown"])
    steps.append(_step(
        "web_payload",
        "OK" if web_ready else "MISSING",
        score_start,
        today_ops=bool(payload.get("today_ops")),
        action_intents=len(payload.get("action_intents") or {}),
        quality_sources=len((payload.get("data_quality_breakdown") or {}).get("sources") or []),
    ))
    overall_status = "OK"
    if any(step.get("status") in {"MISSING", "DEGRADED", "ERROR"} for step in steps):
        overall_status = "DEGRADED"
    payload["refresh_status"] = {
        "status": overall_status,
        "history_refreshed": history_refreshed,
        "skip_reason": skip_reason,
        "requested_as_of": str(requested_as_of),
        "effective_as_of": as_of,
        "history_dir": str(history_dir),
        "symbols_requested": len(symbols),
        "symbols_refreshed_requested": len(refresh),
        "symbols_updated": sum(1 for item in refresh.values() if item.updated),
        "trading_days_stale": _completed_trading_days_after(as_of),
        "manifest": manifest_info,
        "latest_by_symbol": {
            symbol: result.end_date
            for symbol, result in sorted(refresh.items())
            if symbol in _critical_symbols(config)
        },
    }
    refresh_meta = write_refresh_run(
        state_db_path,
        requested_as_of=requested_as_of,
        effective_as_of=as_of,
        status=overall_status,
        steps=steps,
        refresh_status=payload["refresh_status"],
        payload_hash=payload.get("input_hash"),
        retention=config.get("state_retention"),
    )
    payload["refresh_status"]["state_db_path"] = refresh_meta["state_db_path"]
    payload["refresh_status"]["refresh_run_id"] = refresh_meta["refresh_run_id"]
    payload["refresh_status"]["steps"] = steps
    return payload


def _step(name: str, status: str, step_start: float, **extra: Any) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "duration_ms": round((time.perf_counter() - step_start) * 1000.0, 2),
        **extra,
    }


def _completed_trading_days_after(as_of: Optional[str], today: Optional[date] = None) -> int:
    """Count expected completed US-market trading days strictly after ``as_of``
    and strictly before ``today``.

    Weekday approximation (Mon-Fri, no holiday calendar). Holidays may slightly
    over-report staleness, which is the safe direction — the whole point is to
    stop hiding a real gap, not to silently pass it.
    """
    today = today or date.today()
    try:
        start = date.fromisoformat(str(as_of)[:10])
    except (ValueError, TypeError):
        return 0
    count = 0
    cur = start + timedelta(days=1)
    while cur < today:
        if cur.weekday() < 5:  # Mon-Fri
            count += 1
        cur += timedelta(days=1)
    return count


def _history_is_fresh(as_of: Optional[str], max_trading_day_lag: int = 0) -> bool:
    """Fresh only when no completed trading day is missing since ``as_of``.

    Replaces the old calendar-lag<=3 rule, which let a Thursday bar viewed on
    the following Sunday pass as "fresh" while silently missing Friday's bar.
    Trading-day aware: weekends no longer mask a missing weekday bar.
    """
    if not as_of:
        return False
    return _completed_trading_days_after(as_of) <= max_trading_day_lag


def _refresh_manifest(config: Dict[str, Any], history_refreshed: bool) -> Dict[str, Any]:
    """Re-freeze data_manifest_latest.json so it never drifts from the CSVs.

    Re-freezes when history was refreshed, when the on-disk manifest no longer
    matches the data (drift), or when it is missing. Always reports in_sync so
    the WebUI can surface integrity. Read-only on failure.
    """
    history_dir = resolve_path(config, "history_dir")
    manifest_path = resolve_path(config, "archive_dir") / "data_manifest_latest.json"
    pre_in_sync: Optional[bool] = None
    try:
        if manifest_path.exists():
            pre_in_sync = verify_manifest(history_dir, manifest_path)
    except Exception:
        pre_in_sync = None
    refrozen = False
    if history_refreshed or pre_in_sync is False or not manifest_path.exists():
        try:
            write_manifest(history_dir, manifest_path)
            refrozen = True
        except Exception as exc:
            return {
                "status": "ERROR",
                "refrozen": False,
                "pre_in_sync": pre_in_sync,
                "in_sync": None,
                "error": str(exc),
                "path": str(manifest_path),
            }
    in_sync: Optional[bool] = None
    try:
        in_sync = verify_manifest(history_dir, manifest_path)
    except Exception:
        in_sync = None
    status = "OK" if in_sync else ("DRIFT" if in_sync is False else "MISSING")
    return {
        "status": status,
        "refrozen": refrozen,
        "pre_in_sync": pre_in_sync,
        "in_sync": in_sync,
        "path": str(manifest_path),
    }


def force_refresh_manifest(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Re-freeze the data manifest on demand (WebUI button). Returns status + frozen_at."""
    cfg = config or load_config()
    info = _refresh_manifest(cfg, history_refreshed=True)
    info.update(manifest_status(cfg))
    info["ok"] = info.get("status") == "OK"
    return info


def manifest_status(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Lightweight manifest integrity probe for the dashboard GET path.

    Does NOT re-freeze — read-only verification so a normal page load reports
    drift honestly without mutating anything.
    """
    cfg = config or load_config()
    history_dir = resolve_path(cfg, "history_dir")
    manifest_path = resolve_path(cfg, "archive_dir") / "data_manifest_latest.json"
    if not manifest_path.exists():
        return {"status": "MISSING", "in_sync": None, "frozen_at": None, "path": str(manifest_path)}
    in_sync: Optional[bool] = None
    try:
        in_sync = verify_manifest(history_dir, manifest_path)
    except Exception:
        in_sync = None
    frozen_at = None
    try:
        frozen_at = json.loads(manifest_path.read_text(encoding="utf-8")).get("frozen_at")
    except Exception:
        frozen_at = None
    status = "OK" if in_sync else ("DRIFT" if in_sync is False else "UNKNOWN")
    return {"status": status, "in_sync": in_sync, "frozen_at": frozen_at, "path": str(manifest_path)}


def latest_history_date(config: Optional[Dict[str, Any]] = None, symbols: Optional[Iterable[str]] = None) -> Optional[str]:
    cfg = config or load_config()
    history_dir = resolve_path(cfg, "history_dir")
    candidates = []
    for symbol in symbols or _critical_symbols(cfg):
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, usecols=["date"])
        except Exception:
            continue
        if frame.empty or "date" not in frame:
            continue
        dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        if not dates.empty:
            candidates.append(dates.max().date())
    if not candidates:
        return None
    return min(candidates).isoformat()


def latest_cached_as_of() -> Optional[str]:
    cfg = load_config()
    path = resolve_path(cfg, "archive_dir") / "audit_log.jsonl"
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line).get("payload", {})
        except Exception:
            continue
        as_of = str(payload.get("as_of", ""))[:10]
        if as_of:
            return as_of
    return None


def _critical_symbols(config: Dict[str, Any]) -> set[str]:
    symbols = set(trade_symbols(config))
    symbols.update({"QQQ", "SOXX", "SPY", "^VIX"})
    return symbols


def _flow_symbols(config: Dict[str, Any]) -> set[str]:
    symbols = set(trade_symbols(config))
    for components in config.get("component_proxies", {}).values():
        symbols.update(components)
    return symbols


def _stale_symbols(config: Dict[str, Any], symbols: Iterable[str], reference_as_of: Optional[str]) -> list[str]:
    if not reference_as_of:
        return sorted(set(symbols))
    latest = _latest_by_symbol(config, symbols)
    out = []
    ref = pd.Timestamp(str(reference_as_of)[:10]).date()
    for symbol in sorted(set(symbols)):
        day = latest.get(symbol)
        if day is None or day < ref:
            out.append(symbol)
    return out


def _latest_by_symbol(config: Dict[str, Any], symbols: Iterable[str]) -> Dict[str, Optional[date]]:
    history_dir = resolve_path(config, "history_dir")
    out: Dict[str, Optional[date]] = {}
    for symbol in symbols:
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            out[symbol] = None
            continue
        try:
            frame = pd.read_csv(path, usecols=["date"])
            dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
        except Exception:
            dates = pd.Series(dtype="datetime64[ns]")
        out[symbol] = dates.max().date() if not dates.empty else None
    return out


def _normalize_as_of(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[:4].isdigit():
        return text[:10]
    fallback = latest_history_date()
    if fallback:
        return fallback
    return "2026-06-02"
