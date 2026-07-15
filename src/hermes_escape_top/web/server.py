"""Hermes Escape-Top WebUI server.

Endpoints:
  GET  /                   Dashboard
  GET  /api/score          Latest cached score JSON (read-only)
  POST /api/refresh_score  Recompute score JSON and update archive
  Legacy M4/demo write endpoints return HTTP 410 and cannot mutate live state.
  GET  /health             Healthcheck
"""
from __future__ import annotations

import json
import hmac
import os
import subprocess
import sys
import traceback
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def _runtime_root() -> Path:
    override = os.environ.get("HERMES_RUNTIME_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    local_root = PACKAGE_DIR.parent
    if (local_root / "scripts").exists() or (local_root / "data").exists():
        return local_root
    repo_root = PACKAGE_DIR.parents[1]
    if (repo_root / "src" / "hermes_escape_top").exists():
        return repo_root
    return local_root


BASE_DIR = _runtime_root()
VENV_PYTHON = BASE_DIR.parent.parent.parent.parent / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
SHADOW_LOG = BASE_DIR / "reports" / "shadow" / "M4_shadow_log.jsonl"
RUN_DAILY = BASE_DIR / "scripts" / "run_daily.py"
RUN_DAILY_PKG = (
    BASE_DIR / "scripts" / "run_daily_package.py"
    if (BASE_DIR / "scripts" / "run_daily_package.py").exists()
    else PACKAGE_DIR / "scripts" / "run_daily_package.py"
)

from ..config import load_config, resolve_path
from ..core.data.alpaca_flow import load_daily_flow_snapshot
from ..core.data.run_transaction import pending_score_run_transaction
from ..core.data.state_store import record_execution_confirmation
from ..ibkr.live_check import run_live_check
from ..core.safe_io import PipelineBusy, pipeline_lock
from ..scripts.refresh_external import refresh_all_sources as refresh_all_external_sources
from ..scripts.refresh_external import IMPORT_FILE_SOURCE_IDS
from ..scripts.refresh_external import pending_import_file
from ..scripts.refresh_external import profile_for
from ..scripts.refresh_external import refresh_source as refresh_external_source
from ..scripts.refresh_external import status as external_source_status
from .health import compute_health
from .market_evidence import attach_market_admission_status
from .refresh import (
    apply_ibkr_position_overlay,
    force_refresh_manifest,
    manifest_status,
    refresh_positions_only,
    refresh_score_with_market_data,
)
from .render import render_dashboard


# ── helpers ───────────────────────────────────────────────────────────────────

# Dangerous writes that change production behavior or decision state: require a
# loopback Host/Origin AND HERMES_CONFIRM_TOKEN.
TOKEN_WRITE_ENDPOINTS = {
    "/api/confirm_execution",  # writes execution confirmations that feed reentry
}
# Low-risk data refresh / recompute (no order or money path — the system never
# orders) are loopback-only, matching the 8765 workbench /refresh. A token here is
# friction without security value: loopback already blocks remote/CSRF callers,
# and the worst a local caller can do is refresh data.
LOOPBACK_WRITE_ENDPOINTS = {
    "/api/refresh_manifest",
    "/api/refresh_soft_data",
    "/api/refresh_score",
    "/api/refresh_positions",
    "/api/refresh_external_source",
    "/api/refresh_external_sources",
    "/api/rerun_external_precheck",
    "/api/ibkr_live_check",
}
RETIRED_WRITE_ENDPOINTS = {
    "/api/m4_shadow",
    "/api/m4_backfill",
    "/api/m4_golive",
    "/api/ibkr_demo_snapshot",
}

# Returned with HTTP 409 when a write endpoint cannot take the pipeline lock.
_BUSY_PAYLOAD = {
    "ok": False,
    "busy": True,
    "message": "另一个刷新或当日官方 run 正在写数据，本次已跳过以避免并发写坏。请几秒后重试。",
}

_LEGACY_SOFT_SOURCE_GROUPS = {
    "fred": ("fred_net_liquidity",),
    "fred_risk": ("dollar", "real_rate"),
    "naaim": ("naaim_exposure",),
    "aaii": ("aaii_sentiment",),
    "cot": ("cot_nq",),
}


def _refresh_soft_data_via_external_runner(only: object = None) -> dict:
    """Keep the legacy endpoint without exposing its direct CSV writers."""
    selected = str(only or "").strip()
    if not selected:
        return refresh_all_external_sources()
    source_ids = _LEGACY_SOFT_SOURCE_GROUPS.get(selected, (selected,))
    runs = [
        refresh_external_source(source_id, auto_import=True)
        for source_id in source_ids
    ]
    ok_count = sum(1 for run in runs if str(run.get("status") or "") == "OK")
    return {
        "ok": ok_count == len(runs),
        "ok_count": ok_count,
        "error_count": len(runs) - ok_count,
        "runs": runs,
        "mode": "legacy_endpoint_via_external_runner",
    }


def _latest_precheck(as_of: str) -> dict | None:
    """Load latest daily_score_precheck without running score_pipeline."""
    try:
        p = BASE_DIR / "data" / f"daily_score_precheck_{as_of}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        files = sorted((BASE_DIR / "data").glob("daily_score_precheck_*.json"), reverse=True)
        if files:
            return json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _tail_lines_newest_first(path, max_bytes: int = 48 * 1024 * 1024) -> list:
    """Lines from the tail of a (possibly huge, append-only) file, newest-first.
    Reads at most max_bytes so the 150MB+ audit log is never read whole on a
    dashboard request — the read stays bounded as the log grows to GB. The window
    covers many recent official days; an as_of older than it falls back to NO_CACHE
    (rare manual query) rather than re-scanning the entire file."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - max_bytes))
        data = fh.read()
    lines = data.split(b"\n")
    if size > max_bytes:
        lines = lines[1:]  # drop the likely-partial first line
    lines.reverse()
    return lines


def _read_audit_payloads(max_bytes: int = 64 * 1024 * 1024) -> list:
    """Read the audit tail ONCE and return the scored payloads it holds, newest-
    first. The dashboard derives BOTH the latest-payload lookup and the decision-
    history strip from this single read — one file read per page load, not two.
    64MB spans ~10 official trading days in steady state (1 record/day); more under
    re-run bloat is fine — the history strip caps at max_days."""
    try:
        path = resolve_path(load_config(), "archive_dir") / "audit_log.jsonl"
        if not path.exists():
            return []
        pending = pending_score_run_transaction(path.parent)
        pending_run_id = str((pending or {}).get("run_id") or "")
        out: list = []
        for raw in _tail_lines_newest_first(path, max_bytes):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue
            pl = record.get("payload") if isinstance(record, dict) else None
            pl = pl if isinstance(pl, dict) else record
            persistence_run_id = str(((pl or {}).get("persistence") or {}).get("run_id") or "")
            if pending_run_id and persistence_run_id == pending_run_id:
                continue
            if isinstance(pl, dict) and "scores" in pl:
                out.append(pl)
        return out
    except Exception:
        return []


def _read_run_receipt() -> dict:
    """The scheduled daily run's end-of-run self-attestation (run_receipt.json):
    when the official run last completed + its self-check. Lets the dashboard show
    a positive 'ran today, green' instead of only inferring freshness from data."""
    try:
        path = resolve_path(load_config(), "archive_dir") / "run_receipt.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _attach_alpaca_daily_flow(payload: dict) -> dict:
    """Attach the nearest non-future SIP flow cache without touching audit data."""
    try:
        config = load_config()
        archive_dir = resolve_path(config, "archive_dir")
        status_path = archive_dir / "alpaca_daily_flow_status.json"
        if status_path.exists():
            payload["alpaca_daily_flow_status"] = json.loads(status_path.read_text(encoding="utf-8"))
        flow = load_daily_flow_snapshot(archive_dir, payload.get("as_of", ""))
        if flow is not None:
            payload["alpaca_daily_flow"] = flow
            payload.setdefault("alpaca_daily_flow_status", {"status": "OK", "as_of": flow.get("as_of")})
        else:
            payload.setdefault("alpaca_daily_flow_status", {"status": "MISSING"})
    except Exception as exc:
        payload["alpaca_daily_flow_status"] = {"status": "ERROR", "error": str(exc)}
    return payload


def _attach_external_source_status(payload: dict) -> dict:
    """Attach source-run ledger status for UI trust display; no network calls."""
    try:
        payload["external_source_status"] = external_source_status(load_config())
    except Exception as exc:
        payload["external_source_status_error"] = str(exc)
    return payload


def _attach_market_admission_status(payload: dict) -> dict:
    return attach_market_admission_status(
        payload, config_loader=load_config, path_resolver=resolve_path
    )


def _attach_external_import_candidates(payload: dict) -> dict:
    """Attach newest official import files for AAII/NAAIM, without importing."""
    candidates = []
    try:
        archive_dir = resolve_path(load_config(), "archive_dir")
    except Exception:
        return payload
    for source_id in IMPORT_FILE_SOURCE_IDS:
        profile = profile_for(source_id)
        if profile is None:
            continue
        try:
            path = pending_import_file(source_id, archive_dir)
        except Exception:
            path = None
        if path is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        candidates.append({
            "source_id": source_id,
            "label": getattr(profile, "label", source_id),
            "path": str(path),
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "size_bytes": stat.st_size,
        })
        external = payload.get("external_source_status")
        if isinstance(external, dict) and isinstance(external.get(source_id), dict):
            external[source_id]["official_artifact_ready"] = True
            external[source_id]["migration_status"] = "OFFICIAL_FILE_READY"
            external[source_id]["next_action"] = f"validate and import the staged official file for {source_id}"
    if candidates:
        payload["external_import_candidates"] = candidates
    return payload


def _external_precheck_status_paths() -> list[Path]:
    override = os.environ.get("HERMES_EXTERNAL_PRECHECK_STATUS")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(Path.home() / ".hermes" / "logs" / "external" / "external_precheck_latest.json")
    return candidates


def _attach_external_precheck_status(payload: dict) -> dict:
    """Attach the latest launchd external-source precheck JSON. Read-only."""
    for path in _external_precheck_status_paths():
        if not path.exists():
            continue
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(status, dict):
            continue
        status = dict(status)
        status["source_path"] = str(path)
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            mtime_date = mtime.date().isoformat()
            status["mtime"] = mtime.isoformat(timespec="seconds")
            status["mtime_date"] = mtime_date
            status["stale"] = mtime_date != date.today().isoformat()
        except Exception:
            status["stale"] = True
        markdown_path = path.with_suffix(".md")
        if markdown_path.exists():
            try:
                # Generated reports are small; cap anyway so a malformed file cannot
                # bloat the dashboard payload.
                status["markdown_text"] = markdown_path.read_text(encoding="utf-8")[:12000]
                status["markdown_path"] = str(markdown_path)
            except Exception:
                pass
        payload["external_precheck_status"] = status
        return payload
    return payload


def _external_precheck_script_path() -> Path:
    override = os.environ.get("HERMES_EXTERNAL_PRECHECK_SCRIPT")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend([
        Path.home() / ".hermes" / "bin" / "refresh_external_precheck.sh",
        BASE_DIR / "ops" / "refresh_external_precheck.sh",
    ])
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def _tail_text(text: str, limit: int = 2000) -> str:
    return (text or "")[-limit:]


def rerun_external_precheck() -> dict:
    """Run the launchd-equivalent external-source precheck entrypoint."""
    script = _external_precheck_script_path()
    if not script.exists():
        return {
            "ok": False,
            "status": "SCRIPT_MISSING",
            "script": str(script),
            "error": "refresh_external_precheck.sh not found",
        }
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "HERMES_EXTERNAL_PRECHECK_LOCK_TIMEOUT": "0"},
    )
    payload: dict = {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "script": str(script),
        "stdout_tail": _tail_text(result.stdout),
        "stderr_tail": _tail_text(result.stderr),
    }
    if result.returncode == 75:
        payload.update({"busy": True, "message": _BUSY_PAYLOAD["message"]})
    _attach_external_precheck_status(payload)
    return payload


def _system_health_report_roots() -> list[Path]:
    """Candidate report directories for repo, live, and HERMES_DATA_DIR runs."""
    candidates: list[Path] = []
    override = os.environ.get("HERMES_DATA_DIR")
    if override:
        candidates.append(Path(override).expanduser() / "reports")
    candidates.extend([
        PACKAGE_DIR / "reports",
        BASE_DIR / "reports",
        BASE_DIR / "hermes_escape_top" / "reports",
    ])
    if BASE_DIR.parent.name == "releases":
        candidates.extend(BASE_DIR.parent.glob("*/hermes_escape_top/reports"))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path.expanduser())
    return unique


def _read_system_health_report(path: Path) -> dict | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(report, dict):
        return None
    report = dict(report)
    report["source_path"] = str(path)
    return report


def _report_matches_input_hash(report: dict, payload_hash: str) -> bool:
    return str(report.get("input_hash") or "") == payload_hash


def _attach_system_health_report(payload: dict) -> dict:
    """Attach the daily 20-dimension health report for dashboard evidence.

    This is read-only and intentionally does not recompute health. Exact as_of
    evidence wins; otherwise the newest report is attached and marked stale.
    """
    requested = str(payload.get("as_of") or "")[:10]
    if not requested:
        return payload

    exact_paths = []
    all_paths = []
    for root in _system_health_report_roots():
        exact = root / f"system_health_{requested}.json"
        if exact.exists():
            exact_paths.append(exact)
        if root.exists():
            all_paths.extend(root.glob("system_health_*.json"))

    payload_hash = str(payload.get("input_hash") or "")
    report = None
    if exact_paths:
        if payload_hash:
            matching = [
                (path, candidate)
                for path in exact_paths
                if (candidate := _read_system_health_report(path)) is not None
                and _report_matches_input_hash(candidate, payload_hash)
            ]
            if not matching:
                return payload
            _path, report = max(matching, key=lambda item: item[0].stat().st_mtime)
        else:
            chosen = max(exact_paths, key=lambda p: p.stat().st_mtime)
            report = _read_system_health_report(chosen)
    elif all_paths and not payload_hash:
        chosen = max(all_paths, key=lambda p: (p.name, p.stat().st_mtime))
        report = _read_system_health_report(chosen)
    if report is None:
        return payload
    report_as_of = str(report.get("as_of") or "")[:10]
    report["requested_as_of"] = requested
    report["stale"] = report_as_of != requested
    payload["system_health_report"] = report
    return payload


def _system_health_history_row(report: dict, path: Path) -> dict:
    dimensions = report.get("audit_dimensions") if isinstance(report.get("audit_dimensions"), list) else []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for row in dimensions:
        if isinstance(row, dict):
            status = str(row.get("status") or "UNKNOWN").upper()
            if status in counts:
                counts[status] += 1
    health = report.get("health") if isinstance(report.get("health"), dict) else {}
    layers = health.get("layers") if isinstance(health.get("layers"), dict) else {}
    return {
        "as_of": str(report.get("as_of") or "")[:10],
        "generated_at": str(report.get("generated_at") or ""),
        "health_level": str(health.get("level") or "NA"),
        "counts": counts,
        "layers": {
            "strategy_data": str((layers.get("strategy_data") or {}).get("level") or "NA"),
            "position_reconciliation": str((layers.get("position_reconciliation") or {}).get("level") or "NA"),
            "auxiliary_flows": str((layers.get("auxiliary_flows") or {}).get("level") or "NA"),
        },
        "source_path": str(path),
    }


def _attach_system_health_history(payload: dict, limit: int = 7) -> dict:
    """Attach recent daily health reports, deduped by as_of with newest evidence."""
    by_as_of: dict[str, tuple[str, float, dict]] = {}
    for root in _system_health_report_roots():
        if not root.exists():
            continue
        for path in root.glob("system_health_*.json"):
            report = _read_system_health_report(path)
            if report is None:
                continue
            as_of = str(report.get("as_of") or "")[:10]
            if not as_of:
                continue
            generated = str(report.get("generated_at") or "")
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            row = _system_health_history_row(report, path)
            key = (generated, mtime)
            if as_of not in by_as_of or key > (by_as_of[as_of][0], by_as_of[as_of][1]):
                by_as_of[as_of] = (generated, mtime, row)
    history = [value[2] for as_of, value in sorted(by_as_of.items(), key=lambda item: item[0], reverse=True)]
    if history:
        payload["system_health_history"] = history[:limit]
    return payload


def _latest_score_payload(as_of: str, records: list | None = None, prefer_preview: bool = False) -> dict | None:
    """Newest package score payload (or the one matching as_of). Operates on a
    pre-read record list when given (so the dashboard reads the audit once);
    otherwise reads it itself (back-compatible for the other endpoints)."""
    try:
        raw_target = str(as_of or "latest")
        latest_mode = raw_target.lower() in {"latest", "newest", ""}
        target = raw_target[:10]
        if records is None:
            records = _read_audit_payloads()
        fallback = None
        fallback_day = ""
        exact_sched = None       # official record exactly matching an explicit target
        exact_any = None         # newest record exactly matching the target (any run_type)
        exact_preview = None     # newest NON-official record for the target (?view=preview)
        latest = None            # newest OFFICIAL (scheduled) run — the default headline
        latest_day = ""
        latest_any = None        # newest of any run_type — fallback only if no scheduled
        latest_any_day = ""
        for payload in records:
            pday = str(payload.get("as_of", ""))[:10]
            if latest_mode:
                if not pday:
                    continue
                if pday > latest_any_day:
                    latest_any_day = pday
                    latest_any = payload
                # An intraday manual_rerun preview must never silently become the
                # default headline (the SOXL REDUCE->EXIT->REDUCE scare was a
                # preview flip): `latest` only ever tracks the newest scheduled run.
                if str(payload.get("run_type", "scheduled")) == "scheduled" and pday > latest_day:
                    latest_day = pday
                    latest = dict(payload)
                    latest["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": True, "requested_as_of": raw_target}
                continue
            if pday == target:
                # Explicit date: prefer the OFFICIAL (scheduled) record for that day,
                # so navigating to / being redirected to a date that already has an
                # official run shows the official — not a redundant manual_rerun
                # preview (records are newest-first → first match of each kind is the
                # newest). A genuine pre-official preview (no scheduled yet for the
                # day) still surfaces below, flagged non_official.
                rt = str(payload.get("run_type", "scheduled"))
                if exact_any is None:
                    exact_any = dict(payload)
                    exact_any["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": True, "non_official": rt != "scheduled"}
                if rt == "scheduled" and exact_sched is None:
                    exact_sched = dict(payload)
                    exact_sched["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": True}
                if rt != "scheduled" and exact_preview is None:
                    exact_preview = dict(payload)
                    exact_preview["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": True, "non_official": True}
                continue
            if pday and pday <= target and pday > fallback_day:
                fallback_day = pday
                fallback = dict(payload)
                fallback["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": False, "requested_as_of": target}
        if latest_mode:
            if latest is not None:
                return latest
            # No official run in the window: surface the newest preview but flag it
            # so render labels it non-official — never pass a preview off as official.
            if latest_any is not None:
                latest_any = dict(latest_any)
                latest_any["cache_status"] = {"hit": True, "source": "audit_log.jsonl", "exact": True, "requested_as_of": raw_target, "non_official": True}
                return latest_any
            return None
        # ?view=preview explicitly asks for the intraday preview (the 更新策略数据
        # button redirects here after a manual_rerun), so show the newest non-official
        # record for that day; otherwise the official scheduled run always wins.
        if prefer_preview and exact_preview is not None:
            return exact_preview
        if exact_sched is not None:
            return exact_sched
        if exact_any is not None:
            return exact_any   # only a preview exists for that exact day (genuine pre-official)
        return fallback
    except Exception:
        return None


def _recent_status_history(as_of: str, max_days: int = 30, records: list | None = None) -> dict:
    """Per-symbol status over the last `max_days` distinct OFFICIAL trading days
    for the dashboard consistency strip. Shows however many official days exist
    (only ~10 until the system accumulates more, one per trading day; rotation
    retains up to 90). Uses the pre-read record list when given
    (shared with the latest-payload read — one audit read per page load); manual
    re-runs (run_type != scheduled) are skipped so the strip shows the decision of
    record, not intraday previews."""
    try:
        if records is None:
            records = _read_audit_payloads()
        by_day: dict = {}
        for pl in records:  # newest-first
            if str(pl.get("run_type", "scheduled")) != "scheduled":
                continue
            day = str(pl.get("as_of", ""))[:10]
            if day:
                by_day.setdefault(day, pl)  # first seen is newest -> keep newest per day
        out: dict = {}
        for day in sorted(by_day)[-max_days:]:
            scores = by_day[day].get("scores") or {}
            for sym in ("MSTR", "FNGU", "SOXL"):
                sc = scores.get(sym) or {}
                if not sc:
                    continue
                out.setdefault(sym, []).append({
                    "as_of": day,
                    "status": sc.get("status", "?"),
                    "valve": bool(sc.get("hard_valve_hits")),
                })
        return out
    except Exception:
        return {}


def _prev_official_valves(records: list, before_as_of: str) -> dict:
    """Hard-valve ids per symbol from the most recent OFFICIAL run BEFORE
    `before_as_of`. The dashboard marks a valve that fired today but not in that
    run as 'newly fired, pending tomorrow's confirmation' — so a fresh EXIT reads
    as unconfirmed, not as a settled state (前后一致性)."""
    day0 = str(before_as_of or "")[:10]
    for pl in records:  # newest-first
        if str(pl.get("run_type", "scheduled")) != "scheduled":
            continue
        day = str(pl.get("as_of", ""))[:10]
        if day and day < day0:
            scores = pl.get("scores") or {}
            return {s: list((scores.get(s) or {}).get("hard_valve_hits") or [])
                    for s in ("MSTR", "FNGU", "SOXL")}
    return {}


def _subprocess_env() -> dict:
    env = os.environ.copy()
    package_parent = str(PACKAGE_DIR.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = package_parent + (os.pathsep + existing if existing else "")
    return env


def _empty_dashboard_payload(as_of: str) -> dict:
    return {
        "schema_version": "escape-top-greenfield-dashboard-cache-miss-v1",
        "as_of": str(as_of)[:10],
        "scores": {},
        "sizing": {},
        "routing": {},
        "reentry": {},
        "mirror": {"decisions": {}},
        "posterior_pnl": {"portfolio_value": 0.0, "escape": {}, "mirror": {}},
        "portfolio_risk": {},
        "regime": {"current": "NO_CACHE"},
        "data_quality": {"level": "NO_CACHE", "overall_score": 0.0},
        "cache_status": {"hit": False, "message": "No cached score payload. Use POST /api/refresh_score."},
        "ibkr": {"source": "disabled", "note": "No cached score payload."},
    }


def _local_hostname(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value).strip()
    if "://" in raw:
        return (urlparse(raw).hostname or "").lower()
    if raw.startswith("[") and "]" in raw:
        return raw[1 : raw.index("]")].lower()
    return raw.rsplit(":", 1)[0].lower()


def _is_local_request_host(value: str | None) -> bool:
    return _local_hostname(value) in {"localhost", "127.0.0.1", "::1"}


def _write_request_allowed(config: dict, req: dict, headers) -> tuple[bool, str]:
    if not _is_local_request_host(headers.get("Host")):
        return False, "HOST_NOT_LOCAL"
    origin = headers.get("Origin")
    if origin and not _is_local_request_host(origin):
        return False, "ORIGIN_NOT_LOCAL"
    web_cfg = config.get("web", {}) if isinstance(config.get("web"), dict) else {}
    env_name = str(web_cfg.get("confirm_execution_token_env") or "HERMES_CONFIRM_TOKEN")
    expected = os.environ.get(env_name) or web_cfg.get("confirm_execution_token")
    if not expected:
        return False, "TOKEN_NOT_CONFIGURED"
    supplied = headers.get("X-Hermes-Token") or req.get("token")
    if supplied and hmac.compare_digest(str(supplied), str(expected)):
        return True, "TOKEN_OK"
    return False, "UNAUTHORIZED"


def _confirm_execution_allowed(config: dict, req: dict, headers) -> tuple[bool, str]:
    return _write_request_allowed(config, req, headers)


def _loopback_only_allowed(headers) -> tuple[bool, str]:
    """Loopback guard for low-risk data-refresh endpoints: require a local
    Host/Origin but no token. Blocks remote and cross-site callers without the
    token friction — the same posture as the 8765 workbench /refresh. Dangerous
    endpoints keep the token gate via _write_request_allowed."""
    if not _is_local_request_host(headers.get("Host")):
        return False, "HOST_NOT_LOCAL"
    origin = headers.get("Origin")
    if origin and not _is_local_request_host(origin):
        return False, "ORIGIN_NOT_LOCAL"
    return True, "LOOPBACK_OK"


def _auth_failure_payload(status: str, token_required: bool = True) -> bytes:
    message = (
        "write endpoint requires localhost Host/Origin and HERMES_CONFIRM_TOKEN"
        if token_required
        else "endpoint requires a localhost Host/Origin (loopback only)"
    )
    return json.dumps(
        {"ok": False, "status": status, "message": message},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode()


def _read_run_daily_mode() -> str:
    try:
        src = RUN_DAILY.read_text(encoding="utf-8")
        if "escape_top_system" in src and "run_daily_package" not in src:
            return "monolith"
        if "run_daily_package" in src or "hermes_escape_top.cli" in src:
            return "package"
    except Exception:
        pass
    return "unknown"


def _shadow_status() -> dict:
    entries = []
    if SHADOW_LOG.exists():
        for line in SHADOW_LOG.read_text(encoding="utf-8").splitlines()[-10:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
    shadow_latest = None
    shadow_files = sorted(
        (BASE_DIR / "data" / "shadow").glob("daily_score_precheck_*.json"), reverse=True
    )
    if shadow_files:
        try:
            shadow_latest = json.loads(shadow_files[0].read_text(encoding="utf-8"))
        except Exception:
            pass
    available_dates = []
    for p in sorted((BASE_DIR / "data").glob("daily_score_precheck_*.json"), reverse=True):
        available_dates.append(p.stem.replace("daily_score_precheck_", ""))
    return {
        "log_entries": entries,
        "shadow_precheck": shadow_latest,
        "run_daily_mode": _read_run_daily_mode(),
        "available_dates": available_dates,
        "latest_baseline_date": available_dates[0] if available_dates else None,
    }


def _run_shadow(as_of: str) -> dict:
    cmd = [
        PYTHON,
        str(RUN_DAILY_PKG),
        "--as-of",
        as_of,
        "--skip-refresh",
        "--lock-timeout",
        "0",
    ]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), env=_subprocess_env(), capture_output=True, text=True, timeout=180)
        output = r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else "")
        ok = r.returncode == 0
        diff_result = _diff_shadow(as_of)
        busy = "pipeline busy" in output.lower()
        return {"ok": ok, "busy": busy, "output": output[-2000:], "diff": diff_result}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "Timeout (180s)", "diff": None}
    except Exception:
        return {"ok": False, "output": traceback.format_exc()[-1000:], "diff": None}


def _run_history_refresh(as_of: str) -> dict:
    cmd = [PYTHON, "-m", "hermes_escape_top.cli", "backfill-history", "--end", as_of, "--repair-overlap-days", "3"]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), env=_subprocess_env(), capture_output=True, text=True, timeout=180)
        return {"ok": r.returncode == 0, "output": (r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else ""))[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "history refresh timeout (180s)"}
    except Exception:
        return {"ok": False, "output": traceback.format_exc()[-1000:]}


def _run_baseline(as_of: str) -> dict:
    backup = RUN_DAILY.with_suffix(".py.monolith_backup")
    script = backup if backup.exists() else RUN_DAILY
    if not script.exists():
        return {"ok": False, "output": f"No monolith baseline script found at {script}"}
    cmd = [PYTHON, str(script), "--as-of", as_of, "--skip-refresh"]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), env=_subprocess_env(), capture_output=True, text=True, timeout=180)
        output = r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else "")
        return {"ok": r.returncode == 0, "output": output[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "baseline timeout (180s)"}
    except Exception:
        return {"ok": False, "output": traceback.format_exc()[-1000:]}


def _backfill_compare(as_of: str) -> dict:
    # The legacy history/baseline legs do not acquire the package transaction
    # themselves. Hold the shared mutex around both, then release it before the
    # package shadow child takes the same lock normally.
    with pipeline_lock(blocking=False):
        refresh = _run_history_refresh(as_of)
        baseline = _run_baseline(as_of) if refresh.get("ok") else {
            "ok": False,
            "output": "Skipped baseline because refresh failed.",
        }
    shadow = _run_shadow(as_of) if baseline.get("ok") else {"ok": False, "output": "Skipped shadow because baseline failed.", "diff": None}
    output = (
        "=== history refresh ===\n" + str(refresh.get("output", "")) +
        "\n\n=== baseline ===\n" + str(baseline.get("output", "")) +
        "\n\n=== package shadow ===\n" + str(shadow.get("output", ""))
    )
    return {
        "ok": bool(refresh.get("ok") and baseline.get("ok") and shadow.get("ok")),
        "output": output[-5000:],
        "diff": shadow.get("diff"),
        "steps": {"refresh": refresh.get("ok"), "baseline": baseline.get("ok"), "shadow": shadow.get("ok")},
    }


def _diff_shadow(as_of: str) -> dict | None:
    mono_path = BASE_DIR / "data" / f"daily_score_precheck_{as_of}.json"
    pkg_path = BASE_DIR / "data" / "shadow" / f"daily_score_precheck_{as_of}.json"
    if not mono_path.exists() or not pkg_path.exists():
        return None
    try:
        mono = json.loads(mono_path.read_text())
        pkg = json.loads(pkg_path.read_text())
        diffs, matches, total = [], 0, 0
        for sym in ["MSTR", "FNGU", "SOXL"]:
            mr = mono.get("results", {}).get(sym, {})
            pr = pkg.get("results", {}).get(sym, {})
            mht = mr.get("hard_trigger", {}) or {}
            pht = pr.get("hard_trigger", {}) or {}
            mv = {"status": mr.get("status"), "sell_pct": mr.get("sell_pct"),
                  "hard_ids": sorted(mht.get("ids", []))}
            pv = {"status": pr.get("status"), "sell_pct": pr.get("sell_pct"),
                  "hard_ids": sorted(pht.get("ids", []))}
            for f in ["hard_ids", "status", "sell_pct"]:
                total += 1
                if mv[f] == pv[f]:
                    matches += 1
                else:
                    diffs.append(f"{sym}.{f}: 单体={mv[f]} → 包={pv[f]}")
        return {"match_rate": round(matches / total * 100, 1) if total else 0,
                "matches": matches, "total": total, "divergences": diffs}
    except Exception:
        return None


def _flip_to_package() -> dict:
    try:
        backup = RUN_DAILY.with_suffix(".py.monolith_backup")
        RUN_DAILY.parent.mkdir(parents=True, exist_ok=True)
        if RUN_DAILY.exists() and not backup.exists():
            backup.write_text(RUN_DAILY.read_text(encoding="utf-8"), encoding="utf-8")
        elif not RUN_DAILY.exists() and not backup.exists():
            backup.write_text(
                '#!/usr/bin/env python3\n"""No monolith file existed in this checkout before package shim creation."""\n',
                encoding="utf-8",
            )
        new_content = (
            '#!/usr/bin/env python3\n'
            '"""run_daily.py — M4 live: runs the package engine via -m (single source of truth).\n'
            'There is no loose run_daily_package.py copy; the package self-locates via\n'
            '_discover_runtime_paths walk-up. Monolith backup: run_daily.py.monolith_backup\n"""\n'
            'import os, subprocess, sys\n'
            'from pathlib import Path\n'
            'ESCAPE_TOP = Path(__file__).resolve().parent.parent\n'
            'PYTHON = sys.executable\n'
            'if __name__ == "__main__":\n'
            '    env = dict(os.environ)\n'
            '    env["PYTHONPATH"] = str(ESCAPE_TOP) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")\n'
            '    cmd = [PYTHON, "-m", "hermes_escape_top.scripts.run_daily_package",\n'
            '           "--live", "--commit-state"] + sys.argv[1:]\n'
            '    r = subprocess.run(cmd, cwd=str(ESCAPE_TOP), env=env)\n'
            '    sys.exit(r.returncode)\n'
        )
        RUN_DAILY.write_text(new_content, encoding="utf-8")
        return {"ok": True,
                "message": f"✅ run_daily.py → 包引擎。备份: {backup.name}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ── HTTP handler ──────────────────────────────────────────────────────────────

def make_handler(default_as_of: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "HermesGreenfieldHTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            as_of = params.get("as_of", ["latest"])[0]
            view = params.get("view", [""])[0]

            if parsed.path in {"/", "/index.html"}:
                audit_records = _read_audit_payloads()  # single audit read for all three lookups
                payload = _latest_score_payload(as_of, audit_records, prefer_preview=(view == "preview")) or _empty_dashboard_payload(as_of)
                payload = apply_ibkr_position_overlay(payload)
                _attach_alpaca_daily_flow(payload)
                _attach_external_source_status(payload)
                payload["run_receipt"] = _read_run_receipt()
                _attach_market_admission_status(payload)
                _attach_external_import_candidates(payload)
                _attach_external_precheck_status(payload)
                _attach_system_health_report(payload)
                _attach_system_health_history(payload)
                payload["status_history"] = _recent_status_history(payload.get("as_of") or as_of, records=audit_records)
                payload["prev_valves"] = _prev_official_valves(audit_records, payload.get("as_of") or as_of)
                shadow = _shadow_status()
                try:
                    manifest = manifest_status()
                except Exception:
                    manifest = {}
                try:
                    health = compute_health(payload, manifest)
                except Exception:
                    health = {}
                self._send(200, "text/html; charset=utf-8",
                           render_dashboard(payload, shadow_status=shadow,
                                            manifest_status=manifest, health=health).encode())
                return

            if parsed.path == "/api/score":
                payload = _latest_score_payload(as_of)
                if payload is None:
                    payload = {"ok": False, "as_of": as_of, "message": "No cached score payload. POST /api/refresh_score to refresh."}
                else:
                    payload = apply_ibkr_position_overlay(payload)
                    _attach_alpaca_daily_flow(payload)
                    _attach_external_source_status(payload)
                    _attach_market_admission_status(payload)
                    _attach_external_import_candidates(payload)
                    _attach_external_precheck_status(payload)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/shadow_status":
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(_shadow_status(), ensure_ascii=False,
                                      indent=2, default=str).encode())
                return

            if parsed.path == "/api/manifest_status":
                try:
                    payload = manifest_status()
                except Exception:
                    payload = {"status": "ERROR", "error": traceback.format_exc()[-1000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/external_source_status":
                try:
                    payload = {"ok": True, "sources": external_source_status(load_config())}
                except Exception:
                    payload = {"ok": False, "error": traceback.format_exc()[-1000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/health_status":
                try:
                    score = _latest_score_payload(as_of) or _empty_dashboard_payload(as_of)
                    score = apply_ibkr_position_overlay(score)
                    _attach_alpaca_daily_flow(score)
                    _attach_external_source_status(score)
                    score["run_receipt"] = _read_run_receipt()
                    _attach_market_admission_status(score)
                    _attach_external_precheck_status(score)
                    try:
                        manifest = manifest_status()
                    except Exception:
                        manifest = {}
                    out = compute_health(score, manifest)
                except Exception:
                    out = {"level": "ERROR", "error": traceback.format_exc()[-1000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(out, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/health":
                self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
                return

            self._send(404, "text/plain; charset=utf-8", b"not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            try:
                req = json.loads(body) if body else {}
            except Exception:
                req = {}

            if parsed.path in RETIRED_WRITE_ENDPOINTS:
                payload = {
                    "ok": False,
                    "retired": True,
                    "status": "GONE",
                    "message": "legacy M4/demo write endpoint is permanently disabled",
                }
                self._send(
                    410,
                    "application/json; charset=utf-8",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(),
                )
                return

            if parsed.path in TOKEN_WRITE_ENDPOINTS:
                try:
                    allowed, auth_status = _write_request_allowed(load_config(), req, self.headers)
                except Exception:
                    allowed, auth_status = False, "AUTH_CHECK_ERROR"
                if not allowed:
                    self._send(403, "application/json; charset=utf-8",
                               _auth_failure_payload(auth_status, token_required=True))
                    return
            elif parsed.path in LOOPBACK_WRITE_ENDPOINTS:
                allowed, auth_status = _loopback_only_allowed(self.headers)
                if not allowed:
                    self._send(403, "application/json; charset=utf-8",
                               _auth_failure_payload(auth_status, token_required=False))
                    return

            if parsed.path == "/api/refresh_manifest":
                response_status = 200
                try:
                    with pipeline_lock(blocking=False):
                        payload = force_refresh_manifest()
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD)
                    response_status = 409
                except Exception:
                    payload = {"ok": False, "status": "ERROR", "error": traceback.format_exc()[-2000:]}
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/refresh_soft_data":
                response_status = 200
                try:
                    with pipeline_lock(blocking=False):
                        payload = _refresh_soft_data_via_external_runner(req.get("only"))
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD)
                    response_status = 409
                except Exception:
                    payload = {"ok": False, "error": traceback.format_exc()[-2000:]}
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path in {"/api/refresh_score", "/api/score"}:
                as_of = req.get("as_of", "latest")
                response_status = 200
                try:
                    payload = refresh_score_with_market_data(as_of, blocking=False)
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD, as_of=as_of)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/refresh_positions":
                as_of = req.get("as_of", "latest")
                response_status = 200
                try:
                    base_payload = _latest_score_payload(as_of) or {"as_of": as_of}
                    payload = refresh_positions_only(as_of, blocking=False, base_payload=base_payload)
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD, as_of=as_of)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/refresh_external_source":
                source_id = str(req.get("source_id") or req.get("source") or "").strip()
                import_file = str(req.get("import_file") or "").strip()
                response_status = 200
                if not source_id:
                    payload = {"ok": False, "error": "source_id is required"}
                    response_status = 400
                else:
                    try:
                        with pipeline_lock(blocking=False):
                            if import_file:
                                run = refresh_external_source(source_id, import_file=import_file)
                            else:
                                run = refresh_external_source(source_id)
                        payload = {"ok": run.get("status") == "OK", "run": run}
                    except PipelineBusy:
                        payload = dict(_BUSY_PAYLOAD, source_id=source_id)
                        response_status = 409
                    except ValueError as exc:
                        payload = {"ok": False, "source_id": source_id, "error": str(exc)}
                        response_status = 400
                    except Exception:
                        payload = {
                            "ok": False,
                            "source_id": source_id,
                            "error": traceback.format_exc()[-2000:],
                        }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/refresh_external_sources":
                response_status = 200
                try:
                    with pipeline_lock(blocking=False):
                        payload = refresh_all_external_sources()
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/rerun_external_precheck":
                response_status = 200
                try:
                    payload = rerun_external_precheck()
                    if payload.get("busy"):
                        response_status = 409
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/ibkr_live_check":
                as_of = req.get("as_of", default_as_of)
                response_status = 200
                try:
                    payload = run_live_check(as_of, blocking=False)
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD, as_of=as_of)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "status": "LIVE_CHECK_EXCEPTION",
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/confirm_execution":
                response_status = 200
                try:
                    with pipeline_lock(blocking=False):
                        config = load_config()
                        state_db_path = resolve_path(config, "archive_dir") / "hermes_state.sqlite"
                        payload = record_execution_confirmation(
                            state_db_path,
                            symbol=str(req.get("symbol", "")).upper(),
                            tranche=str(req.get("tranche", "")),
                            status=str(req.get("status", "CONFIRMED")),
                            source=str(req.get("source", "manual_web")),
                            confirmed_at=req.get("confirmed_at"),
                            payload=req,
                        )
                        payload["ok"] = True
                        payload["auth_status"] = auth_status
                except PipelineBusy:
                    payload = dict(_BUSY_PAYLOAD)
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            self._send(404, "text/plain; charset=utf-8", b"not found")

        def log_message(self, *_): return  # noqa: silence default logging

        def _send(self, status: int, ct: str, body: bytes) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # Client disconnected mid-response (e.g. clicked 更新策略数据 then
                # navigated away during the ~70s rescore). Nothing to send to — not
                # an error worth a traceback in dashboard.err.log.
                pass

    return Handler


def create_server(host: str, port: int, default_as_of: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(default_as_of))
