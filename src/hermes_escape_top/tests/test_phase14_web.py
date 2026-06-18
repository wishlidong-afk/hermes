from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.web.server import _attach_alpaca_daily_flow, _latest_score_payload
from hermes_escape_top.web.render import render_dashboard, write_dashboard


class Phase14WebTest(unittest.TestCase):
    def test_render_dashboard_contains_core_sections(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        html = render_dashboard(payload)
        self.assertIn("今日操作台", html)
        self.assertIn("Evidence Strip", html)
        self.assertIn("Hard Valve Radar", html)
        self.assertIn("System Health", html)
        self.assertIn("Audit Detail", html)
        self.assertIn("Portfolio Risk", html)
        self.assertNotIn("Mirror Reference", html)
        self.assertIn("IBKR Live 验收", html)
        self.assertIn("更新持仓", html)
        self.assertIn("IBKR 现有总资产", html)
        self.assertIn("宏观 A 模块评分", html)
        self.assertIn("穿透股票成交与流向参考", html)

    def test_write_dashboard_file(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_dashboard(payload, Path(tmp) / "dashboard.html")
            self.assertTrue(path.exists())
            self.assertIn("Hermes Escape Top", path.read_text())

    def test_latest_score_payload_uses_newest_date_not_tail_record(self) -> None:
        def record(as_of: str, source: str) -> str:
            return json.dumps({
                "payload": {
                    "as_of": as_of,
                    "scores": {"MSTR": {"status": "HOLD"}},
                    "ibkr": {"source": source},
                }
            })

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            (archive / "audit_log.jsonl").write_text(
                "\n".join([
                    record("2026-06-04", "tws"),
                    record("2026-05-29", "disabled"),
                ]) + "\n",
                encoding="utf-8",
            )
            with mock.patch("hermes_escape_top.web.server.load_config", return_value={}), mock.patch(
                "hermes_escape_top.web.server.resolve_path",
                return_value=archive,
            ):
                latest = _latest_score_payload("latest")
                exact = _latest_score_payload("2026-05-29")
        self.assertEqual(latest["as_of"], "2026-06-04")
        self.assertEqual(latest["ibkr"]["source"], "tws")
        self.assertEqual(exact["as_of"], "2026-05-29")

    def test_alpaca_flow_attachment_never_uses_a_future_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            for day in ("2026-06-16", "2026-06-18"):
                (archive / f"alpaca_daily_flow_{day}.json").write_text(json.dumps({
                    "schema_version": "alpaca-sip-daily-flow-v1",
                    "as_of": day,
                    "baskets": {"MSTR": {"net_notional": 1}},
                }), encoding="utf-8")
            payload = {"as_of": "2026-06-17"}
            with mock.patch("hermes_escape_top.web.server.load_config", return_value={}), mock.patch(
                "hermes_escape_top.web.server.resolve_path", return_value=archive
            ):
                _attach_alpaca_daily_flow(payload)

        self.assertEqual(payload["alpaca_daily_flow"]["as_of"], "2026-06-16")


if __name__ == "__main__":
    unittest.main()
