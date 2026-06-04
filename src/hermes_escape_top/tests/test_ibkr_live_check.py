from __future__ import annotations

import unittest
from unittest import mock

from hermes_escape_top.ibkr import live_check
from hermes_escape_top.ibkr.positions import PositionSnapshot


class IbkrLiveCheckTest(unittest.TestCase):
    def test_snapshot_source_is_not_live(self) -> None:
        snap = PositionSnapshot(
            account_id="U_CACHE",
            net_liq=100_000.0,
            gross_position_value=0.0,
            total_cash=100_000.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            source="snapshot",
            error="No TCP listener",
        )
        with (
            mock.patch.object(live_check, "read_positions", return_value=snap),
            mock.patch.object(live_check, "score_pipeline") as score_mock,
        ):
            payload = live_check.run_live_check("2026-05-29", write_report=False)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "IBKR_NOT_LIVE")
        self.assertEqual(payload["preflight"]["source"], "snapshot")
        score_mock.assert_not_called()

    def test_live_source_runs_score_refresh(self) -> None:
        snap = PositionSnapshot(
            account_id="U_LIVE",
            net_liq=100_000.0,
            gross_position_value=50_000.0,
            total_cash=50_000.0,
            unrealized_pnl=1_000.0,
            realized_pnl=0.0,
            source="tws",
        )
        score_payload = {
            "scores": {
                "MSTR": {
                    "status": "HOLD",
                    "final_score": 10.0,
                    "sell_fraction": 0.0,
                    "hard_valve_hits": [],
                }
            },
            "sizing": {"MSTR": {"target_weight": 0.15}},
            "routing": {"MSTR": {"destination": None}},
            "ibkr": {
                "source": "tws",
                "account_id": "U_LIVE",
                "net_liq": 100_000.0,
                "max_abs_delta": 0.0,
                "all_within_tolerance": True,
                "trade_symbols": [],
                "route_legs": [],
            },
            "audit_log_path": "/tmp/audit.jsonl",
            "signal_journal_path": "/tmp/signal.jsonl",
        }
        with (
            mock.patch.object(live_check, "read_positions", return_value=snap),
            mock.patch.object(live_check, "score_pipeline", return_value=score_payload),
        ):
            payload = live_check.run_live_check("2026-05-29", write_report=False)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "LIVE_OK")
        self.assertEqual(payload["ibkr"]["source"], "tws")
        self.assertEqual(payload["score_summary"]["MSTR"]["target_weight"], 0.15)


if __name__ == "__main__":
    unittest.main()
