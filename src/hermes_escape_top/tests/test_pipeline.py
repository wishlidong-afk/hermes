"""Tests for Unified Pipeline -- end-to-end integration.

Validates:
  1. Pipeline runs end-to-end with defaults
  2. R3 invariant holds through full pipeline
  3. Confidence degradation propagates to sizing
  4. Hard valve → execute_now in execution plan
  5. Audit log completeness
  6. Deterministic: same input → same output
  7. Empty/missing data → graceful fallback
  8. All 7 system gates have structural support
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hermes_escape_top.core.research.integration_pipeline import PipelineResult, score_pipeline
from hermes_escape_top.core.contracts import Verdict


def _make_store(n: int = 300, symbols: list = None) -> dict:
    if symbols is None:
        symbols = ["MSTR", "FNGU", "SOXL", "QQQ", "^VIX"]
    rng = np.random.RandomState(42)
    dates = pd.bdate_range("2020-01-01", periods=n)
    store = {}
    for sym in symbols:
        price = 100 * np.exp(np.cumsum(rng.randn(n) * 0.015))
        store[sym] = pd.DataFrame({
            "open": price * (1 + rng.randn(n) * 0.003),
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price,
            "volume": (rng.rand(n) * 1e6 + 5e4).astype(int),
        }, index=dates)
    return store


def _base_cfg() -> dict:
    return {
        "symbols": ["MSTR", "FNGU", "SOXL"],
        "sleeve_caps": {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30},
        "thresholds": {"exit": 75, "defensive_exit": 65, "reduce": 50, "trim": 35, "watch": 20},
        "risk_engine": {
            "min_periods": 40,
            "ewma_lambda": 0.94,
            "vol_budget_annual": 0.35,
            "cvar_budget": 0.08,
            "extreme_corr_penalty": 0.70,
            "downside_q": 0.10,
            "cvar_alpha": 0.95,
        },
        "sizing": {
            "dd_aversion": 3.0,
            "leverage_L": {"MSTR": 1.0, "FNGU": 3.0, "SOXL": 3.0},
            "solver": "slsqp_or_grid",
            "exec_slices": 3,
        },
        "confidence": {
            "tau_stale": 3,
            "weakest_weight": 0.60,
            "normal_threshold": 0.80,
            "caution_threshold": 0.55,
        },
        "governance": {"disagreement_threshold": 0.40},
    }


class TestPipelineEndToEnd(unittest.TestCase):
    def test_runs_with_defaults(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIsInstance(result, PipelineResult)
        self.assertEqual(len(result.symbols), 3)
        self.assertIn("MSTR", result.verdicts)
        self.assertIsNotNone(result.risk_state)
        self.assertIsNotNone(result.confidence)
        self.assertIsNotNone(result.sizing)

    def test_r3_invariant(self) -> None:
        """w_i <= rule_target_weight for ALL symbols, ALWAYS."""
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        for sym, w in result.sizing.target_weights.items():
            rule = result.verdicts[sym].rule_target_weight
            self.assertLessEqual(w, rule + 1e-6, f"R3 violated: {sym} w={w} > rule={rule}")

    def test_deterministic(self) -> None:
        store = _make_store()
        cfg = _base_cfg()
        r1 = score_pipeline("2021-01-15", store, cfg)
        r2 = score_pipeline("2021-01-15", store, cfg)
        self.assertEqual(r1.sizing.target_weights, r2.sizing.target_weights)
        self.assertEqual(r1.confidence.decision_confidence, r2.confidence.decision_confidence)
        self.assertEqual(r1.confidence.mode, r2.confidence.mode)


class TestPipelineConfidence(unittest.TestCase):
    def test_confidence_propagates_to_sizing(self) -> None:
        store = _make_store()
        cfg = _base_cfg()
        result = score_pipeline("2021-01-15", store, cfg)
        self.assertEqual(result.sizing.confidence_applied, round(result.confidence.decision_confidence, 6))


class TestPipelineAudit(unittest.TestCase):
    def test_audit_complete(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        audit = result.audit
        self.assertIn("as_of", audit)
        self.assertIn("scores_summary", audit)
        self.assertIn("verdicts_summary", audit)
        self.assertIn("risk_summary", audit)
        self.assertIn("confidence", audit)
        self.assertIn("sizing_summary", audit)
        self.assertIn("regime", audit)
        self.assertIn("fragility", audit)
        self.assertIn("disagreement", audit)
        self.assertIn("drift", audit)

    def test_audit_reproducible_fields(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertEqual(result.audit["as_of"], "2021-01-15")
        for sym in result.symbols:
            self.assertIn(sym, result.audit["scores_summary"])


class TestPipelineEdgeCases(unittest.TestCase):
    def test_empty_store(self) -> None:
        result = score_pipeline("2021-01-15", {}, _base_cfg())
        self.assertIsInstance(result, PipelineResult)

    def test_missing_symbol(self) -> None:
        store = _make_store(symbols=["MSTR"])
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIsInstance(result, PipelineResult)

    def test_custom_scorer(self) -> None:
        def custom_scorer(sym, store, ctx, cfg):
            return {"A": 15, "B": 20, "C": 30, "D": 15, "total": 80, "missing_weight": 5}

        def custom_verdict(sym, score, store, cfg):
            return Verdict(sym, "EXIT", 0.0, 1.0, hard_valve_hits=["H-M1"])

        store = _make_store()
        result = score_pipeline(
            "2021-01-15", store, _base_cfg(),
            scorer_fn=custom_scorer, verdict_fn=custom_verdict,
        )
        for sym in result.symbols:
            self.assertEqual(result.verdicts[sym].status, "EXIT")
            plan = [p for p in result.sizing.execution_plan if p["symbol"] == sym]
            if plan:
                self.assertEqual(plan[0]["mode"], "execute_now")


class TestPipelineSystemGates(unittest.TestCase):
    """Structural tests that each system gate has support in the pipeline."""

    def test_gate1_single_risk_source(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIsNotNone(result.risk_state.cov)

    def test_gate2_single_sizing_entry(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIsNotNone(result.sizing.target_weights)

    def test_gate3_r3_invariant(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        for sym, w in result.sizing.target_weights.items():
            self.assertLessEqual(w, result.verdicts[sym].rule_target_weight + 1e-6)

    def test_gate4_confidence_spine(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIn(result.confidence.mode, ("NORMAL", "CAUTION", "DEGRADED"))
        self.assertIn("decision_confidence", result.audit["confidence"])

    def test_gate5_pbo_support(self) -> None:
        """ValidationHarness is available (tested separately)."""
        from hermes_escape_top.core.backtest.harness import prob_backtest_overfitting
        self.assertTrue(callable(prob_backtest_overfitting))

    def test_gate6_factor_health_support(self) -> None:
        from hermes_escape_top.core.factors.lab import factor_ic, cluster_and_prune
        self.assertTrue(callable(factor_ic))
        self.assertTrue(callable(cluster_and_prune))

    def test_gate7_governance_support(self) -> None:
        store = _make_store()
        result = score_pipeline("2021-01-15", store, _base_cfg())
        self.assertIn("fragility", result.audit)
        self.assertIn("disagreement", result.audit)


if __name__ == "__main__":
    unittest.main()
