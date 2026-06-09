from __future__ import annotations

import unittest
from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.decision.verdict import VerdictInput, make_verdict
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves


def _mstr_snaps(*, close=90.0, ma200=80.0, r1=-0.16, r2=-0.10) -> dict[str, SymbolSnapshot]:
    """Defaults trigger ONLY H-M2: −16% day below EMA10, but close>MA200 (no H-M1),
    r2>−22% (no H-M3), BTC healthy (no H-M4), above chandelier (no H-M6)."""
    day = date(2026, 1, 2)
    return {
        "MSTR": SymbolSnapshot("MSTR", day, {
            "close": Field("close", close, "u", day),
            "ma200": Field("ma200", ma200, "u", day),
            "ema10": Field("ema10", 95.0, "u", day),
            "ema20": Field("ema20", 98.0, "u", day),
            "chandelier_exit": Field("chandelier_exit", 70.0, "u", day),
            "drawdown_60d_high_pct": Field("drawdown_60d_high_pct", -0.05, "u", day),
            "return_1d": Field("return_1d", r1, "u", day),
            "return_2d": Field("return_2d", r2, "u", day),
        }),
        "BTC-USD": SymbolSnapshot("BTC-USD", day, {
            "close": Field("close", 60000.0, "u", day), "ma50": Field("ma50", 55000.0, "u", day)}),
    }


class HM2BufferValveTest(unittest.TestCase):
    def test_lone_hm2_off_triggers_exit(self) -> None:
        r = evaluate_hard_valves("MSTR", _mstr_snaps(), hm2_buffer=False)
        self.assertTrue(r.triggered)
        self.assertEqual(r.ids, ["H-M2"])
        self.assertFalse(r.buffered)

    def test_lone_hm2_on_is_buffered_not_exit(self) -> None:
        r = evaluate_hard_valves("MSTR", _mstr_snaps(), hm2_buffer=True)
        self.assertFalse(r.triggered)
        self.assertEqual(r.ids, [])
        self.assertTrue(r.buffered)
        self.assertEqual(r.buffered_ids, ["H-M2"])
        self.assertEqual(r.buffer_status, "DEFENSIVE_EXIT")

    def test_hm2_with_companion_valve_still_exits(self) -> None:
        # close<=MA200 adds H-M1 → not a lone H-M2 → full EXIT even with buffer on.
        r = evaluate_hard_valves("MSTR", _mstr_snaps(close=70.0, ma200=80.0), hm2_buffer=True)
        self.assertTrue(r.triggered)
        self.assertIn("H-M1", r.ids)
        self.assertIn("H-M2", r.ids)
        self.assertFalse(r.buffered)


class HM2BufferVerdictTest(unittest.TestCase):
    def test_floor_applies_and_bypasses_confirmation(self) -> None:
        cfg = load_config()
        # Low score (would be HOLD) but buffered H-M2 floors to DEFENSIVE_EXIT now.
        v = make_verdict(
            VerdictInput(symbol="MSTR", score=10, module_scores={}, previous_status="HOLD",
                         hard_floor_status="DEFENSIVE_EXIT"),
            cfg,
        )
        self.assertEqual(v.status, "DEFENSIVE_EXIT")
        self.assertEqual(v.sell_fraction, 0.75)  # MSTR DEFENSIVE_EXIT
        self.assertFalse(v.confirmation_required)

    def test_no_floor_is_unchanged(self) -> None:
        cfg = load_config()
        v = make_verdict(VerdictInput(symbol="MSTR", score=10, module_scores={}), cfg)
        self.assertEqual(v.status, "HOLD")
        self.assertEqual(v.sell_fraction, 0.0)

    def test_floor_never_lowers_a_higher_status(self) -> None:
        cfg = load_config()
        # Score already EXIT (>=75); a DEFENSIVE_EXIT floor must not lower it.
        v = make_verdict(
            VerdictInput(symbol="MSTR", score=90, module_scores={}, hard_floor_status="DEFENSIVE_EXIT"),
            cfg,
        )
        self.assertEqual(v.status, "EXIT")


if __name__ == "__main__":
    unittest.main()
