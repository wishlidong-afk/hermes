from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from ..config import load_config, resolve_path, trade_symbols
from ..core.data.base import SymbolSnapshot
from ..core.data.manifest import verify_manifest, write_manifest
from ..core.safe_io import assert_pipeline_lease, pipeline_lock
from ..core.data.store import safe_symbol
from ..core.data.state_store import recent_ibkr_snapshots, write_ibkr_snapshot, write_refresh_run
from ..core.decision.action_intents import build_action_context
from ..ibkr.positions import read_positions
from ..ibkr.reconcile import reconcile as ibkr_reconcile
from ..pipeline import _score_pipeline_locked
from ..scripts.backfill_history import all_backfill_symbols, backfill, online_soft_history_symbols


IBKR_POSITION_OVERLAY = "ibkr_position_overlay.json"


def refresh_score_with_market_data(
    requested_as_of: Any = "latest",
    *,
    blocking: bool = True,
) -> Dict[str, Any]:
    """Run the complete refresh + score + refresh-ledger transaction."""
    config = load_config()
    lock_path = resolve_path(config, "archive_dir") / ".pipeline.lock"
    with pipeline_lock(blocking=blocking, timeout=600, path=lock_path) as lease:
        return _refresh_score_with_market_data_locked(requested_as_of, _lease=lease)


def refresh_positions_only(
    requested_as_of: Any = "latest",
    *,
    blocking: bool = True,
    base_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Refresh only the external IBKR position layer.

    This endpoint intentionally does not refresh market history and does not run
    score_pipeline. It reads live/cached IBKR positions, reconciles them against
    the currently displayed strategy payload, then stores a small overlay that the
    dashboard can merge onto the official run.
    """
    config = load_config()
    lock_path = resolve_path(config, "archive_dir") / ".pipeline.lock"
    with pipeline_lock(blocking=blocking, timeout=60, path=lock_path):
        payload = dict(base_payload or {})
        if not payload.get("as_of"):
            gating_symbols = ["QQQ", "SPY", *trade_symbols(config)]
            payload["as_of"] = latest_history_date(config, gating_symbols) or _normalize_as_of(requested_as_of)
        as_of = str(payload.get("as_of") or requested_as_of)[:10]
        if not config.get("ibkr", {}).get("enabled", False):
            ibkr = {"source": "disabled", "note": "set ibkr.enabled=true to activate"}
        else:
            snap = read_positions(config)
            ibkr = ibkr_reconcile(
                snap,
                payload.get("sizing") or {},
                payload.get("routing") or {},
            ).to_dict()

        archive_dir = resolve_path(config, "archive_dir")
        state_db_path = archive_dir / "hermes_state.sqlite"
        state_meta = write_ibkr_snapshot(
            state_db_path,
            as_of=as_of,
            ibkr=ibkr,
            retention=config.get("state_retention"),
        )
        history = recent_ibkr_snapshots(state_db_path, limit=5)
        refreshed_at = datetime.now(timezone.utc).isoformat()
        status = {
            "schema_version": "hermes-ibkr-position-overlay-v1",
            "status": "OK" if ibkr.get("source") == "tws" and not ibkr.get("snapshot_stale") else "DEGRADED",
            "as_of": as_of,
            "refreshed_at": refreshed_at,
            "base_input_hash": payload.get("input_hash"),
            "score_pipeline": False,
            "history_refreshed": False,
            "official_run_written": False,
            "state_db_path": state_meta["db_path"],
            "ibkr_snapshot_id": state_meta.get("ibkr_snapshot_id"),
        }
        overlay = {
            **status,
            "ibkr": ibkr,
        }
        _atomic_write_json(archive_dir / IBKR_POSITION_OVERLAY, overlay)
        payload["as_of"] = as_of
        payload["ibkr"] = ibkr
        payload["ibkr_history"] = history
        payload["ibkr_refresh_status"] = status
        payload["ok"] = status["status"] == "OK"
        return payload


def apply_ibkr_position_overlay(payload: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge a same-run IBKR overlay onto a cached official score payload."""
    if not payload:
        return payload
    cfg = config or load_config()
    path = resolve_path(cfg, "archive_dir") / IBKR_POSITION_OVERLAY
    try:
        overlay = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if str(overlay.get("as_of") or "")[:10] != str(payload.get("as_of") or "")[:10]:
        return payload
    base_hash = overlay.get("base_input_hash")
    payload_hash = payload.get("input_hash")
    # A scored payload carries an input_hash and the overlay must have been keyed
    # to that exact run. Reject when the payload has a hash but the overlay's is
    # missing or different -- otherwise an overlay written before any official run
    # existed (base_input_hash=None) would bleed onto a later, different official
    # run for the same as_of, which is the cross-run staleness this gate exists to
    # stop. A payload without a hash (empty/fallback dashboard) keeps the lenient
    # path so a just-refreshed position layer still shows before the first run.
    if payload_hash and str(base_hash or "") != str(payload_hash):
        return payload
    ibkr = overlay.get("ibkr")
    if not isinstance(ibkr, dict):
        return payload
    merged = dict(payload)
    merged["ibkr"] = ibkr
    merged["ibkr_refresh_status"] = {
        key: value
        for key, value in overlay.items()
        if key != "ibkr"
    }
    try:
        merged["ibkr_history"] = recent_ibkr_snapshots(
            resolve_path(cfg, "archive_dir") / "hermes_state.sqlite",
            limit=5,
        )
    except Exception:
        pass
    return _refresh_action_context_after_overlay(merged)


def _refresh_action_context_after_overlay(payload: Dict[str, Any]) -> Dict[str, Any]:
    snapshots_payload = payload.get("snapshots") or {}
    if not isinstance(snapshots_payload, dict) or not snapshots_payload:
        return payload
    try:
        snapshots = {
            symbol: SymbolSnapshot.from_dict(snapshot)
            for symbol, snapshot in snapshots_payload.items()
            if isinstance(snapshot, dict)
        }
        if not snapshots:
            return payload
        refreshed = dict(payload)
        refreshed.update(build_action_context(refreshed, snapshots))
        return refreshed
    except Exception:
        return payload


def _refresh_score_with_market_data_locked(
    requested_as_of: Any = "latest",
    *,
    _lease: Any,
) -> Dict[str, Any]:
    """Refresh OHLCV first, then score the newest locally available trading day."""
    started = time.perf_counter()
    steps = []
    config = load_config()
    assert_pipeline_lease(
        _lease,
        path=resolve_path(config, "archive_dir") / ".pipeline.lock",
    )
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
        skip_reason = "" if refresh_symbols == symbols else f"core fresh; refreshed stale flow/soft symbols: {','.join(stale_flow_symbols)}"
        steps.append(_step(
            "history_refresh",
            "OK",
            step_start,
            symbols_requested=len(refresh_symbols),
            symbols_updated=sum(1 for item in refresh.values() if item.updated),
            reason=skip_reason,
        ))
    integrity_start = time.perf_counter()
    integrity_offenders = _history_integrity_scan(config)
    steps.append(_step(
        "history_integrity",
        "OK" if not integrity_offenders else "ERROR",
        integrity_start,
        offenders=integrity_offenders[:12],
        offender_count=len(integrity_offenders),
    ))
    if integrity_offenders:
        write_refresh_run(
            state_db_path,
            requested_as_of=requested_as_of,
            effective_as_of=latest_history_date(config, _critical_symbols(config)) or _normalize_as_of(requested_as_of),
            status="ERROR",
            steps=steps,
            refresh_status={
                "status": "ERROR",
                "history_refreshed": history_refreshed,
                "skip_reason": skip_reason,
                "requested_as_of": str(requested_as_of),
                "history_dir": str(history_dir),
                "symbols_requested": len(symbols),
                "symbols_refreshed_requested": len(refresh),
                "symbols_updated": sum(1 for item in refresh.values() if item.updated),
                "history_integrity": {
                    "status": "ERROR",
                    "offenders": integrity_offenders[:12],
                    "offender_count": len(integrity_offenders),
                },
            },
            payload_hash=None,
            retention=config.get("state_retention"),
        )
        raise RuntimeError(
            "history integrity failed; refusing to score on potentially cross-wired bars: "
            + "; ".join(integrity_offenders[:6])
        )
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
    payload = _score_pipeline_locked(as_of, _lease=_lease)
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


def _atomic_write_json(path: Any, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _history_integrity_scan(config: Dict[str, Any]) -> list[str]:
    """Catch residual cross-wired OHLCV bars before scoring.

    Download-time guards compare the incoming frame with the local history, but
    this post-refresh scan protects the WebUI refresh path even if a corrupted
    file already exists on disk or a future writer bypasses backfill_history.
    """
    history_dir = resolve_path(config, "history_dir")
    offenders: list[str] = []
    for symbol in _integrity_watch_symbols(config):
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        if not path.exists():
            continue
        limit = 3.0 if symbol.startswith("^") else 1.5
        try:
            frame = pd.read_csv(path, usecols=["date", "close"]).tail(12)
        except Exception:
            continue
        close = pd.to_numeric(frame.get("close"), errors="coerce")
        dates = frame.get("date")
        if frame.empty:
            continue
        latest_close = close.iloc[-1]
        latest_date = str(dates.iloc[-1])
        if pd.isna(latest_close) or float(latest_close) <= 0:
            offenders.append(f"{path.name} latest row {latest_date} missing close")
        rows = [
            (str(day), float(value))
            for day, value in zip(dates, close)
            if pd.notna(value)
        ]
        for (d1, c1), (d2, c2) in zip(rows, rows[1:]):
            if c1 > 0 and not (1.0 / limit <= c2 / c1 <= limit):
                offenders.append(f"{path.name} {d1} {c1:.2f} -> {d2} {c2:.2f}")
    return offenders


def _integrity_watch_symbols(config: Dict[str, Any]) -> list[str]:
    symbols = set(config.get("symbols", {}).keys())
    symbols.update(config.get("market_symbols", []))
    for values in config.get("radars", {}).values():
        symbols.update(values)
    symbols.update({
        "QQQ",
        "SOXX",
        "SMH",
        "SPY",
        "^VIX",
        "^VIX3M",
        "^SOX",
        "BTC-USD",
        "BOXX",
        "DBMF",
        "GLD",
        "IAU",
        "BRK.B",
        "BIL",
        "SHV",
    })
    return sorted(str(symbol) for symbol in symbols if symbol)


def _completed_trading_days_after(as_of: Optional[str], today: Optional[date] = None) -> int:
    """Count expected completed US-market trading days strictly after ``as_of``
    and strictly before ``today``.

    Uses NYSE regular full-day holidays. This avoids false DEGRADED banners on
    US market holidays while still treating an actually missing completed
    session as stale.
    """
    today = today or date.today()
    try:
        start = date.fromisoformat(str(as_of)[:10])
    except (ValueError, TypeError):
        return 0
    count = 0
    cur = start + timedelta(days=1)
    while cur < today:
        if _is_us_market_trading_day(cur):
            count += 1
        cur += timedelta(days=1)
    return count


def _is_us_market_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in _us_market_holidays(day.year)


@lru_cache(maxsize=32)
def _us_market_holidays(year: int) -> frozenset[date]:
    holidays: set[date] = {
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        _easter_date(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),     # Memorial Day
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed_holiday(year, 12, 25),
    }
    for observed in (
        _observed_fixed_holiday(year, 1, 1),
        _observed_fixed_holiday(year + 1, 1, 1),
    ):
        if observed.year == year:
            holidays.add(observed)
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(year, 6, 19))
    return frozenset(holidays)


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    raw = date(year, month, day)
    if raw.weekday() == 5:
        return raw - timedelta(days=1)
    if raw.weekday() == 6:
        return raw + timedelta(days=1)
    return raw


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    cur = date(year, month, 1)
    offset = (weekday - cur.weekday()) % 7
    return cur + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + int(month == 12), 1 if month == 12 else month + 1, 1)
    cur = next_month - timedelta(days=1)
    return cur - timedelta(days=(cur.weekday() - weekday) % 7)


def _easter_date(year: int) -> date:
    # Anonymous Gregorian algorithm; sufficient for Good Friday market holiday.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


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
    """Re-freeze the data manifest on demand (WebUI button). Returns status + frozen_at.

    Runs the history-integrity scan FIRST and refuses to re-freeze when bars are
    corrupt — otherwise the button re-certifies corrupted / hand-edited CSVs as OK,
    hiding a DRIFT that is real damage. Verify-then-freeze: the same discipline the
    daily run applies before _refreeze_manifest, now enforced at the button too."""
    cfg = config or load_config()
    offenders = _history_integrity_scan(cfg)
    if offenders:
        info = dict(manifest_status(cfg))   # keep current (DRIFT/…) status — do NOT freeze
        info.update({
            "status": info.get("status") or "DRIFT",
            "refrozen": False,
            "ok": False,
            "integrity_offenders": offenders[:12],
            "offender_count": len(offenders),
            "error": "history integrity scan failed — refusing to re-freeze corrupt bars",
        })
        return info
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
    symbols.update(online_soft_history_symbols(config))
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
