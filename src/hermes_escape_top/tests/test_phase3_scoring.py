from __future__ import annotations

import unittest
from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.registry import FactorContext
from hermes_escape_top.core.scoring.scorer import (
    build_registry,
    score_symbol,
    sell_fraction_for,
    status_from_score,
    weighted_percent_score,
)
from hermes_escape_top.pipeline import score_pipeline


DAY = date(2026, 5, 29)


def snap(symbol: str, values: dict[str, float | None]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        as_of=DAY,
        fields={name: Field(name=name, value=value, source="unit", as_of=DAY) for name, value in values.items()},
    )


def base_snapshots(close: float = 120.0) -> dict[str, SymbolSnapshot]:
    primary = {
        "close": close,
        "ma50": 115.0,
        "ma150": 105.0,
        "ma200": 100.0,
        "ma220": 98.0,
        "ema50": 112.0,
        "rsi14": 55.0,
        "drawdown_60d_high_pct": -0.05,
        "return_2d": 0.01,
        "distribution_days_25d": 2.0,
        "chandelier_exit": 90.0,
        "realized_vol20": 0.35,
    }
    return {
        "MSTR": snap("MSTR", primary),
        "QQQ": snap("QQQ", {"close": 450.0, "ma200": 400.0, "ema50": 430.0, "distribution_days_25d": 2.0}),
        "SPY": snap("SPY", {"close": 520.0, "ema50": 500.0}),
        "^VIX": snap("^VIX", {"close": 14.0}),
        "^VIX3M": snap("^VIX3M", {"close": 18.0}),
        "BTC-USD": snap("BTC-USD", {"close": 100000.0, "ma200": 80000.0}),
        "SOXX": snap("SOXX", {"close": 300.0, "ma200": 250.0, "ema50": 280.0}),
    }


class Phase3ScoringTest(unittest.TestCase):
    def test_c10_super_trend_factor_is_capped_at_ten(self) -> None:
        snapshots = base_snapshots(close=80.0)
        snapshots["MSTR"].fields["ema50"] = Field("ema50", 100.0, "unit", DAY)
        snapshots["MSTR"].fields["ma50"] = Field("ma50", 90.0, "unit", DAY)
        snapshots["MSTR"].fields["ma150"] = Field("ma150", 100.0, "unit", DAY)
        snapshots["MSTR"].fields["ma200"] = Field("ma200", 110.0, "unit", DAY)
        factors = build_registry("MSTR").evaluate(FactorContext(symbol="MSTR", snapshots=snapshots))
        c10 = next(factor for factor in factors if factor.factor_id == "C10_MACRO_TREND_STRUCTURE")
        self.assertEqual(c10.score, 10.0)

    def test_missing_critical_data_is_not_safe(self) -> None:
        config = load_config()
        snapshots = base_snapshots()
        snapshots["MSTR"].fields["close"] = Field("close", None, "unit", DAY)
        result = score_symbol("MSTR", snapshots, config).result
        self.assertEqual(result.final_score, 100.0)
        self.assertEqual(result.status, "EXIT")
        self.assertTrue(any("missing close" in item for item in result.explain))

    def test_status_and_sell_fraction_mapping(self) -> None:
        config = load_config()
        self.assertEqual(status_from_score(19.9, config), "HOLD")
        self.assertEqual(status_from_score(20.0, config), "WATCH")
        self.assertEqual(status_from_score(50.0, config), "REDUCE")
        self.assertAlmostEqual(sell_fraction_for("SOXL", "REDUCE", config), 0.60)
        self.assertAlmostEqual(sell_fraction_for("MSTR", "REDUCE", config), 0.50)

    def test_symbol_module_weighting_is_deterministic(self) -> None:
        config = load_config()
        modules = {"A": 10.0, "B": 5.0, "C": 20.0, "D": 5.0}
        first = weighted_percent_score("SOXL", modules, config)
        second = weighted_percent_score("SOXL", modules, config)
        self.assertEqual(first, second)
        self.assertGreater(first, 0)

    def test_phase3_score_pipeline_runs_all_trade_symbols(self) -> None:
        payload = score_pipeline("2026-05-29")
        self.assertEqual(payload["schema_version"], "escape-top-greenfield-phase3-score-v1")
        self.assertEqual(set(payload["scores"]), {"FNGU", "MSTR", "SOXL"})
        self.assertIn(payload["regime"]["current"], {"LOW_VOL_TREND", "CHOP", "HIGH_VOL", "CRISIS", "UNKNOWN"})
        for score in payload["scores"].values():
            self.assertIn(score["status"], {"HOLD", "WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"})
            self.assertIn("factor_scores", score)

    def test_price_core_gaps_are_wired_to_real_fields(self) -> None:
        payload = score_pipeline("2026-05-29")
        fngu = payload["scores"]["FNGU"]["factor_scores"]
        soxl = payload["scores"]["SOXL"]["factor_scores"]
        for factor in fngu["A"] + fngu["C"]:
            if factor["factor_id"] in {"A6_FUND_FLOW", "C7_AVWAP_PLATFORM_SUPPORT"}:
                self.assertEqual(factor["missing_fields"], [])
                self.assertGreater(factor["max_score"], 0)
        fngu_flow = next(factor for factor in fngu["D"] if factor["factor_id"] == "D_F4_COMPONENT_FLOW")
        soxl_flow = next(factor for factor in soxl["D"] if factor["factor_id"] == "D_S4_COMPONENT_FLOW")
        self.assertEqual(fngu_flow["missing_fields"], [])
        self.assertEqual(soxl_flow["missing_fields"], [])
        self.assertGreater(fngu_flow["max_score"], 0)
        self.assertGreater(soxl_flow["max_score"], 0)


if __name__ == "__main__":
    unittest.main()
