from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from hermes_escape_top.core.data.run_transaction import recover_incomplete_score_run, score_run_transaction
from hermes_escape_top.core.safe_io import pipeline_lock
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
        self.assertNotIn("IBKR Live 验收", html)
        self.assertNotIn("runIbkrLiveCheck", html)
        self.assertIn("更新持仓", html)
        self.assertIn("ibkr.source === 'tws' && !ibkr.snapshot_stale", html)
        self.assertIn("持仓未更新：未连接 IBKR Live", html)
        self.assertIn("IBKR 现有总资产", html)
        self.assertIn("宏观 A 模块评分", html)
        self.assertIn("穿透股票成交与流向参考", html)

    def test_strategy_refresh_previews_but_position_refresh_stays_official(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        html = render_dashboard(payload)
        strategy_fn = html[html.index("window.refreshScore"):html.index("window.refreshPositions")]
        positions_fn = html[html.index("window.refreshPositions"):html.index("window.refreshManifest")]
        self.assertIn("view=preview", strategy_fn)
        self.assertNotIn("view=preview", positions_fn)
        self.assertIn("no market refresh, no official rerun", positions_fn)
        self.assertIn("不重抓行情、不重算官方策略", positions_fn)

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

    def test_latest_score_payload_hides_a_pending_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "data" / "archive"
            archive.mkdir(parents=True)
            audit = archive / "audit_log.jsonl"
            audit.write_text(json.dumps({"payload": {
                "as_of": "2026-06-04",
                "run_type": "scheduled",
                "scores": {"MSTR": {"status": "HOLD"}},
            }}) + "\n", encoding="utf-8")
            with pipeline_lock(path=archive / ".pipeline.lock") as lease:
                context = score_run_transaction(
                    archive, [audit], metadata={"as_of": "2026-06-05"}, _lease=lease
                )
                transaction = context.__enter__()
                with audit.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"payload": {
                        "as_of": "2026-06-05",
                        "run_type": "scheduled",
                        "persistence": {"run_id": transaction.run_id},
                        "scores": {"MSTR": {"status": "EXIT"}},
                    }}) + "\n")

                with mock.patch("hermes_escape_top.web.server.load_config", return_value={}), mock.patch(
                    "hermes_escape_top.web.server.resolve_path", return_value=archive
                ):
                    latest = _latest_score_payload("latest")

                self.assertEqual(latest["as_of"], "2026-06-04")
                recover_incomplete_score_run(archive, _lease=lease)

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
