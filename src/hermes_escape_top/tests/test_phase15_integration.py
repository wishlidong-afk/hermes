from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import pandas as pd

from hermes_escape_top.config import load_config, resolve_path
from hermes_escape_top.core.backtest.posterior import ideal_previous_day_pnl
from hermes_escape_top.core.safe_io import PipelineBusy, pipeline_lock
from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.web.server import create_server


def _auth_headers(content_type: bool = True) -> dict[str, str]:
    headers = {"X-Hermes-Token": "secret", "Origin": "http://127.0.0.1"}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


class Phase15IntegrationTest(unittest.TestCase):
    def test_ideal_previous_day_pnl_known_values(self) -> None:
        dates = pd.bdate_range("2026-01-01", periods=2)
        history = pd.DataFrame({"Close": [100.0, 110.0]}, index=dates)
        row = ideal_previous_day_pnl("TEST", "TEST", 0.25, history, dates[-1].date().isoformat(), 100000.0)
        self.assertAlmostEqual(row.notional, 25000.0)
        self.assertAlmostEqual(row.shares, 250.0)
        self.assertAlmostEqual(row.pnl, 2500.0)
        self.assertAlmostEqual(row.return_pct, 0.10)

    def test_score_pipeline_includes_posterior_pnl(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        self.assertIn("posterior_pnl", payload)
        self.assertEqual(set(payload["posterior_pnl"]["escape"]), {"FNGU", "MSTR", "SOXL"})
        self.assertEqual(set(payload["posterior_pnl"]["mirror"]), {"MSTR_QQQ", "FNGU_QQQ", "SOXL_SOXX"})

    def test_score_pipeline_uses_ibkr_netliq_for_posterior_base(self) -> None:
        with mock.patch(
            "hermes_escape_top.pipeline._ibkr_payload",
            return_value={"source": "tws", "net_liq": 86_005.32},
        ):
            payload = score_pipeline("2026-05-29")
        self.assertEqual(payload["posterior_pnl"]["portfolio_value"], 86_005.32)

    def test_read_only_server_health_and_api(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            refreshed_payload = score_pipeline("2026-05-29")
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(f"{base}/health", timeout=10) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read().decode("utf-8"))["ok"], True)
            with urllib.request.urlopen(f"{base}/api/score", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("as_of", payload)
            request = urllib.request.Request(
                f"{base}/api/refresh_score",
                data=b"",
                headers=_auth_headers(content_type=False),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch("hermes_escape_top.web.server.refresh_score_with_market_data", return_value=refreshed_payload):
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("posterior_pnl", payload)
                self.assertIn("mirror", payload)
            request = urllib.request.Request(
                f"{base}/api/refresh_positions",
                data=b"",
                headers=_auth_headers(content_type=False),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch("hermes_escape_top.web.server.refresh_score_with_market_data", return_value=refreshed_payload):
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("ibkr", payload)
            with urllib.request.urlopen(f"{base}/api/score", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("posterior_pnl", payload)
                self.assertTrue(payload.get("cache_status", {}).get("hit"))
            with urllib.request.urlopen(f"{base}/", timeout=10) as response:
                html = response.read().decode("utf-8")
                self.assertIn("Posterior Ideal P/L", html)
                self.assertIn("IBKR Live 验收", html)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_ibkr_live_endpoint(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/ibkr_live_check",
                data=b'{"as_of":"2026-05-29"}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.run_live_check",
                return_value={"ok": False, "status": "IBKR_NOT_LIVE", "as_of": "2026-05-29"},
            ):
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(payload["status"], "IBKR_NOT_LIVE")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_ibkr_live_busy_returns_409(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/ibkr_live_check",
                data=b'{"as_of":"2026-05-29"}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.run_live_check",
                side_effect=PipelineBusy("pipeline busy"),
            ):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_ibkr_demo_busy_returns_409_without_write(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/ibkr_demo_snapshot",
                data=b"{}",
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server.write_demo_snapshot") as writer:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            writer.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_execution_confirmation_endpoint(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/confirm_execution",
                data=b'{"symbol":"SOXL","tranche":"T1","status":"CONFIRMED"}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.record_execution_confirmation",
                return_value={"confirmation_id": 7, "symbol": "SOXL", "tranche": "T1"},
            ):
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["confirmation_id"], 7)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_refresh_score_is_loopback_only_no_token_required(self) -> None:
        # The data-refresh endpoint (the '刷新策略数据' button) must work from a
        # loopback browser WITHOUT a token — token friction belongs only on the
        # dangerous endpoints. Loopback Origin, no X-Hermes-Token.
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            refreshed_payload = score_pipeline("2026-05-29")
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/refresh_score",
                data=b"",
                headers={"Origin": "http://127.0.0.1"},  # loopback, NO token
                method="POST",
            )
            with mock.patch("hermes_escape_top.web.server.refresh_score_with_market_data", return_value=refreshed_payload):
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("posterior_pnl", payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_refresh_score_returns_409_while_pipeline_lock_is_held(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/refresh_score",
                data=b'{"as_of":"latest"}',
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://127.0.0.1",
                },
                method="POST",
            )
            lock_path = resolve_path(load_config(), "archive_dir") / ".pipeline.lock"
            with pipeline_lock(blocking=False, path=lock_path):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(ctx.exception.code, 409)
                payload = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertTrue(payload["busy"])
            self.assertEqual(payload["as_of"], "latest")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_golive_still_requires_token_even_from_loopback(self) -> None:
        # The dangerous endpoint stays token-gated: a loopback caller WITHOUT a
        # token is rejected 403.
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/m4_golive",
                data=b'{"confirmed":true}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},  # loopback, NO token
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_golive_busy_returns_409_without_rewriting_entry(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/m4_golive",
                data=b'{"confirmed":true}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server._flip_to_package") as flip:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            flip.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_m4_backfill_busy_returns_409(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/m4_backfill",
                data=b'{"as_of":"2026-05-29"}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server._backfill_compare",
                side_effect=PipelineBusy("pipeline busy"),
            ):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_execution_confirmation_rejects_bad_token_without_write(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/confirm_execution",
                data=b'{"symbol":"SOXL","tranche":"T1","token":"wrong"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.record_execution_confirmation",
                return_value={"confirmation_id": 7},
            ) as recorder:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(ctx.exception.code, 403)
                payload = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "UNAUTHORIZED")
            recorder.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_execution_confirmation_busy_returns_409_without_write(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/confirm_execution",
                data=b'{"symbol":"SOXL","tranche":"T1"}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server.record_execution_confirmation") as recorder:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            recorder.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_server_execution_confirmation_accepts_header_token(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/confirm_execution",
                data=b'{"symbol":"SOXL","tranche":"T1"}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.record_execution_confirmation",
                return_value={"confirmation_id": 8, "symbol": "SOXL", "tranche": "T1"},
            ):
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["confirmation_id"], 8)
            self.assertEqual(payload["auth_status"], "TOKEN_OK")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_refresh_error_returns_json_not_empty_response(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/refresh_score",
                data=b'{"as_of":"latest"}',
                headers=_auth_headers(),
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch("hermes_escape_top.web.server.refresh_score_with_market_data", side_effect=RuntimeError("boom")):
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("boom", payload["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_token_write_endpoint_rejects_missing_token_without_calling_handler(self) -> None:
        # A token-gated endpoint (confirm_execution) rejects a missing token with
        # 403 BEFORE invoking its handler — no side effects on auth failure.
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/confirm_execution",
                data=b'{"symbol":"SOXL","tranche":"T1","status":"CONFIRMED"}',
                headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"},  # loopback, NO token
                method="POST",
            )
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch(
                "hermes_escape_top.web.server.record_execution_confirmation",
                return_value={},
            ) as recorder:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(ctx.exception.code, 403)
                payload = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertEqual(payload["status"], "UNAUTHORIZED")
            recorder.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def test_tail_lines_newest_first_is_bounded(tmp_path):
    # The dashboard's audit read must be bounded (not a 150MB+ full read per page
    # load). _tail_lines_newest_first returns newest-first and only the tail window.
    from pathlib import Path
    from hermes_escape_top.web.server import _tail_lines_newest_first

    p = tmp_path / "audit.jsonl"
    p.write_text("".join(f"line{i}\n" for i in range(100)), encoding="utf-8")
    lines = _tail_lines_newest_first(Path(p), max_bytes=30)  # tiny window
    nonempty = [l for l in lines if l.strip()]   # the loop skips empties (trailing \n)
    assert nonempty[0].strip() == b"line99"      # newest first
    assert len(nonempty) < 100                   # bounded to the tail, not the whole file


if __name__ == "__main__":
    unittest.main()
