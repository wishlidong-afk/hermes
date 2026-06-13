#!/usr/bin/env python3
"""Serve the operator workbench on 8765 (read-only).

Reads the latest audit_log entry on every GET (tail-seek — the file is
hundreds of MB) and renders web/workbench.py. No POST endpoints: actions
live on 8766; this page only answers the four operator questions.

Usage: PYTHONPATH=<pkg parent> python3 -m hermes_escape_top.scripts.serve_workbench \
           [--host 127.0.0.1] [--port 8765]
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.web.workbench import render_workbench

TAIL_CHUNK = 32 * 1024 * 1024


def _recent_records(limit: int = 60) -> list:
    """Newest-first audit records (tail of the log; the file is hundreds of MB)."""
    config = load_config()
    path = resolve_path(config, "archive_dir") / "audit_log.jsonl"
    if not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_CHUNK))
        lines = [l for l in fh.read().split(b"\n") if l.strip()]
    out = []
    for raw in reversed(lines):
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
        if len(out) >= limit:
            break
    return out


def official_and_preview() -> tuple:
    """(official_payload, preview_payload_or_None).

    Official = the latest SCHEDULED run (the launchd daily job). Preview =
    a more-recent manual_rerun for the SAME as_of, if one exists — shown as
    non-official so an intraday verification re-run can never masquerade as
    today's advice (the 2026-06-11 fake-EXIT lesson). Records predating the
    run_type tag are treated as scheduled so old logs still resolve.
    """
    recs = _recent_records()
    if not recs:
        return {}, None
    latest = recs[0].get("payload") or {}
    latest_rt = (recs[0].get("payload") or {}).get("run_type", "scheduled")
    official = None
    for r in recs:
        pl = r.get("payload") or {}
        if pl.get("run_type", "scheduled") == "scheduled":
            official = pl
            break
    if official is None:
        official = latest  # no scheduled record in window; show what we have
        return official, None
    # Preview only when the newest record is a manual rerun AND it differs from
    # the official run (same as_of, newer) — otherwise nothing to disclaim.
    preview = None
    if latest_rt != "scheduled" and latest.get("input_hash") != official.get("input_hash"):
        preview = latest
    return official, preview


def latest_payload() -> dict:
    official, _ = official_and_preview()
    return official
    return {}


REFRESH_SCRIPT = Path.home() / ".hermes" / "bin" / "run_daily.sh"


def _refresh_running() -> bool:
    import subprocess
    probe = subprocess.run(["pgrep", "-f", "run_daily_package.py"], capture_output=True)
    return probe.returncode == 0


# (name, cadence, max_age_days). Daily ages mirror config.soft_data_slo;
# AAII gets an early-warning budget of 10 (alert before the 13d SLO).
TRUST_SOURCES = [
    ("cboe_equity_pcr", "daily", 6), ("fred_net_liquidity", "daily", 6),
    ("real_rate", "daily", 6), ("dollar", "weekly", 13),
    ("naaim_exposure", "weekly", 13), ("aaii_sentiment", "weekly", 10),
    ("occ_equity_pcr", "weekly", 13), ("cot_nq", "weekly", 13),
]


def trust_rows() -> list:
    import csv as _csv
    from datetime import date as _date
    config = load_config()
    soft = resolve_path(config, "soft_history_dir")
    out = []
    today = _date.today()
    for name, cadence, max_age in TRUST_SOURCES:
        path = soft / f"{name}.csv"
        row = {"name": name, "cadence": cadence}
        try:
            tail = [r for r in _csv.reader(path.open()) if r and r[0][:2] == "20"][-1]
            header = next(_csv.reader(path.open()))
            rec = dict(zip(header, tail))
            last = _date.fromisoformat(tail[0][:10])
            row["last_date"] = last.isoformat()
            row["days_left"] = max_age - (today - last).days
            row["is_proxy"] = str(rec.get("is_proxy", "")).lower() == "true"
            row["source"] = rec.get("source", "")
        except (OSError, ValueError, IndexError, StopIteration):
            row.update(last_date="缺失", days_left=None, is_proxy=False, source="")
        out.append(row)
    return out


def _local_only(headers) -> bool:
    """True only when Host and any Origin resolve to loopback."""
    def _loopback(value: str) -> bool:
        host = value.split("//")[-1].split("/")[0].rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1", "")
    if not _loopback(headers.get("Host") or ""):
        return False
    origin = headers.get("Origin")
    return _loopback(origin) if origin else True


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/refresh":
            self.send_error(404)
            return
        # localhost-only guard: /refresh only triggers a data pull+rescore (no
        # money/order path), so it doesn't require the 8766 token — but reject
        # cross-origin/DNS-rebinding callers so a malicious page can't make the
        # machine churn. Host/Origin must be loopback.
        if not _local_only(self.headers):
            self.send_error(403, "localhost only")
            return
        import subprocess
        if _refresh_running():
            msg = "已有更新在运行中，请稍候刷新页面"
        elif not REFRESH_SCRIPT.exists():
            msg = "run_daily.sh 不存在"
        else:
            subprocess.Popen(["/bin/bash", str(REFRESH_SCRIPT)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            msg = "已触发完整日任务（拉行情+软数据+评分，约 3 分钟），完成后刷新页面"
        body = msg.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        try:
            official, preview = official_and_preview()
            body = render_workbench(official, trust=trust_rows(), preview=preview).encode("utf-8")
            self.send_response(200)
        except Exception as exc:  # pragma: no cover — never blank-page the operator
            body = f"<pre>workbench render failed: {exc!r}</pre>".encode("utf-8")
            self.send_response(500)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), Handler)
    print(f"workbench serving on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
