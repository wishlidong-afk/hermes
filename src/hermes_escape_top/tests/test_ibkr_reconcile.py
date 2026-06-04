"""Tests for IBKR reconciliation (NEXT-6) — offline only, no TWS connection.

Tests use mock PositionSnapshot so they run without TWS.
Iron rule: tests never place orders or connect to a live broker.
"""
from __future__ import annotations

import unittest

from hermes_escape_top.ibkr.positions import PositionRecord, PositionSnapshot
from hermes_escape_top.ibkr.reconcile import ReconcileReport, reconcile


def _snap(positions=None, net_liq=100_000.0, account="U_TEST") -> PositionSnapshot:
    return PositionSnapshot(
        account_id=account,
        net_liq=net_liq,
        gross_position_value=net_liq * 0.9,
        total_cash=net_liq * 0.1,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        positions=positions or [],
        sync_time="2026-05-29T12:00:00+00:00",
        source="snapshot",
    )


def _pos(symbol, mv, qty=10.0, cost=None, sec="STK") -> PositionRecord:
    cost = cost if cost is not None else (mv / qty if qty else 0)
    return PositionRecord(
        symbol=symbol, sec_type=sec, quantity=qty,
        avg_cost=cost, market_value=mv, currency="USD",
        is_option=(sec == "OPT"),
    )


class TestReconcileMatch(unittest.TestCase):
    def test_exact_match(self):
        snap = _snap([_pos("FNGU", 18_000), _pos("SOXL", 10_800)])
        sizing = {
            "FNGU": {"target_weight": 0.18},
            "SOXL": {"target_weight": 0.108},
            "MSTR": {"target_weight": 0.0},
        }
        report = reconcile(snap, sizing, tolerance=0.01)
        fngu = next(d for d in report.trade_symbols if d.symbol == "FNGU")
        self.assertEqual(fngu.status, "MATCH")
        self.assertTrue(report.all_within_tolerance)

    def test_zero_ideal_zero_actual_is_match(self):
        snap = _snap([])
        sizing = {"MSTR": {"target_weight": 0.0}}
        report = reconcile(snap, sizing)
        mstr = report.trade_symbols[0]
        self.assertEqual(mstr.status, "MATCH")


class TestReconcileMissing(unittest.TestCase):
    def test_position_missing_from_account(self):
        snap = _snap([])   # no FNGU in account
        sizing = {"FNGU": {"target_weight": 0.18}}
        report = reconcile(snap, sizing)
        self.assertEqual(report.trade_symbols[0].status, "MISSING")
        self.assertAlmostEqual(report.trade_symbols[0].delta_weight, -0.18, places=4)

    def test_max_delta_computed(self):
        snap = _snap([])
        sizing = {"FNGU": {"target_weight": 0.20}, "MSTR": {"target_weight": 0.0}}
        report = reconcile(snap, sizing)
        self.assertAlmostEqual(report.max_abs_delta, 0.20, places=4)
        self.assertFalse(report.all_within_tolerance)


class TestReconcileOver(unittest.TestCase):
    def test_over_position_flagged(self):
        snap = _snap([_pos("FNGU", 30_000)])  # 30% actual, 18% ideal
        sizing = {"FNGU": {"target_weight": 0.18}}
        report = reconcile(snap, sizing)
        self.assertEqual(report.trade_symbols[0].status, "OVER")
        self.assertGreater(report.trade_symbols[0].delta_weight, 0)


class TestReconcileRouteLeg(unittest.TestCase):
    def test_soxx_in_route_legs_when_routing_provided(self):
        """When routing dict includes SOXX destination, it appears in route_legs."""
        snap = _snap([_pos("SOXX", 10_000)])
        sizing = {"SOXL": {"sleeve_cap": 0.30, "target_weight": 0.10}}
        routing = {"SOXL": {"applies": True, "destination": "SOXX", "weights": {"SOXX": 1.0}}}
        report = reconcile(snap, sizing, routing)
        # SOXX is in route_legs (destination of SOXL)
        soxx = next((d for d in report.route_legs if d.symbol == "SOXX"), None)
        self.assertIsNotNone(soxx)
        self.assertAlmostEqual(soxx.ideal_weight, 0.20)

    def test_route_leg_uses_residual_when_risky_target_is_zero(self):
        snap = _snap([])
        sizing = {"SOXL": {"sleeve_cap": 0.30, "target_weight": 0.0}}
        routing = {"SOXL": {"applies": True, "destination": "SOXX", "weights": {"SOXX": 1.0}}}
        report = reconcile(snap, sizing, routing)
        soxx = next(d for d in report.route_legs if d.symbol == "SOXX")
        self.assertAlmostEqual(soxx.ideal_weight, 0.30)
        self.assertEqual(soxx.status, "MISSING")

    def test_route_leg_respects_multi_destination_weights(self):
        snap = _snap([])
        sizing = {"MSTR": {"sleeve_cap": 0.15, "target_weight": 0.0}}
        routing = {
            "MSTR": {
                "applies": True,
                "destination": "BOXX",
                "weights": {"BOXX": 0.70, "DBMF": 0.30},
            }
        }
        report = reconcile(snap, sizing, routing)
        targets = {row.symbol: row.ideal_weight for row in report.route_legs}
        self.assertAlmostEqual(targets["BOXX"], 0.105)
        self.assertAlmostEqual(targets["DBMF"], 0.045)

    def test_soxx_is_route_leg_without_routing_dict(self):
        """Without routing dict, SOXX in account is flagged ROUTE_LEG via ROUTE_LEGS set."""
        snap = _snap([_pos("SOXX", 10_000)])
        sizing = {"SOXL": {"target_weight": 0.0}}
        report = reconcile(snap, sizing)   # no routing kwarg
        soxx = next((d for d in report.extra_positions if d.symbol == "SOXX"), None)
        self.assertIsNotNone(soxx)
        self.assertEqual(soxx.status, "ROUTE_LEG")

    def test_brkb_recognised_as_route_leg(self):
        snap = _snap([_pos("BRK B", 12_000)])
        sizing = {"MSTR": {"target_weight": 0.0}}
        report = reconcile(snap, sizing)
        brkb = next((d for d in report.extra_positions if d.symbol == "BRK B"), None)
        self.assertIsNotNone(brkb)
        self.assertEqual(brkb.status, "ROUTE_LEG")

    def test_unknown_symbol_is_extra(self):
        snap = _snap([_pos("NASA", 25_000)])
        sizing = {"MSTR": {"target_weight": 0.0}}
        report = reconcile(snap, sizing)
        nasa = next((d for d in report.extra_positions if d.symbol == "NASA"), None)
        self.assertIsNotNone(nasa)
        self.assertEqual(nasa.status, "EXTRA")


class TestReconcileReport(unittest.TestCase):
    def test_to_dict_serialisable(self):
        import json
        snap = _snap([_pos("FNGU", 15_000)])
        report = reconcile(snap, {"FNGU": {"target_weight": 0.18}})
        d = report.to_dict()
        s = json.dumps(d)   # must not raise
        self.assertIn("trade_symbols", s)

    def test_no_connection_uses_snapshot_source(self):
        snap = _snap([])
        snap.source = "snapshot"
        snap.error = "TWS connection refused"
        report = reconcile(snap, {"MSTR": {"target_weight": 0.0}})
        self.assertEqual(report.source, "snapshot")
        self.assertIsNotNone(report.error)

    def test_r3_analogy_actual_never_exceeds_netliq(self):
        """Total actual weight must not exceed 100% (sanity check)."""
        snap = _snap([
            _pos("FNGU", 20_000),
            _pos("SOXL", 15_000),
            _pos("MSTR", 5_000),
        ])
        sizing = {s: {"target_weight": 0.2} for s in ["FNGU", "SOXL", "MSTR"]}
        report = reconcile(snap, sizing)
        total_actual = sum(d.actual_weight for d in report.trade_symbols)
        self.assertLessEqual(total_actual, 1.001)


if __name__ == "__main__":
    unittest.main()
