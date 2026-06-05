from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves
from hermes_escape_top.pipeline import score_pipeline


DAY = date(2026, 5, 29)


def snap(symbol: str, values: dict[str, float | None]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        as_of=DAY,
        fields={name: Field(name=name, value=value, source="unit", as_of=DAY) for name, value in values.items()},
    )


def clean_snapshots() -> dict[str, SymbolSnapshot]:
    return {
        "SOXL": snap(
            "SOXL",
            {
                "close": 120.0,
                "ma200": 100.0,
                "ema10": 118.0,
                "ema20": 115.0,
                "ema50": 110.0,
                "chandelier_exit": 90.0,
                "drawdown_60d_high_pct": -0.02,
                "return_1d": 0.01,
                "return_2d": 0.02,
            },
        ),
        "FNGU": snap(
            "FNGU",
            {
                "close": 90.0,
                "ma200": 80.0,
                "ema10": 88.0,
                "ema20": 86.0,
                "ema50": 84.0,
                "chandelier_exit": 70.0,
                "drawdown_60d_high_pct": -0.02,
                "return_1d": 0.01,
                "return_2d": 0.02,
            },
        ),
        "QQQ": snap("QQQ", {"close": 450.0, "ma200": 400.0, "ema50": 430.0, "distribution_days_25d": 2.0}),
        "SOXX": snap("SOXX", {"close": 300.0, "ma200": 250.0, "ema50": 280.0}),
        "FNGS": snap("FNGS", {"close": 75.0, "ma200": 60.0, "ema50": 70.0}),
        "^VIX": snap("^VIX", {"close": 14.0}),
        "^VIX3M": snap("^VIX3M", {"close": 18.0}),
    }


class Phase4HardValveTest(unittest.TestCase):
    def test_historical_mstr_hard_valves_match_known_family(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        mstr = payload["scores"]["MSTR"]
        self.assertEqual(mstr["status"], "EXIT")
        self.assertEqual(mstr["sell_fraction"], 1.0)
        self.assertIn("H-M1", mstr["hard_valve_hits"])
        self.assertIn("H-M4", mstr["hard_valve_hits"])

    def test_clean_uptrend_does_not_trigger_soxl_hard_valves(self) -> None:
        result = evaluate_hard_valves("SOXL", clean_snapshots())
        self.assertFalse(result.triggered)
        self.assertEqual(result.ids, [])

    def test_soxl_peak_trailing_damage_triggers_hs6(self) -> None:
        snapshots = clean_snapshots()
        snapshots["SOXL"].fields["close"] = Field("close", 70.0, "unit", DAY)
        snapshots["SOXL"].fields["ema50"] = Field("ema50", 80.0, "unit", DAY)
        snapshots["SOXL"].fields["drawdown_60d_high_pct"] = Field("drawdown_60d_high_pct", -0.26, "unit", DAY)
        result = evaluate_hard_valves("SOXL", snapshots)
        self.assertTrue(result.triggered)
        self.assertIn("H-S6", result.ids)

    def test_fngu_qqq_ma200_break_triggers_hf1(self) -> None:
        snapshots = clean_snapshots()
        snapshots["QQQ"].fields["close"] = Field("close", 390.0, "unit", DAY)
        snapshots["QQQ"].fields["ma200"] = Field("ma200", 400.0, "unit", DAY)
        result = evaluate_hard_valves("FNGU", snapshots)
        self.assertTrue(result.triggered)
        self.assertIn("H-F1", result.ids)


if __name__ == "__main__":
    unittest.main()
