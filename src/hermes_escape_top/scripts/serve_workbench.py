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


def latest_payload() -> dict:
    config = load_config()
    path = resolve_path(config, "archive_dir") / "audit_log.jsonl"
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_CHUNK))
        lines = [l for l in fh.read().split(b"\n") if l.strip()]
    for raw in reversed(lines):
        try:
            return json.loads(raw).get("payload") or {}
        except json.JSONDecodeError:
            continue
    return {}


REFRESH_SCRIPT = Path.home() / ".hermes" / "bin" / "run_daily.sh"


def _refresh_running() -> bool:
    import subprocess
    probe = subprocess.run(["pgrep", "-f", "run_daily_package.py"], capture_output=True)
    return probe.returncode == 0


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/refresh":
            self.send_error(404)
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
            body = render_workbench(latest_payload()).encode("utf-8")
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
