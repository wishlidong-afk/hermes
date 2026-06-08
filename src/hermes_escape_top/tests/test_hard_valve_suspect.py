from __future__ import annotations

import unittest
from datetime import date

from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves


def _mstr_break_snapshots() -> dict[str, SymbolSnapshot]:
    """MSTR close <= MA200 → H-M1 would fire."""
    day = date(2026, 1, 2)
    return {
        "MSTR": SymbolSnapshot(
            "MSTR",
            day,
            {
                "close": Field("close", 90.0, "unit", day),
                "ma200": Field("ma200", 100.0, "unit", day),
                "ema10": Field("ema10", 95.0, "unit", day),
                "ema20": Field("ema20", 98.0, "unit", day),
                "chandelier_exit": Field("chandelier_exit", 105.0, "unit", day),
                "drawdown_60d_high_pct": Field("drawdown_60d_high_pct", -0.05, "unit", day),
                "return_1d": Field("return_1d", -0.02, "unit", day),
                "return_2d": Field("return_2d", -0.03, "unit", day),
            },
        ),
        "BTC-USD": SymbolSnapshot(
            "BTC-USD",
            day,
            {"close": Field("close", 60000.0, "unit", day), "ma50": Field("ma50", 55000.0, "unit", day)},
        ),
    }


class HardValveSuspectTest(unittest.TestCase):
    def test_clean_bar_triggers_hard_valve(self) -> None:
        result = evaluate_hard_valves("MSTR", _mstr_break_snapshots(), suspect=False)
        self.assertTrue(result.triggered)
        self.assertIn("H-M1", result.ids)
        self.assertFalse(result.pending)
        self.assertEqual(result.pending_ids, [])

    def test_suspect_bar_holds_valve_pending(self) -> None:
        result = evaluate_hard_valves("MSTR", _mstr_break_snapshots(), suspect=True)
        # Held pending: must NOT force EXIT (triggered/ids drive the 100% liquidation).
        self.assertFalse(result.triggered)
        self.assertEqual(result.ids, [])
        # But the would-be trigger is recorded for explainability.
        self.assertTrue(result.pending)
        self.assertIn("H-M1", result.pending_ids)
        self.assertIn("suspect bar", result.pending_reason)

    def test_default_is_clean_behaviour(self) -> None:
        """Omitting `suspect` must be byte-identical to the prior behaviour."""
        default = evaluate_hard_valves("MSTR", _mstr_break_snapshots())
        explicit = evaluate_hard_valves("MSTR", _mstr_break_snapshots(), suspect=False)
        self.assertEqual(default.triggered, explicit.triggered)
        self.assertEqual(default.ids, explicit.ids)


if __name__ == "__main__":
    unittest.main()
