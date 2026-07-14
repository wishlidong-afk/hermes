from __future__ import annotations

import hashlib
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock

from hermes_escape_top.core.data.run_transaction import recover_incomplete_score_run, score_run_transaction
from hermes_escape_top.core.safe_io import pipeline_lock
from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.web.server import (
    _attach_alpaca_daily_flow,
    _attach_market_admission_status,
    _latest_score_payload,
)
from hermes_escape_top.web.render import render_dashboard, write_dashboard


class Phase14WebTest(unittest.TestCase):
    def test_score_pipeline_persists_market_admission_context_in_audit(self) -> None:
        status = {
            "mode": "enforce_consensus",
            "status": "ERROR",
            "operation_id": "current-run",
            "run_error": "OSError: evidence disk full",
        }
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline(
                "2026-05-29",
                market_admission_status=status,
            )

        record = json.loads(Path(payload["audit_log_path"]).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(payload["market_admission_status"], status)
        self.assertEqual(record["payload"]["market_admission_status"], status)

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

    def test_market_admission_attachment_never_hides_missing_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"as_of": "2026-07-13"}
            with mock.patch(
                "hermes_escape_top.web.server.load_config",
                return_value={
                    "features": {"use_market_admission_gate": True},
                    "paths": {"archive_dir": tmp},
                },
            ):
                _attach_market_admission_status(payload)

        self.assertEqual(payload["market_admission_status"]["status"], "MISSING")
        self.assertEqual(payload["market_admission_status"]["mode"], "enforce_consensus")

    def test_market_admission_attachment_loads_current_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            history = archive / "history"
            history.mkdir()
            canonical = history / "QQQ.csv"
            canonical.write_text("date,close\n2026-07-13,100\n", encoding="utf-8")
            (archive / "market_admission_latest.json").write_text(
                json.dumps({
                    "mode": "enforce_consensus",
                    "status": "BLOCKED",
                    "rejected_rows": 1,
                    "generated_at": "2026-07-14T00:05:00+00:00",
                    "completed_through": "2026-07-13",
                    "operation_id": "current-run",
                    "canonical_files": {
                        "QQQ.csv": {
                            "sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
                            "latest_as_of": "2026-07-13",
                        }
                    },
                }),
                encoding="utf-8",
            )
            payload = {"as_of": "2026-07-13"}
            with mock.patch(
                "hermes_escape_top.web.server.load_config",
                return_value={
                    "features": {"use_market_admission_gate": True},
                    "paths": {"archive_dir": tmp, "history_dir": str(history)},
                },
            ):
                _attach_market_admission_status(payload)

        self.assertEqual(payload["market_admission_status"]["status"], "BLOCKED")

    def test_market_admission_attachment_rejects_stale_ok_from_prior_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            history = root / "history"
            archive.mkdir()
            history.mkdir()
            (archive / "market_admission_latest.json").write_text(
                json.dumps({
                    "mode": "enforce_consensus",
                    "status": "OK",
                    "generated_at": "2026-07-01T03:00:00+00:00",
                    "completed_through": "2026-07-01",
                    "operation_id": "old-run",
                    "canonical_files": {},
                }),
                encoding="utf-8",
            )
            payload = {
                "as_of": "2026-07-13",
                "run_receipt": {"started_at": "2026-07-14T00:00:00+00:00"},
            }
            with mock.patch(
                "hermes_escape_top.web.server.load_config",
                return_value={
                    "features": {"use_market_admission_gate": True},
                    "paths": {
                        "archive_dir": str(archive),
                        "history_dir": str(history),
                    },
                },
            ):
                _attach_market_admission_status(payload)

        self.assertEqual(payload["market_admission_status"]["status"], "STALE")

    def test_market_admission_attachment_detects_canonical_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            history = root / "history"
            archive.mkdir()
            history.mkdir()
            (history / "QQQ.csv").write_text("date,close\n2026-07-13,100\n", encoding="utf-8")
            (archive / "market_admission_latest.json").write_text(
                json.dumps({
                    "mode": "enforce_consensus",
                    "status": "OK",
                    "generated_at": "2026-07-14T00:05:00+00:00",
                    "completed_through": "2026-07-13",
                    "operation_id": "current-run",
                    "canonical_files": {
                        "QQQ.csv": {"sha256": "0" * 64, "latest_as_of": "2026-07-13"},
                    },
                }),
                encoding="utf-8",
            )
            payload = {
                "as_of": "2026-07-13",
                "run_receipt": {"started_at": "2026-07-14T00:00:00+00:00"},
            }
            with mock.patch(
                "hermes_escape_top.web.server.load_config",
                return_value={
                    "features": {"use_market_admission_gate": True},
                    "paths": {
                        "archive_dir": str(archive),
                        "history_dir": str(history),
                    },
                },
            ):
                _attach_market_admission_status(payload)

        self.assertEqual(
            payload["market_admission_status"]["status"],
            "EVIDENCE_DRIFT",
        )

    def test_market_admission_attachment_preserves_current_run_error_over_old_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            history = root / "history"
            archive.mkdir()
            history.mkdir()
            canonical = history / "QQQ.csv"
            canonical.write_text("date,close\n2026-07-13,100\n", encoding="utf-8")
            canonical_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
            common = {
                "mode": "enforce_consensus",
                "generated_at": "2026-07-14T00:05:00+00:00",
                "completed_through": "2026-07-13",
                "canonical_files": {
                    "QQQ.csv": {"sha256": canonical_hash, "latest_as_of": "2026-07-13"},
                },
            }
            (archive / "market_admission_latest.json").write_text(
                json.dumps({**common, "status": "OK", "operation_id": "old-run"}),
                encoding="utf-8",
            )
            payload = {
                "as_of": "2026-07-13",
                "run_receipt": {"started_at": "2026-07-14T00:00:00+00:00"},
                "market_admission_status": {
                    **common,
                    "status": "ERROR",
                    "operation_id": "current-run",
                    "run_error": "OSError: evidence disk full",
                },
            }
            with mock.patch(
                "hermes_escape_top.web.server.load_config",
                return_value={
                    "features": {"use_market_admission_gate": True},
                    "paths": {
                        "archive_dir": str(archive),
                        "history_dir": str(history),
                    },
                },
            ):
                _attach_market_admission_status(payload)

        self.assertEqual(payload["market_admission_status"]["status"], "ERROR")
        self.assertEqual(payload["market_admission_status"]["operation_id"], "current-run")


if __name__ == "__main__":
    unittest.main()
