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
import subprocess
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parents[2]
VENV_PYTHON = BASE_DIR.parent.parent.parent.parent / ".hermes" / "hermes-agent" / "venv" / "bin" / "python3"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
SHADOW_LOG = BASE_DIR / "reports" / "shadow" / "M4_shadow_log.jsonl"
RUN_DAILY = BASE_DIR / "scripts" / "run_daily.py"
RUN_DAILY_PKG = BASE_DIR / "scripts" / "run_daily_package.py"

from ..config import load_config, resolve_path
from ..pipeline import score_pipeline
from .render import render_dashboard


# ── helpers ───────────────────────────────────────────────────────────────────

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
        target = str(as_of)[:10]
        path = resolve_path(load_config(), "archive_dir") / "audit_log.jsonl"
        if not path.exists():
            return None
        fallback = None
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
            if pday == target:
                payload = dict(payload)
                payload["cache_status"] = {"hit": True, "source": str(path), "exact": True}
                return payload
            if pday and pday <= target and fallback is None:
                fallback = dict(payload)
                fallback["cache_status"] = {"hit": True, "source": str(path), "exact": False, "requested_as_of": target}
        return fallback
    except Exception:
        return None


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
    return {
        "log_entries": entries,
        "shadow_precheck": shadow_latest,
        "run_daily_mode": _read_run_daily_mode(),
    }


def _run_shadow(as_of: str) -> dict:
    cmd = [PYTHON, str(RUN_DAILY_PKG), "--as-of", as_of, "--skip-refresh"]
    try:
        r = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=180)
        output = r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else "")
        ok = r.returncode == 0
        diff_result = _diff_shadow(as_of)
        return {"ok": ok, "output": output[-2000:], "diff": diff_result}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "Timeout (180s)", "diff": None}
    except Exception:
        return {"ok": False, "output": traceback.format_exc()[-1000:], "diff": None}


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
        if not backup.exists():
            backup.write_text(RUN_DAILY.read_text(encoding="utf-8"), encoding="utf-8")
        new_content = (
            '#!/usr/bin/env python3\n'
            '"""run_daily.py — M4 live: package engine.\n'
            'Monolith backup: run_daily.py.monolith_backup\n"""\n'
            'import subprocess, sys\n'
            'from pathlib import Path\n'
            'BASE_DIR = Path(__file__).resolve().parent\n'
            'PYTHON = sys.executable\n'
            'if __name__ == "__main__":\n'
            '    cmd = [PYTHON, str(BASE_DIR / "run_daily_package.py"),\n'
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
            as_of = params.get("as_of", [default_as_of])[0]

            if parsed.path in {"/", "/index.html"}:
                payload = _latest_score_payload(as_of) or _empty_dashboard_payload(as_of)
                shadow = _shadow_status()
                self._send(200, "text/html; charset=utf-8",
                           render_dashboard(payload, shadow_status=shadow).encode())
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

            if parsed.path == "/api/m4_shadow":
                as_of = req.get("as_of", default_as_of)
                result = _run_shadow(as_of)
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

            if parsed.path in {"/api/refresh_score", "/api/score"}:
                as_of = req.get("as_of", default_as_of)
                payload = score_pipeline(as_of)
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
