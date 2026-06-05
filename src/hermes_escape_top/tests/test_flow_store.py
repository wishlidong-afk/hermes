from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from hermes_escape_top.core.data.flow_store import write_flow_snapshot


class FlowStoreTest(unittest.TestCase):
    def test_write_flow_snapshot_persists_symbols_and_baskets(self) -> None:
        payload = {
            "as_of": "2026-06-04",
            "symbols": {
                "FNGU": {"symbol": "FNGU", "severity": "WATCH"},
            },
            "component_baskets": {
                "SOXL": {"severity": "NORMAL", "component_min_as_of": "2026-06-03", "component_max_stale_days": 1, "components": []},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_flow_snapshot(Path(tmp) / "flow.sqlite", payload)
            with sqlite3.connect(path) as conn:
                rows = conn.execute("SELECT kind, symbol, severity FROM flow_snapshots ORDER BY kind, symbol").fetchall()
                meta = conn.execute(
                    "SELECT component_min_as_of, component_max_stale_days, input_hash, created_at FROM flow_snapshots WHERE kind='basket' AND symbol='SOXL'"
                ).fetchone()
        self.assertEqual(rows, [("basket", "SOXL", "NORMAL"), ("symbol", "FNGU", "WATCH")])
        self.assertEqual(meta[0], "2026-06-03")
        self.assertEqual(meta[1], 1)
        self.assertTrue(meta[2])
        self.assertTrue(meta[3])


if __name__ == "__main__":
    unittest.main()
