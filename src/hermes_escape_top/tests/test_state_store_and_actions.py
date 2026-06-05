from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.core.data.state_store import (
    latest_execution_confirmations,
    recent_calibration_logs,
    recent_ibkr_snapshots,
    record_execution_confirmation,
    write_refresh_run,
)


class StateStoreAndActionTest(unittest.TestCase):
    def test_pipeline_writes_unified_state_and_action_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "hermes_escape_top.config.CONFIG_PATH",
            Path("src/hermes_escape_top/config/config.json"),
        ):
            # Use default config paths but disable IBKR to avoid live dependency.
            with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
                payload = score_pipeline("2026-06-04", include_ibkr=True)
        self.assertIn("state", payload)
        self.assertIn("today_ops", payload)
        self.assertIn("action_intents", payload)
        self.assertIn("decision_layers", payload)
        self.assertIn("data_quality_breakdown", payload)
        self.assertIn("ibkr_history", payload)
        self.assertIn("calibration_history", payload)
        self.assertEqual(set(payload["action_intents"]), {"FNGU", "MSTR", "SOXL"})
        db_path = Path(payload["state"]["db_path"])
        self.assertTrue(db_path.exists())
        with sqlite3.connect(db_path) as conn:
            runs = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
            decisions = conn.execute("SELECT COUNT(*) FROM decisions WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM data_sources WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
            reentry = conn.execute("SELECT COUNT(*) FROM reentry_states WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
            calibration = conn.execute("SELECT COUNT(*) FROM calibration_logs WHERE as_of='2026-06-04'").fetchone()[0]
        self.assertGreaterEqual(runs, 1)
        self.assertEqual(decisions, 3)
        self.assertGreater(sources, 0)
        self.assertEqual(reentry, 3)
        self.assertGreater(calibration, 0)
        self.assertGreaterEqual(len(recent_ibkr_snapshots(db_path)), 1)
        self.assertGreaterEqual(len(recent_calibration_logs(db_path)), 1)

    def test_refresh_run_writer_records_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            meta = write_refresh_run(
                path,
                requested_as_of="latest",
                effective_as_of="2026-06-04",
                status="OK",
                steps=[{"name": "history_refresh", "status": "SKIPPED"}],
                refresh_status={"symbols_updated": 0},
                payload_hash="abc",
            )
            self.assertEqual(meta["refresh_run_id"], 1)
            with sqlite3.connect(path) as conn:
                row = conn.execute("SELECT status, payload_hash FROM refresh_runs").fetchone()
        self.assertEqual(row, ("OK", "abc"))

    def test_execution_confirmation_writer_records_latest_by_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            meta = record_execution_confirmation(
                path,
                symbol="soxl",
                tranche="T1",
                status="CONFIRMED",
                source="unit_test",
                payload={"shares": 10},
            )
            self.assertEqual(meta["symbol"], "SOXL")
            latest = latest_execution_confirmations(path)
        self.assertEqual(latest["SOXL"]["tranche"], "T1")
        self.assertEqual(latest["SOXL"]["status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
