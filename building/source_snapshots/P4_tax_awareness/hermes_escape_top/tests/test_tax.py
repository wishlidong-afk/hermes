"""Tests for E27 Tax / Wash-Sale Awareness."""

from __future__ import annotations

import unittest
from datetime import date

from hermes_escape_top.core.portfolio.tax import (
    TaxLot,
    WashSaleCheck,
    after_tax_return,
    tax_lot_optimize,
    wash_sale_check,
)


class TestWashSaleCheck(unittest.TestCase):
    def test_no_recent_buy_is_clean(self) -> None:
        result = wash_sale_check("MSTR", date(2026, 6, 1), [])
        self.assertFalse(result.is_wash_sale)

    def test_buy_within_30_days_triggers(self) -> None:
        trades = [{"symbol": "MSTR", "date": "2026-05-20", "action": "buy", "shares": 10, "price": 400}]
        result = wash_sale_check("MSTR", date(2026, 6, 1), trades)
        self.assertTrue(result.is_wash_sale)

    def test_buy_outside_window_clean(self) -> None:
        trades = [{"symbol": "MSTR", "date": "2026-04-01", "action": "buy", "shares": 10, "price": 400}]
        result = wash_sale_check("MSTR", date(2026, 6, 1), trades)
        self.assertFalse(result.is_wash_sale)

    def test_substantially_identical_triggers(self) -> None:
        trades = [{"symbol": "MSTU", "date": "2026-05-25", "action": "buy", "shares": 5, "price": 50}]
        result = wash_sale_check("MSTR", date(2026, 6, 1), trades, substantially_identical=["MSTU"])
        self.assertTrue(result.is_wash_sale)

    def test_sell_action_ignored(self) -> None:
        trades = [{"symbol": "MSTR", "date": "2026-05-20", "action": "sell", "shares": 10, "price": 400}]
        result = wash_sale_check("MSTR", date(2026, 6, 1), trades)
        self.assertFalse(result.is_wash_sale)


class TestTaxLotOptimize(unittest.TestCase):
    def setUp(self) -> None:
        self.lots = [
            TaxLot("MSTR", 10, 300.0, date(2025, 1, 15), is_short_term=False),
            TaxLot("MSTR", 10, 500.0, date(2026, 3, 1), is_short_term=True),
            TaxLot("MSTR", 5, 400.0, date(2025, 8, 1), is_short_term=False),
        ]

    def test_hifo_picks_highest_cost_first(self) -> None:
        rec = tax_lot_optimize(self.lots, 10, current_price=450.0, method="HIFO")
        self.assertEqual(rec.method, "HIFO")
        self.assertAlmostEqual(rec.total_shares, 10.0)
        self.assertEqual(rec.lots_to_sell[0].cost_basis, 500.0)

    def test_fifo_picks_oldest_first(self) -> None:
        rec = tax_lot_optimize(self.lots, 10, current_price=450.0, method="FIFO")
        self.assertEqual(rec.lots_to_sell[0].acquired, date(2025, 1, 15))

    def test_hifo_maximizes_loss(self) -> None:
        rec_hifo = tax_lot_optimize(self.lots, 10, current_price=350.0, method="HIFO")
        rec_fifo = tax_lot_optimize(self.lots, 10, current_price=350.0, method="FIFO")
        self.assertLessEqual(rec_hifo.realized_gain, rec_fifo.realized_gain)

    def test_empty_lots(self) -> None:
        rec = tax_lot_optimize([], 10, current_price=450.0)
        self.assertEqual(rec.total_shares, 0.0)

    def test_short_long_split(self) -> None:
        rec = tax_lot_optimize(self.lots, 25, current_price=600.0, method="FIFO")
        self.assertNotEqual(rec.short_term_portion, 0.0)
        self.assertNotEqual(rec.long_term_portion, 0.0)


class TestAfterTaxReturn(unittest.TestCase):
    def test_gain_taxed(self) -> None:
        net = after_tax_return(1000.0, short_term_rate=0.37, is_short_term=True)
        self.assertAlmostEqual(net, 630.0)

    def test_loss_no_tax(self) -> None:
        net = after_tax_return(-500.0, is_short_term=True)
        self.assertAlmostEqual(net, -500.0)

    def test_long_term_lower_rate(self) -> None:
        st = after_tax_return(1000.0, is_short_term=True)
        lt = after_tax_return(1000.0, is_short_term=False)
        self.assertGreater(lt, st)


if __name__ == "__main__":
    unittest.main()
