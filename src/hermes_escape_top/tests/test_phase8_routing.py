from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from hermes_escape_top.config import load_config
from hermes_escape_top.core.routing.capital_routing import route_capital
from hermes_escape_top.core.scoring.result import ScoreResult
from hermes_escape_top.pipeline import score_pipeline


def result(status: str, modules: dict[str, float], factors: dict[str, float] | None = None, hard=None) -> ScoreResult:
    factor_scores = {"A": [], "B": [], "C": [], "D": []}
    for factor_id, score in (factors or {}).items():
        module = factor_id[0]
        factor_scores[module].append({"factor_id": factor_id, "score": score})
    return ScoreResult(
        symbol="SOXL",
        as_of=date(2026, 5, 29),
        module_scores=modules,
        status=status,
        hard_valve_hits=hard or [],
        factor_scores=factor_scores,
    )


class Phase8RoutingTest(unittest.TestCase):
    def test_defcon1_macro_routes_to_boxx(self) -> None:
        config = load_config()
        decision = route_capital("SOXL", result("REDUCE", {"A": 12}, {"A1_QQQ_MA200_BREAK": 4}), config)
        self.assertEqual(decision.defcon, "DEFCON1")
        self.assertIn("BOXX", decision.weights)

    def test_defcon1_uses_max_factor_when_prefix_has_multiple_rows(self) -> None:
        config = load_config()
        decision = route_capital(
            "SOXL",
            result(
                "REDUCE",
                {"A": 4},
                {
                    "A1_QQQ_MA200_BREAK": 0,
                    "A1_VIX_COMPLACENCY": 4,
                },
            ),
            config,
        )
        self.assertEqual(decision.defcon, "DEFCON1")
        self.assertIn("BOXX", decision.weights)

    def test_defcon2_hard_valve_routes_to_brkb(self) -> None:
        config = load_config()
        decision = route_capital("MSTR", result("EXIT", {"A": 0, "D": 0}, hard=["H-M1"]), config)
        self.assertEqual(decision.defcon, "DEFCON2")
        self.assertEqual(decision.destination, "BRK.B")

    def test_defcon3_routine_reduce_routes_to_one_x(self) -> None:
        config = load_config()
        decision = route_capital("SOXL", result("REDUCE", {"A": 0, "D": 0}), config)
        self.assertEqual(decision.defcon, "DEFCON3")
        self.assertEqual(decision.destination, "SOXX")

    def test_no_sell_has_no_route(self) -> None:
        config = load_config()
        decision = route_capital("FNGU", result("WATCH", {"A": 0, "D": 0}), config)
        self.assertFalse(decision.applies)

    def test_score_pipeline_includes_routing(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        self.assertEqual(set(payload["routing"]), {"FNGU", "MSTR", "SOXL"})
        # DEFCON1 since the 2026-06-08 calibration enabled A10/A11/A15: MSTR's A
        # module is now 14 (>=12) with QQQ broken → macro-nuclear route to BOXX.
        self.assertEqual(payload["routing"]["MSTR"]["defcon"], "DEFCON1")


if __name__ == "__main__":
    unittest.main()
