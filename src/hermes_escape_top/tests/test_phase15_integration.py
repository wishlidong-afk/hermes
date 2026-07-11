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
            with mock.patch.dict("os.environ", {"HERMES_CONFIRM_TOKEN": "secret"}), mock.patch("hermes_escape_top.web.server.refresh_positions_only", return_value=refreshed_payload) as refresh_positions:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("ibkr", payload)
                refresh_positions.assert_called_once()
                args, kwargs = refresh_positions.call_args
                self.assertEqual(args, ("latest",))
                self.assertFalse(kwargs["blocking"])
                self.assertIn("as_of", kwargs["base_payload"])
                self.assertIn("sizing", kwargs["base_payload"])
            with urllib.request.urlopen(f"{base}/api/score", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("posterior_pnl", payload)
                self.assertTrue(payload.get("cache_status", {}).get("hit"))
            with urllib.request.urlopen(f"{base}/", timeout=10) as response:
                html = response.read().decode("utf-8")
                self.assertIn("Posterior Ideal P/L", html)
                self.assertNotIn("IBKR Live 验收", html)
                self.assertIn("更新持仓", html)
                self.assertIn("刷新全部外部源", html)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_health_status_uses_ibkr_overlay_before_computing_health(self) -> None:
        stale_payload = {
            "as_of": "2026-05-29",
            "cache_status": {"hit": True},
            "data_quality": {"level": "HIGH", "overall_score": 97.0},
            "data_quality_breakdown": {"sources": []},
            "ibkr": {
                "source": "snapshot",
                "sync_time": "2026-01-01T00:00:00+00:00",
                "snapshot_stale": True,
            },
        }
        fresh_payload = {
            **stale_payload,
            "ibkr": {
                "source": "tws",
                "sync_time": "2026-05-29T12:00:00+00:00",
                "snapshot_stale": False,
            },
        }

        def compute_health_probe(payload, manifest):
            self.assertEqual(payload["ibkr"]["source"], "tws")
            self.assertFalse(payload["ibkr"]["snapshot_stale"])
            return {"level": "OK", "checks": []}

        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with mock.patch("hermes_escape_top.web.server._latest_score_payload", return_value=stale_payload), \
                 mock.patch("hermes_escape_top.web.server.apply_ibkr_position_overlay", return_value=fresh_payload) as overlay, \
                 mock.patch("hermes_escape_top.web.server._attach_alpaca_daily_flow", side_effect=lambda payload: payload), \
                 mock.patch("hermes_escape_top.web.server._read_run_receipt", return_value={}), \
                 mock.patch("hermes_escape_top.web.server.manifest_status", return_value={"status": "OK"}), \
                 mock.patch("hermes_escape_top.web.server.compute_health", side_effect=compute_health_probe):
                with urllib.request.urlopen(f"{base}/api/health_status", timeout=10) as response:
                    health = json.loads(response.read().decode("utf-8"))
            overlay.assert_called_once()
            self.assertEqual(health["level"], "OK")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_api_score_and_health_status_attach_external_precheck_evidence(self) -> None:
        base_payload = {
            "as_of": "2026-05-29",
            "cache_status": {"hit": True},
            "data_quality": {"level": "HIGH", "overall_score": 97.0},
            "data_quality_breakdown": {"sources": []},
            "ibkr": {"source": "disabled"},
        }

        def attach_precheck(payload):
            payload["external_precheck_status"] = {
                "ready": True,
                "mtime_date": "2026-05-29",
                "warning_sources": ["real_rate"],
                "source_path": "/tmp/external_precheck_latest.json",
            }
            return payload

        def compute_health_probe(payload, manifest):
            self.assertTrue(payload["external_precheck_status"]["ready"])
            self.assertEqual(payload["external_precheck_status"]["warning_sources"], ["real_rate"])
            return {"level": "OK", "checks": []}

        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with mock.patch("hermes_escape_top.web.server._latest_score_payload", return_value=base_payload), \
                 mock.patch("hermes_escape_top.web.server.apply_ibkr_position_overlay", side_effect=lambda payload: dict(payload)), \
                 mock.patch("hermes_escape_top.web.server._attach_alpaca_daily_flow", side_effect=lambda payload: payload), \
                 mock.patch("hermes_escape_top.web.server._attach_external_source_status", side_effect=lambda payload: payload), \
                 mock.patch("hermes_escape_top.web.server._attach_external_precheck_status", side_effect=attach_precheck) as attach:
                with urllib.request.urlopen(f"{base}/api/score", timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["external_precheck_status"]["ready"])
            attach.assert_called_once()

            with mock.patch("hermes_escape_top.web.server._latest_score_payload", return_value=base_payload), \
                 mock.patch("hermes_escape_top.web.server.apply_ibkr_position_overlay", side_effect=lambda payload: dict(payload)), \
                 mock.patch("hermes_escape_top.web.server._attach_alpaca_daily_flow", side_effect=lambda payload: payload), \
                 mock.patch("hermes_escape_top.web.server._attach_external_source_status", side_effect=lambda payload: payload), \
                 mock.patch("hermes_escape_top.web.server._attach_external_precheck_status", side_effect=attach_precheck), \
                 mock.patch("hermes_escape_top.web.server._read_run_receipt", return_value={}), \
                 mock.patch("hermes_escape_top.web.server.manifest_status", return_value={"status": "OK"}), \
                 mock.patch("hermes_escape_top.web.server.compute_health", side_effect=compute_health_probe):
                with urllib.request.urlopen(f"{base}/api/health_status", timeout=10) as response:
                    health = json.loads(response.read().decode("utf-8"))
            self.assertEqual(health["level"], "OK")
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

    def test_retired_m4_and_demo_write_endpoints_return_410(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in (
                "/api/m4_shadow",
                "/api/m4_backfill",
                "/api/m4_golive",
                "/api/ibkr_demo_snapshot",
            ):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}{path}",
                    data=b'{"confirmed":true,"force":true}',
                    headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(ctx.exception.code, 410, path)
                payload = json.loads(ctx.exception.read().decode("utf-8"))
                self.assertTrue(payload["retired"])
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

    def test_external_source_status_endpoint_reads_ledger(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with mock.patch(
                "hermes_escape_top.web.server.external_source_status",
                return_value={
                    "dollar": {
                        "source_id": "dollar",
                        "status": "OK",
                        "latest_promoted_as_of": "2026-06-30",
                    }
                },
            ):
                with urllib.request.urlopen(f"{base}/api/external_source_status", timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["sources"]["dollar"]["status"], "OK")
            self.assertEqual(payload["sources"]["dollar"]["latest_promoted_as_of"], "2026-06-30")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_source_refresh_endpoint_is_single_source_and_loopback_only(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/refresh_external_source",
                data=b'{"source_id":"dollar"}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.refresh_external_source",
                return_value={"source_id": "dollar", "status": "OK", "promoted": True},
            ) as refresh:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            refresh.assert_called_once_with("dollar")
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run"]["status"], "OK")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_source_refresh_endpoint_accepts_official_import_file(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/refresh_external_source",
                data=b'{"source_id":"aaii_sentiment","import_file":"/Users/liweishi/.hermes/external_imports/sentiment.xls"}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.refresh_external_source",
                return_value={"source_id": "aaii_sentiment", "status": "OK", "promoted": True},
            ) as refresh:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            refresh.assert_called_once_with(
                "aaii_sentiment",
                import_file="/Users/liweishi/.hermes/external_imports/sentiment.xls",
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run"]["source_id"], "aaii_sentiment")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_source_refresh_all_endpoint_runs_bundle_once(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            request = urllib.request.Request(
                f"{base}/api/refresh_external_sources",
                data=b"{}",
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            expected = {
                "ok": False,
                "ok_count": 4,
                "error_count": 1,
                "runs": [{"source_id": "aaii_sentiment", "status": "FETCH_ERROR"}],
            }
            with mock.patch(
                "hermes_escape_top.web.server.refresh_all_external_sources",
                return_value=expected,
            ) as refresh:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            refresh.assert_called_once_with()
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["ok_count"], 4)
            self.assertEqual(payload["error_count"], 1)
            self.assertEqual(payload["runs"][0]["source_id"], "aaii_sentiment")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_source_refresh_returns_409_while_pipeline_lock_is_held(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/refresh_external_source",
                data=b'{"source_id":"dollar"}',
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server.refresh_external_source") as refresh:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            refresh.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_source_refresh_all_returns_409_while_pipeline_lock_is_held(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/refresh_external_sources",
                data=b"{}",
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server.refresh_all_external_sources") as refresh:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            refresh.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_precheck_rerun_endpoint_runs_precheck_only(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/rerun_external_precheck",
                data=b"{}",
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            expected = {
                "ok": True,
                "returncode": 0,
                "external_precheck_status": {"ready": True, "stale": False},
            }
            with mock.patch(
                "hermes_escape_top.web.server.rerun_external_precheck",
                return_value=expected,
            ) as rerun:
                with urllib.request.urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            rerun.assert_called_once_with()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["external_precheck_status"]["ready"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_external_precheck_rerun_returns_409_while_pipeline_lock_is_held(self) -> None:
        server = create_server("127.0.0.1", 0, "2026-05-29")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/rerun_external_precheck",
                data=b"{}",
                headers={"Origin": "http://127.0.0.1", "Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
                "hermes_escape_top.web.server.pipeline_lock",
                side_effect=PipelineBusy("pipeline busy"),
            ), mock.patch("hermes_escape_top.web.server.rerun_external_precheck") as rerun:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(request, timeout=10)
            self.assertEqual(ctx.exception.code, 409)
            self.assertTrue(json.loads(ctx.exception.read().decode("utf-8"))["busy"])
            rerun.assert_not_called()
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
