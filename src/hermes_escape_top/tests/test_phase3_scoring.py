from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.decision.action_intents import build_action_context
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


def confidence_snapshots() -> dict[str, SymbolSnapshot]:
    snapshots = base_snapshots()
    snapshots["FNGU"] = snap(
        "FNGU",
        {
            "close": 120.0,
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
            "avwap_anchored_20d": 110.0,
            "support_20d_low": 108.0,
        },
    )
    snapshots["QQQ"] = snap(
        "QQQ",
        {
            "close": 450.0,
            "ma200": 400.0,
            "ema20": 440.0,
            "ema50": 430.0,
            "rsi14": 55.0,
            "cmf20": 0.05,
            "mfi14": 60.0,
            "ad_slope20": 1.0,
            "distribution_days_25d": 2.0,
        },
    )
    snapshots["SPY"] = snap("SPY", {"close": 520.0, "ema50": 500.0, "distribution_days_25d": 2.0})
    snapshots["^VIX3M"] = snap("^VIX3M", {"close": 18.0})
    snapshots["SOFT"] = snap(
        "SOFT",
        {
            "aaii_bull_bear_spread": 0.0,
            "aaii_bull_pctl": 50.0,
            "naaim_exposure": 50.0,
            "naaim_pctl": 50.0,
            "equity_pcr": 0.8,
            "equity_pcr_pctl": 50.0,
            "aggregate_pct_above_50dma": 0.5,
            "aggregate_pct_above_200dma": 0.5,
            "aggregate_breadth_chg_5d": 0.0,
            "net_liq_chg10_pctl": 50.0,
            "vvix_pctl": 50.0,
            "skew_index": 140.0,
            "skew_pctl": 50.0,
            # Enabled risk factors (A10/A11/A15) — neutral so only B6 valuation is missing.
            "real_rate_10y_pctl": 50.0,
            "dollar_broad_pctl": 50.0,
            "defensive_cyclical_pctl": 50.0,
        },
    )
    for component in ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "NFLX", "AVGO"]:
        snapshots[component] = snap(component, {"cmf20": 0.05, "mfi14": 60.0, "ad_slope20": 1.0})
    return snapshots


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
        # Legacy path (flag OFF, pinned explicitly so the deployed default doesn't
        # change the assertion): missing critical data must NOT read as safe — the
        # old behavior escalates to a (fake) 100/EXIT. The deployed default now uses
        # NO_ADVICE instead (test_no_advice_is_noop_on_complete_data_and_safe_on_missing).
        config = load_config()
        off = {**config, "features": {**config.get("features", {}), "use_no_advice_state": False}}
        snapshots = base_snapshots()
        snapshots["MSTR"].fields["close"] = Field("close", None, "unit", DAY)
        result = score_symbol("MSTR", snapshots, off).result
        self.assertEqual(result.final_score, 100.0)
        self.assertEqual(result.status, "EXIT")
        self.assertTrue(any("missing close" in item for item in result.explain))

    def test_no_advice_is_noop_on_complete_data_and_safe_on_missing(self) -> None:
        config = load_config()
        on = {**config, "features": {**config.get("features", {}), "use_no_advice_state": True}}
        off = {**config, "features": {**config.get("features", {}), "use_no_advice_state": False}}

        # 1. Complete data: flag ON == flag OFF. NO_ADVICE only fires on critical
        #    missing, which never happens on complete data — this is WHY enabling
        #    the flag cannot change live advice (proven no-op).
        snaps = base_snapshots()
        r_on = score_symbol("MSTR", snaps, on).result
        r_off = score_symbol("MSTR", snaps, off).result
        self.assertEqual((r_on.status, r_on.final_score, r_on.sell_fraction),
                         (r_off.status, r_off.final_score, r_off.sell_fraction))

        # 2. Critical field missing + flag ON -> NO_ADVICE / sell 0 / no hard valves,
        #    instead of the dangerous fake-100 EXIT that flag OFF produces above.
        bad = base_snapshots()
        bad["MSTR"].fields["close"] = Field("close", None, "unit", DAY)
        r_bad = score_symbol("MSTR", bad, on).result
        self.assertEqual(r_bad.status, "NO_ADVICE")
        self.assertEqual(r_bad.sell_fraction, 0.0)
        self.assertEqual(list(r_bad.hard_valve_hits), [])

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
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        self.assertEqual(payload["schema_version"], "escape-top-greenfield-phase3-score-v1")
        self.assertEqual(set(payload["scores"]), {"FNGU", "MSTR", "SOXL"})
        self.assertIn(payload["regime"]["current"], {"LOW_VOL_TREND", "CHOP", "HIGH_VOL", "CRISIS", "UNKNOWN"})
        self.assertIn("flow", payload)
        self.assertIn("FNGU", payload["flow"]["component_baskets"])
        self.assertIn("SOXL", payload["flow"]["component_baskets"])
        for score in payload["scores"].values():
            self.assertIn(score["status"], {"HOLD", "WATCH", "TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"})
            self.assertIn("factor_scores", score)

    def test_price_core_gaps_are_wired_to_real_fields(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
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

    def test_missing_b6_valuation_counts_as_blind_spot_weight(self) -> None:
        config = load_config()
        snapshots = base_snapshots()
        result = score_symbol("MSTR", snapshots, config).result
        b6 = next(factor for factor in result.factor_scores["B"] if factor["factor_id"] == "B6_VALUATION_HEAT")
        self.assertEqual(b6["missing_fields"], ["B6 valuation"])
        self.assertGreaterEqual(result.missing_weight, config["missing"]["weights"]["B6 valuation"])

    def test_action_confidence_missing_weight_excludes_non_scoring_placeholders(self) -> None:
        config = load_config()
        config["features"]["use_scored_missing_weight"] = False  # assert the full-vs-confidence split
        result = score_symbol("FNGU", confidence_snapshots(), config).result
        self.assertIn("B6 valuation", result.confidence_missing_fields)
        self.assertNotIn("A2 cnn_fear_greed", result.confidence_missing_fields)
        self.assertNotIn("B5 social", result.confidence_missing_fields)
        self.assertIn("A2 cnn_fear_greed", result.non_scoring_missing_fields)
        self.assertIn("B5 social", result.non_scoring_missing_fields)
        self.assertEqual(result.confidence_missing_weight, config["missing"]["weights"]["B6 valuation"])
        self.assertGreater(result.missing_weight, result.confidence_missing_weight)

    def test_action_layer_can_reach_high_with_only_scored_missing_weight(self) -> None:
        snapshots = confidence_snapshots()
        payload = {
            "posterior_pnl": {"portfolio_value": 100000},
            "data_quality": {"overall_score": 92.55},
            "ibkr": {"source": "tws", "snapshot_stale": False},
            "scores": {
                "FNGU": {
                    "final_score": 20,
                    "status": "WATCH",
                    "sell_fraction": 0,
                    "hard_valve_hits": [],
                    "missing_weight": 11,
                    "confidence_missing_weight": 5,
                    "confidence_missing_fields": ["B6 valuation"],
                    "non_scoring_missing_weight": 6,
                    "non_scoring_missing_fields": ["A2 cnn_fear_greed", "B5 social"],
                    "module_scores": {},
                    "factor_scores": {},
                }
            },
            "sizing": {"FNGU": {"sleeve_cap": 0.2, "target_weight": 0.2}},
            "routing": {"FNGU": {"applies": False}},
            "reentry": {"FNGU": {}},
        }
        context = build_action_context(payload, snapshots)
        confidence = context["decision_layers"]["FNGU"]["action_confidence"]
        self.assertEqual(confidence["level"], "HIGH")
        self.assertEqual(confidence["score"], 87.55)
        self.assertEqual(confidence["scored_missing_weight"], 5)
        self.assertEqual(confidence["non_scoring_missing_weight"], 6)


if __name__ == "__main__":
    unittest.main()
