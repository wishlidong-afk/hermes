from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.mirror.store import write_mirror_snapshot
from hermes_escape_top.mirror.strategy import build_mirror_plan
from hermes_escape_top.pipeline import score_pipeline


DAY = date(2026, 5, 29)


def snap(symbol: str, values: dict[str, float]) -> SymbolSnapshot:
    return SymbolSnapshot(symbol, DAY, {name: Field(name, value, "unit", DAY) for name, value in values.items()})


class Phase12MirrorTest(unittest.TestCase):
    def test_mirror_selects_risk_on_for_q_policy(self) -> None:
        snapshots = {
            "QQQ": snap("QQQ", {"close": 120, "ema20": 110, "ma200": 100}),
            "SOXX": snap("SOXX", {"close": 120, "ema20": 110, "ma200": 100}),
            "MSTR": snap("MSTR", {"close": 120, "ma200": 100}),
            "BTC-USD": snap("BTC-USD", {"close": 120, "ma200": 100}),
        }
        plan = build_mirror_plan(snapshots, {})
        self.assertEqual(plan["FNGU_QQQ"].selected_symbol, "FNGU")
        self.assertEqual(plan["SOXL_SOXX"].selected_symbol, "SOXL")
        self.assertEqual(plan["MSTR_QQQ"].selected_symbol, "MSTR")

    def test_mirror_store_writes_sqlite_snapshot(self) -> None:
        snapshots = {
            "QQQ": snap("QQQ", {"close": 90, "ema20": 100, "ma200": 110}),
            "SOXX": snap("SOXX", {"close": 90, "ema20": 100, "ma200": 110}),
            "MSTR": snap("MSTR", {"close": 90, "ma200": 110}),
        }
        plan = build_mirror_plan(snapshots, {})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_mirror_snapshot(Path(tmp) / "mirror.sqlite", "2026-05-29", plan)
            with sqlite3.connect(path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM mirror_snapshots").fetchone()[0]
            self.assertEqual(count, 3)

    def test_score_pipeline_includes_mirror(self) -> None:
        payload = score_pipeline("2026-05-29")
        self.assertIn("mirror", payload)
        self.assertEqual(set(payload["mirror"]["decisions"]), {"FNGU_QQQ", "MSTR_QQQ", "SOXL_SOXX"})


if __name__ == "__main__":
    unittest.main()
