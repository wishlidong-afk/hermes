"""Hermes Escape-Top WebUI server.

Endpoints:
  GET  /                   Dashboard
  GET  /api/score          Latest cached score JSON (read-only)
  POST /api/refresh_score  Recompute score JSON and update archive
  GET  /api/shadow_status  M4 shadow log + latest shadow precheck
  POST /api/m4_shadow      M4-2: run package engine in shadow mode
  POST /api/m4_golive      M4-3: flip run_daily.py to package (human gate)
  GET  /health             Healthcheck
"""
from __future__ import annotations

import json
import hmac
import os
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PACKAGE_DIR = Path(__file__).resolve().parents[1]


def _runtime_root() -> Path:
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
from ..core.data.state_store import record_execution_confirmation
from ..ibkr.live_check import run_live_check
from ..ibkr.positions import write_demo_snapshot
from ..pipeline import score_pipeline
from .health import compute_health
from .refresh import (
    force_refresh_manifest,
    manifest_status,
    refresh_score_with_market_data,
)
from .render import render_dashboard


# ── helpers ───────────────────────────────────────────────────────────────────

# Dangerous writes that change production behavior or decision state: require a
# loopback Host/Origin AND HERMES_CONFIRM_TOKEN.
TOKEN_WRITE_ENDPOINTS = {
    "/api/m4_golive",          # flips run_daily.py to the package engine
    "/api/confirm_execution",  # writes execution confirmations that feed reentry
}
# Low-risk data refresh / recompute (no order or money path — the system never
# orders) are loopback-only, matching the 8765 workbench /refresh. A token here is
# friction without security value: loopback already blocks remote/CSRF callers,
# and the worst a local caller can do is refresh data.
LOOPBACK_WRITE_ENDPOINTS = {
    "/api/m4_shadow",
    "/api/m4_backfill",
    "/api/refresh_manifest",
    "/api/refresh_soft_data",
    "/api/ibkr_demo_snapshot",
    "/api/refresh_score",
    "/api/refresh_positions",
    "/api/ibkr_live_check",
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
        flow = load_daily_flow_snapshot(resolve_path(config, "archive_dir"), payload.get("as_of", ""))
        if flow is not None:
            payload["alpaca_daily_flow"] = flow
    except Exception:
        pass
    return payload


def _latest_score_payload(as_of: str, records: list | None = None) -> dict | None:
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
    cmd = [PYTHON, str(RUN_DAILY_PKG), "--as-of", as_of, "--skip-refresh"]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), env=_subprocess_env(), capture_output=True, text=True, timeout=180)
        output = r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else "")
        ok = r.returncode == 0
        diff_result = _diff_shadow(as_of)
        return {"ok": ok, "output": output[-2000:], "diff": diff_result}
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
    refresh = _run_history_refresh(as_of)
    baseline = _run_baseline(as_of) if refresh.get("ok") else {"ok": False, "output": "Skipped baseline because refresh failed."}
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

            if parsed.path in {"/", "/index.html"}:
                audit_records = _read_audit_payloads()  # single audit read for all three lookups
                payload = _latest_score_payload(as_of, audit_records) or _empty_dashboard_payload(as_of)
                _attach_alpaca_daily_flow(payload)
                payload["status_history"] = _recent_status_history(payload.get("as_of") or as_of, records=audit_records)
                payload["prev_valves"] = _prev_official_valves(audit_records, payload.get("as_of") or as_of)
                payload["run_receipt"] = _read_run_receipt()
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
                    _attach_alpaca_daily_flow(payload)
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

            if parsed.path == "/api/health_status":
                try:
                    score = _latest_score_payload(as_of) or _empty_dashboard_payload(as_of)
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

            if parsed.path == "/api/m4_shadow":
                as_of = req.get("as_of", default_as_of)
                result = _run_shadow(as_of)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(result, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/m4_backfill":
                as_of = req.get("as_of", default_as_of)
                result = _backfill_compare(as_of)
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(result, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/m4_golive":
                if req.get("confirmed") is not True:
                    self._send(400, "application/json; charset=utf-8",
                               b'{"ok":false,"message":"Must send confirmed:true"}')
                    return
                result = _flip_to_package()
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(result, ensure_ascii=False, default=str).encode())
                return

            if parsed.path == "/api/refresh_manifest":
                try:
                    payload = force_refresh_manifest()
                except Exception:
                    payload = {"ok": False, "status": "ERROR", "error": traceback.format_exc()[-2000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/refresh_soft_data":
                try:
                    from ..scripts.backfill_soft_data import refresh_all
                    payload = refresh_all(only=req.get("only"))
                except Exception:
                    payload = {"ok": False, "error": traceback.format_exc()[-2000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path == "/api/ibkr_demo_snapshot":
                try:
                    written = write_demo_snapshot(force=bool(req.get("force")))
                    payload = dict(written)
                    if written.get("ok"):
                        # Re-score so the cached dashboard payload reflects demo positions.
                        latest = _latest_score_payload("latest") or {}
                        as_of = latest.get("as_of") or default_as_of
                        try:
                            rescored = score_pipeline(str(as_of)[:10])
                            payload["rescored_as_of"] = rescored.get("as_of")
                            payload["ibkr_source"] = (rescored.get("ibkr") or {}).get("source")
                        except Exception:
                            payload["rescore_error"] = traceback.format_exc()[-1000:]
                except Exception:
                    payload = {"ok": False, "error": traceback.format_exc()[-2000:]}
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode())
                return

            if parsed.path in {"/api/refresh_score", "/api/score"}:
                as_of = req.get("as_of", "latest")
                try:
                    payload = refresh_score_with_market_data(as_of)
                except Exception:
                    payload = {
                        "ok": False,
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/refresh_positions":
                as_of = req.get("as_of", "latest")
                try:
                    payload = refresh_score_with_market_data(as_of)
                except Exception:
                    payload = {
                        "ok": False,
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/ibkr_live_check":
                as_of = req.get("as_of", default_as_of)
                try:
                    payload = run_live_check(as_of)
                except Exception:
                    payload = {
                        "ok": False,
                        "status": "LIVE_CHECK_EXCEPTION",
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(payload, ensure_ascii=False, indent=2,
                                      sort_keys=True, default=str).encode())
                return

            if parsed.path == "/api/confirm_execution":
                try:
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
                except Exception:
                    payload = {
                        "ok": False,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(200, "application/json; charset=utf-8",
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
