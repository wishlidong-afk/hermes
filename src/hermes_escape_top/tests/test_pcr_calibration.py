from __future__ import annotations

import copy
import unittest
from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.module_a import _equity_pcr_pressure
from hermes_escape_top.core.scoring.registry import FactorContext


def _ctx(pctl: float, config) -> FactorContext:
    day = date(2026, 1, 2)
    snaps = {
        "MSTR": SymbolSnapshot("MSTR", day, {"close": Field("close", 100.0, "u", day)}),
        "SOFT": SymbolSnapshot(
            "SOFT",
            day,
            {
                "equity_pcr": Field("equity_pcr", 0.90, "u", day),  # high pcr → only pctl drives
                "equity_pcr_pctl": Field("equity_pcr_pctl", pctl, "u", day),
            },
        ),
    }
    return FactorContext(symbol="MSTR", snapshots=snaps, config=config)


class PcrCalibrationTest(unittest.TestCase):
    def test_default_thresholds_byte_identical(self) -> None:
        cfg = load_config()
        # pctl 15 is <=20 (default score1) but >12 → score 1 under defaults.
        score, _ = _equity_pcr_pressure(_ctx(15.0, cfg))
        self.assertEqual(score, 1.0)

    def test_tightened_config_suppresses_marginal_signal(self) -> None:
        cfg = copy.deepcopy(load_config())
        cfg["pcr"] = {"score2_pcr": 0.52, "score2_pctl": 8, "score1_pcr": 0.58, "score1_pctl": 12}
        # pctl 15 no longer clears the tightened score1 (<=12) → score 0.
        score, _ = _equity_pcr_pressure(_ctx(15.0, cfg))
        self.assertEqual(score, 0.0)
        # Deep tail still fires.
        score_tail, _ = _equity_pcr_pressure(_ctx(6.0, cfg))
        self.assertEqual(score_tail, 2.0)


if __name__ == "__main__":
    unittest.main()
