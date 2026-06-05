from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.core.data.state_store import write_refresh_run


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
        self.assertEqual(set(payload["action_intents"]), {"FNGU", "MSTR", "SOXL"})
        db_path = Path(payload["state"]["db_path"])
        self.assertTrue(db_path.exists())
        with sqlite3.connect(db_path) as conn:
            runs = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
            decisions = conn.execute("SELECT COUNT(*) FROM decisions WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
            sources = conn.execute("SELECT COUNT(*) FROM data_sources WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
            calibration = conn.execute("SELECT COUNT(*) FROM calibration_logs WHERE as_of='2026-06-04'").fetchone()[0]
        self.assertGreaterEqual(runs, 1)
        self.assertEqual(decisions, 3)
        self.assertGreater(sources, 0)
        self.assertGreater(calibration, 0)

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


if __name__ == "__main__":
    unittest.main()
