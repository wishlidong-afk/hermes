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
                "SOXL": {"severity": "NORMAL", "components": []},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_flow_snapshot(Path(tmp) / "flow.sqlite", payload)
            with sqlite3.connect(path) as conn:
                rows = conn.execute("SELECT kind, symbol, severity FROM flow_snapshots ORDER BY kind, symbol").fetchall()
        self.assertEqual(rows, [("basket", "SOXL", "NORMAL"), ("symbol", "FNGU", "WATCH")])


if __name__ == "__main__":
    unittest.main()

