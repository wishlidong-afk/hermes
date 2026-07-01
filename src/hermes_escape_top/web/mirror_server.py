"""Standalone Hermes Mirror Reference WebUI server."""
from __future__ import annotations

import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..core.safe_io import PipelineBusy
from .mirror_render import render_mirror_dashboard
from .refresh import apply_ibkr_position_overlay, refresh_positions_only, refresh_score_with_market_data
from .server import _empty_dashboard_payload, _latest_score_payload


def make_mirror_handler(default_as_of: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "HermesMirrorHTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            as_of = params.get("as_of", ["latest"])[0]

            if parsed.path in {"/", "/index.html"}:
                payload = _latest_score_payload(as_of) or _empty_dashboard_payload(as_of)
                payload = apply_ibkr_position_overlay(payload)
                self._send(200, "text/html; charset=utf-8", render_mirror_dashboard(payload).encode())
                return

            if parsed.path == "/api/score":
                payload = _latest_score_payload(as_of)
                if payload is None:
                    payload = {"ok": False, "as_of": as_of, "message": "No cached score payload. POST /api/refresh_score to refresh."}
                else:
                    payload = apply_ibkr_position_overlay(payload)
                self._send(200, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode())
                return

            if parsed.path == "/health":
                self._send(200, "application/json; charset=utf-8", b'{"ok":true,"app":"mirror"}')
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

            if parsed.path in {"/api/refresh_score", "/api/score", "/api/refresh_positions"}:
                as_of = req.get("as_of", "latest")
                response_status = 200
                try:
                    refresh = refresh_positions_only if parsed.path == "/api/refresh_positions" else refresh_score_with_market_data
                    if parsed.path == "/api/refresh_positions":
                        payload = refresh(as_of, blocking=False, base_payload=_latest_score_payload(as_of) or {"as_of": as_of})
                    else:
                        payload = refresh(as_of, blocking=False)
                except PipelineBusy:
                    payload = {
                        "ok": False,
                        "busy": True,
                        "as_of": as_of,
                        "message": "another pipeline writer is active",
                    }
                    response_status = 409
                except Exception:
                    payload = {
                        "ok": False,
                        "as_of": as_of,
                        "error": traceback.format_exc()[-2000:],
                    }
                self._send(response_status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str).encode())
                return

            self._send(404, "text/plain; charset=utf-8", b"not found")

        def log_message(self, *_: object) -> None:
            return

        def _send(self, status: int, ct: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def create_mirror_server(host: str, port: int, default_as_of: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_mirror_handler(default_as_of))
