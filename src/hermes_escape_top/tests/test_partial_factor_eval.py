from __future__ import annotations

import copy
import unittest
from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.scorer import build_registry
from hermes_escape_top.core.scoring.registry import FactorContext

FNGU_COMPONENTS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "NFLX", "AVGO"]


def _snapshots(drop_one: bool) -> dict[str, SymbolSnapshot]:
    day = date(2026, 1, 2)
    snaps: dict[str, SymbolSnapshot] = {
        "FNGU": SymbolSnapshot("FNGU", day, {"close": Field("close", 100.0, "u", day), "ma200": Field("ma200", 80.0, "u", day)}),
    }
    for i, c in enumerate(FNGU_COMPONENTS):
        if drop_one and c == "AVGO":
            # Missing one constituent entirely.
            continue
        # All constituents show severe outflow.
        snaps[c] = SymbolSnapshot(
            c, day,
            {
                "cmf20": Field("cmf20", -0.20, "u", day),
                "mfi14": Field("mfi14", 30.0, "u", day),
                "ad_slope20": Field("ad_slope20", -1.0, "u", day),
            },
        )
    return snaps


def _d_f4(snaps, config):
    factors = build_registry("FNGU", config).evaluate(FactorContext(symbol="FNGU", snapshots=snaps, config=config))
    return next(f for f in factors if f.factor_id == "D_F4_COMPONENT_FLOW")


class PartialFactorEvalTest(unittest.TestCase):
    def test_full_data_scores_either_way(self) -> None:
        for cfg in (load_config(), _on()):
            f = _d_f4(_snapshots(drop_one=False), cfg)
            self.assertEqual(f.score, 4.0)

    def test_missing_constituent_zeroes_when_off(self) -> None:
        f = _d_f4(_snapshots(drop_one=True), load_config())  # flag off
        self.assertEqual(f.score, 0.0)
        self.assertTrue(f.missing_fields)  # reported as missing (all-or-nothing)

    def test_missing_constituent_still_scores_when_on(self) -> None:
        f = _d_f4(_snapshots(drop_one=True), _on())
        # 8/9 constituents in severe outflow → factor still fires at full strength.
        self.assertEqual(f.score, 4.0)
        self.assertFalse(f.missing_fields)


def _on():
    cfg = copy.deepcopy(load_config())
    cfg["features"]["use_partial_factor_eval"] = True
    return cfg


if __name__ == "__main__":
    unittest.main()
