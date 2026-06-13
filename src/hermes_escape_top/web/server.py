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

WRITE_ENDPOINTS = {
    "/api/m4_shadow",
    "/api/m4_backfill",
    "/api/m4_golive",
    "/api/refresh_manifest",
    "/api/refresh_soft_data",
    "/api/ibkr_demo_snapshot",
    "/api/refresh_score",
    "/api/score",
    "/api/refresh_positions",
    "/api/ibkr_live_check",
    "/api/confirm_execution",
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


def _latest_score_payload(as_of: str) -> dict | None:
    """Load the newest package score payload from audit_log.jsonl without rerunning."""
    try:
        raw_target = str(as_of or "latest")
        latest_mode = raw_target.lower() in {"latest", "newest", ""}
        target = raw_target[:10]
        path = resolve_path(load_config(), "archive_dir") / "audit_log.jsonl"
        if not path.exists():
            return None
        fallback = None
        fallback_day = ""
        latest = None
        latest_day = ""
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            payload = record.get("payload") if isinstance(record, dict) else None
            if not isinstance(payload, dict) or "scores" not in payload:
                continue
            pday = str(payload.get("as_of", ""))[:10]
            if latest_mode:
                if pday and pday > latest_day:
                    latest_day = pday
                    latest = dict(payload)
                    latest["cache_status"] = {"hit": True, "source": str(path), "exact": True, "requested_as_of": raw_target}
                continue
            if pday == target:
                payload = dict(payload)
                payload["cache_status"] = {"hit": True, "source": str(path), "exact": True}
                return payload
            if pday and pday <= target and pday > fallback_day:
                fallback_day = pday
                fallback = dict(payload)
                fallback["cache_status"] = {"hit": True, "source": str(path), "exact": False, "requested_as_of": target}
        return latest if latest_mode else fallback
    except Exception:
        return None


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


def _auth_failure_payload(status: str) -> bytes:
    return json.dumps(
        {
            "ok": False,
            "status": status,
            "message": "write endpoint requires localhost Host/Origin and HERMES_CONFIRM_TOKEN",
        },
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
            '"""run_daily.py — M4 live: package engine.\n'
            'Monolith backup: run_daily.py.monolith_backup\n"""\n'
            'import subprocess, sys\n'
            'from pathlib import Path\n'
            'BASE_DIR = Path(__file__).resolve().parent\n'
            'PYTHON = sys.executable\n'
            'if __name__ == "__main__":\n'
            '    pkg = BASE_DIR / "run_daily_package.py"\n'
            '    if not pkg.exists():\n'
            '        pkg = BASE_DIR.parent / "src" / "hermes_escape_top" / "scripts" / "run_daily_package.py"\n'
            '    cmd = [PYTHON, str(pkg),\n'
            '           "--live", "--commit-state"] + sys.argv[1:]\n'
            '    r = subprocess.run(cmd, cwd=str(BASE_DIR.parent))\n'
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
                payload = _latest_score_payload(as_of) or _empty_dashboard_payload(as_of)
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

            if parsed.path in WRITE_ENDPOINTS:
                try:
                    allowed, auth_status = _write_request_allowed(load_config(), req, self.headers)
                except Exception:
                    allowed, auth_status = False, "AUTH_CHECK_ERROR"
                if not allowed:
                    self._send(403, "application/json; charset=utf-8", _auth_failure_payload(auth_status))
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
            self.send_response(status)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def create_server(host: str, port: int, default_as_of: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(default_as_of))
