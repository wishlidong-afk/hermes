from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.backtest.snapshot import build_snapshot
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves


class HardValveHistoryTest(unittest.TestCase):
    def test_mstr_2022_ma200_break_triggers_h_m1(self) -> None:
        cfg = load_config()
        store = LocalStore(cfg)
        day = "2022-01-03"
        snapshots = build_snapshot(day, store=store, cfg=cfg)
        histories = {symbol: store.load_history(symbol).loc[: pd.Timestamp(day)] for symbol in ["MSTR", "BTC-USD"]}
        result = evaluate_hard_valves("MSTR", snapshots, histories=histories)
        self.assertTrue(result.triggered)
        self.assertIn("H-M1", result.ids)

    def test_soxl_2022_semiconductor_break_triggers_h_s1_h_s2(self) -> None:
        cfg = load_config()
        store = LocalStore(cfg)
        day = "2022-01-25"
        snapshots = build_snapshot(day, store=store, cfg=cfg)
        histories = {symbol: store.load_history(symbol).loc[: pd.Timestamp(day)] for symbol in ["SOXL", "QQQ", "SOXX", "SMH", "^SOX"]}
        result = evaluate_hard_valves("SOXL", snapshots, histories=histories)
        self.assertTrue(result.triggered)
        self.assertIn("H-S1", result.ids)
        self.assertIn("H-S2", result.ids)

    def test_clean_synthetic_uptrend_has_no_hard_valves(self) -> None:
        day = date(2026, 1, 2)
        snapshots = {
            "SOXL": SymbolSnapshot(
                "SOXL",
                day,
                {
                    "close": Field("close", 120.0, "unit", day),
                    "ma200": Field("ma200", 100.0, "unit", day),
                    "ema20": Field("ema20", 115.0, "unit", day),
                    "ema50": Field("ema50", 110.0, "unit", day),
                    "chandelier_exit": Field("chandelier_exit", 90.0, "unit", day),
                    "drawdown_60d_high_pct": Field("drawdown_60d_high_pct", -0.02, "unit", day),
                    "return_1d": Field("return_1d", 0.01, "unit", day),
                    "return_2d": Field("return_2d", 0.02, "unit", day),
                },
            ),
            "QQQ": SymbolSnapshot("QQQ", day, {"close": Field("close", 500.0, "unit", day), "ma200": Field("ma200", 450.0, "unit", day)}),
            "SOXX": SymbolSnapshot(
                "SOXX",
                day,
                {
                    "close": Field("close", 300.0, "unit", day),
                    "ma200": Field("ma200", 250.0, "unit", day),
                    "ema50": Field("ema50", 280.0, "unit", day),
                },
            ),
        }
        result = evaluate_hard_valves("SOXL", snapshots, histories={})
        self.assertFalse(result.triggered)


if __name__ == "__main__":
    unittest.main()
