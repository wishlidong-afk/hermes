from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from unittest import mock

import pandas as pd

from hermes_escape_top.core.backtest.posterior import ideal_previous_day_pnl
from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.web.server import create_server


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
        payload = score_pipeline("2026-05-29")
        self.assertIn("posterior_pnl", payload)
        self.assertEqual(set(payload["posterior_pnl"]["escape"]), {"FNGU", "MSTR", "SOXL"})
        self.assertEqual(set(payload["posterior_pnl"]["mirror"]), {"FNGU_QQQ", "MSTR_QQQ", "SOXL_SOXX"})

    def test_read_only_server_health_and_api(self) -> None:
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
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertIn("posterior_pnl", payload)
                self.assertIn("mirror", payload)
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
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch(
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


if __name__ == "__main__":
    unittest.main()
