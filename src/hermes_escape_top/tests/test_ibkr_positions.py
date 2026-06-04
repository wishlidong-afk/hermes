"""Tests for read-only IBKR position ingestion."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_escape_top.ibkr import positions
from hermes_escape_top.ibkr.positions import PositionSnapshot


class TestReadPositionsFallback(unittest.TestCase):
    def test_closed_ports_return_unavailable_without_live_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "positions_cache.json"
            with (
                mock.patch.object(positions, "_SNAPSHOT_PATH", cache),
                mock.patch.object(positions, "_tcp_port_open", return_value=False),
            ):
                snap = positions.read_positions({
                    "ibkr": {
                        "host": "127.0.0.1",
                        "ports": [65500],
                        "preflight_timeout": 0.01,
                    }
                })

        self.assertEqual(snap.source, "unavailable")
        self.assertIn("Could not connect to TWS", snap.error or "")

    def test_closed_ports_return_latest_snapshot_when_available(self):
        seed = PositionSnapshot(
            account_id="U_TEST",
            net_liq=123_456.0,
            gross_position_value=100_000.0,
            total_cash=23_456.0,
            unrealized_pnl=100.0,
            realized_pnl=50.0,
            sync_time="2026-06-04T00:00:00+00:00",
            source="tws",
        )

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "positions_cache.json"
            with mock.patch.object(positions, "_SNAPSHOT_PATH", cache):
                positions._save_snapshot(seed)
                with mock.patch.object(positions, "_tcp_port_open", return_value=False):
                    snap = positions.read_positions({"ibkr": {"ports": [65500]}})

        self.assertEqual(snap.source, "snapshot")
        self.assertEqual(snap.net_liq, 123_456.0)
        self.assertIn("Could not connect to TWS", snap.error or "")


if __name__ == "__main__":
    unittest.main()
