from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.reentry.plan import build_reentry_plan
from hermes_escape_top.core.scoring.result import ScoreResult
from hermes_escape_top.pipeline import score_pipeline


DAY = date(2026, 5, 29)


def snap(symbol: str, values: dict[str, float]) -> SymbolSnapshot:
    return SymbolSnapshot(symbol, DAY, {name: Field(name, value, "unit", DAY) for name, value in values.items()})


def history(start: float = 100.0, periods: int = 280) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=periods)
    close = pd.Series([start + i * 0.1 for i in range(periods)], index=dates)
    return pd.DataFrame({"Close": close, "Open": close, "High": close + 1, "Low": close - 1, "Volume": 1_000_000}, index=dates)


def safe_score(symbol: str = "SOXL") -> ScoreResult:
    return ScoreResult(symbol=symbol, as_of=DAY, final_score=10.0, module_scores={"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}, status="HOLD")


class Phase9ReentryTest(unittest.TestCase):
    def test_time_lock_blocks_reentry(self) -> None:
        config = load_config()
        plan = build_reentry_plan("SOXL", safe_score(), {}, {}, config, days_since_last_sell=5)
        self.assertFalse(plan.eligible)
        self.assertEqual(plan.locked_reason, "time_lock")

    def test_t1_reentry_unlocks_after_three_locks_clear(self) -> None:
        config = load_config()
        snapshots = {"SOXX": snap("SOXX", {"close": 101.0, "ema20": 100.0, "macd": 0.2, "macd_signal": 0.1})}
        plan = build_reentry_plan("SOXL", safe_score(), snapshots, {}, config, days_since_last_sell=11)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.tranche, "T1")
        self.assertAlmostEqual(plan.allocation_fraction, 0.30)

    def test_t2_requires_prior_high_break(self) -> None:
        config = load_config()
        frame = history(start=80.0, periods=40)
        snapshots = {"SOXX": snap("SOXX", {"close": 200.0, "ema20": 100.0, "macd": 0.2, "macd_signal": 0.1})}
        plan = build_reentry_plan("SOXL", safe_score(), snapshots, {"SOXX": frame}, config, days_since_last_sell=11, t1_active=True)
        self.assertTrue(plan.eligible)
        self.assertEqual(plan.tranche, "T2")

    def test_pipeline_includes_reentry_block(self) -> None:
        payload = score_pipeline("2026-05-29")
        self.assertEqual(set(payload["reentry"]), {"FNGU", "MSTR", "SOXL"})
        self.assertEqual(payload["reentry"]["MSTR"]["eligible"], False)


if __name__ == "__main__":
    unittest.main()
