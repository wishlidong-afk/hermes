from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

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
            "MSTR": snap("MSTR", {"close": 130, "ema20": 120, "ema50": 112, "ma200": 100, "rsi14": 60, "macd": 2, "macd_signal": 1}),
            "BTC-USD": snap("BTC-USD", {"close": 130, "ma200": 100}),
            "QQQ": snap("QQQ", {"close": 120, "ema20": 112, "ema50": 108, "rsi14": 60, "macd": 2, "macd_signal": 1}),
            "SOXX": snap("SOXX", {"close": 120, "ema50": 110, "ma200": 100, "rsi14": 60, "macd": 2, "macd_signal": 1}),
            "^VIX": snap("^VIX", {"close": 18}),
        }
        plan = build_mirror_plan(snapshots, {})
        self.assertEqual(plan["MSTR_QQQ"].selected_symbol, "MSTR")
        self.assertEqual(plan["FNGU_QQQ"].selected_symbol, "FNGU")
        self.assertEqual(plan["SOXL_SOXX"].selected_symbol, "SOXL")
        self.assertIn("MSTR", plan["MSTR_QQQ"].allocations)
        self.assertIn("QQQ", plan["FNGU_QQQ"].allocations)
        self.assertIn("SOXX", plan["SOXL_SOXX"].allocations)

    def test_mirror_store_writes_sqlite_snapshot(self) -> None:
        snapshots = {
            "MSTR": snap("MSTR", {"close": 80, "ema20": 100, "ema50": 105, "ma200": 110, "rsi14": 55, "macd": -1, "macd_signal": 0}),
            "BTC-USD": snap("BTC-USD", {"close": 90, "ma200": 100}),
            "QQQ": snap("QQQ", {"close": 90, "ema20": 100, "ema50": 105, "rsi14": 55, "macd": -1, "macd_signal": 0}),
            "SOXX": snap("SOXX", {"close": 90, "ema50": 100, "ma200": 110, "rsi14": 55, "macd": -1, "macd_signal": 0}),
            "^VIX": snap("^VIX", {"close": 18}),
        }
        plan = build_mirror_plan(snapshots, {})
        with tempfile.TemporaryDirectory() as tmp:
            path = write_mirror_snapshot(Path(tmp) / "mirror.sqlite", "2026-05-29", plan)
            with sqlite3.connect(path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM mirror_snapshots").fetchone()[0]
            self.assertEqual(count, 3)

    def test_score_pipeline_includes_mirror(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        self.assertIn("mirror", payload)
        self.assertEqual(set(payload["mirror"]["decisions"]), {"MSTR_QQQ", "FNGU_QQQ", "SOXL_SOXX"})


if __name__ == "__main__":
    unittest.main()
