"""Tests for Reentry State Tracker -- 3-3-4 tranche persistence."""

from __future__ import annotations

import json
import unittest
from datetime import date

from hermes_escape_top.core.reentry.tracker import (
    LockCheck,
    TrancheState,
    advance_tranche,
    check_three_locks,
    deserialize_states,
    serialize_states,
)


def _base_cfg() -> dict:
    return {"reentry_time_lock_days": 11, "reentry_sentiment_threshold": 19, "reentry_c_threshold": 5}


class TestThreeLocks(unittest.TestCase):
    def test_all_clear(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-05-01")
        lc = check_three_locks(state, date(2026, 5, 20), total_score=10, c_score=3,
                               divergence_active=False, has_sell_signal=False, has_hard_valve=False, cfg=_base_cfg())
        self.assertTrue(lc.all_clear)

    def test_time_lock_blocks(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-05-28")
        lc = check_three_locks(state, date(2026, 6, 1), total_score=10, c_score=3,
                               divergence_active=False, has_sell_signal=False, has_hard_valve=False, cfg=_base_cfg())
        self.assertFalse(lc.time_lock_clear)
        self.assertFalse(lc.all_clear)

    def test_sentiment_lock_blocks(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-04-01")
        lc = check_three_locks(state, date(2026, 6, 1), total_score=25, c_score=3,
                               divergence_active=False, has_sell_signal=False, has_hard_valve=False, cfg=_base_cfg())
        self.assertFalse(lc.sentiment_lock_clear)

    def test_structure_lock_blocks(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-04-01")
        lc = check_three_locks(state, date(2026, 6, 1), total_score=10, c_score=8,
                               divergence_active=False, has_sell_signal=False, has_hard_valve=False, cfg=_base_cfg())
        self.assertFalse(lc.structure_lock_clear)

    def test_hard_valve_forces_lock(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-04-01")
        lc = check_three_locks(state, date(2026, 6, 1), total_score=5, c_score=1,
                               divergence_active=False, has_sell_signal=False, has_hard_valve=True, cfg=_base_cfg())
        self.assertFalse(lc.all_clear)

    def test_sell_signal_forces_lock(self) -> None:
        state = TrancheState("MSTR", "LOCKED", last_sell_date="2026-04-01")
        lc = check_three_locks(state, date(2026, 6, 1), total_score=5, c_score=1,
                               divergence_active=False, has_sell_signal=True, has_hard_valve=False, cfg=_base_cfg())
        self.assertFalse(lc.all_clear)


class TestAdvanceTranche(unittest.TestCase):
    def _cleared_lock(self) -> "LockCheck":
        return LockCheck(True, True, True, True, [])

    def _locked(self) -> "LockCheck":
        return LockCheck(False, False, False, False, ["forced lock"])

    def test_locked_stays_locked(self) -> None:
        state = TrancheState("MSTR", "LOCKED")
        new = advance_tranche(state, self._locked(), date(2026, 6, 1),
                              radar_price=400, radar_ema20=390, radar_macd_cross=True,
                              radar_20d_high=410, benchmark_new_high=False, cfg={})
        self.assertEqual(new.phase, "LOCKED")

    def test_t1_activates(self) -> None:
        state = TrancheState("MSTR", "LOCKED")
        new = advance_tranche(state, self._cleared_lock(), date(2026, 6, 1),
                              radar_price=400, radar_ema20=390, radar_macd_cross=True,
                              radar_20d_high=410, benchmark_new_high=False, cfg={})
        self.assertEqual(new.phase, "T1_ACTIVE")
        self.assertEqual(new.t1_entry_price, 400)

    def test_t2_activates(self) -> None:
        state = TrancheState("MSTR", "T1_ACTIVE", t1_entry_price=380.0, t1_entry_date="2026-05-20")
        new = advance_tranche(state, self._cleared_lock(), date(2026, 6, 1),
                              radar_price=420, radar_ema20=400, radar_macd_cross=True,
                              radar_20d_high=415, benchmark_new_high=False, cfg={})
        self.assertEqual(new.phase, "T2_ACTIVE")
        self.assertEqual(new.t2_entry_price, 420)

    def test_t3_needs_benchmark(self) -> None:
        state = TrancheState("MSTR", "T2_ACTIVE", t1_entry_price=380.0, t2_entry_price=410.0)
        new = advance_tranche(state, self._cleared_lock(), date(2026, 6, 1),
                              radar_price=430, radar_ema20=410, radar_macd_cross=True,
                              radar_20d_high=425, benchmark_new_high=False, cfg={})
        self.assertEqual(new.phase, "T2_ACTIVE")  # no benchmark high → stays T2

    def test_t3_activates_with_benchmark(self) -> None:
        state = TrancheState("MSTR", "T2_ACTIVE", t1_entry_price=380.0, t2_entry_price=410.0)
        new = advance_tranche(state, self._cleared_lock(), date(2026, 6, 1),
                              radar_price=430, radar_ema20=410, radar_macd_cross=True,
                              radar_20d_high=425, benchmark_new_high=True, cfg={})
        self.assertEqual(new.phase, "T3_ACTIVE")


class TestSerialization(unittest.TestCase):
    def test_round_trip(self) -> None:
        states = {
            "MSTR": TrancheState("MSTR", "T1_ACTIVE", t1_entry_date="2026-05-20", t1_entry_price=400.0),
            "FNGU": TrancheState("FNGU", "LOCKED", last_sell_date="2026-05-15"),
        }
        data = serialize_states(states)
        restored = deserialize_states(data)
        self.assertEqual(restored["MSTR"].phase, "T1_ACTIVE")
        self.assertEqual(restored["MSTR"].t1_entry_price, 400.0)
        self.assertEqual(restored["FNGU"].phase, "LOCKED")

    def test_valid_json(self) -> None:
        states = {"X": TrancheState("X", "LOCKED")}
        data = serialize_states(states)
        parsed = json.loads(data)
        self.assertIn("X", parsed)


if __name__ == "__main__":
    unittest.main()
