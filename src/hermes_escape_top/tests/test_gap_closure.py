from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.backtest.labeling import eval_labels, triple_barrier_labels
from hermes_escape_top.core.backtest.costs import apply_cost
from hermes_escape_top.core.backtest.metrics import compute_metrics
from hermes_escape_top.core.backtest.param_sweep import run_param_sweep
from hermes_escape_top.core.backtest.replay import run_strategy_backtest
from hermes_escape_top.core.backtest.simulator import DayDecision, simulate, simulate_rebalanced_weights
from hermes_escape_top.core.backtest.snapshot import build_snapshot
from hermes_escape_top.core.backtest.validation import deflated_sharpe, deflated_sharpe_ratio, purged_kfold_indices, walk_forward_splits
from hermes_escape_top.core.data.audit import audit_replay_matches, load_last_audit
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.breadth import component_breadth
from hermes_escape_top.core.data.crypto import annualized_basis
from hermes_escape_top.core.data.macro import CboeIndicesSource, FredNetLiquiditySource, fred_net_liquidity_frame, net_liquidity_from_series
from hermes_escape_top.core.data.options import black_scholes_gamma, gex_proxy, skew_record
from hermes_escape_top.core.data.pcr import PutCallSource
from hermes_escape_top.core.data.quality import quality_from_snapshots
from hermes_escape_top.core.data.sentiment import AaiiSource
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.data.valuation import valuation_missing
from hermes_escape_top.core.decision.signal_journal import SignalJournalEntry, append_signal_journal, load_latest_status, trading_days_since_last_sell
from hermes_escape_top.core.routing.capital_routing import evaluate_brkb_defense, route_capital
from hermes_escape_top.core.scoring.result import ScoreResult
from hermes_escape_top.pipeline import score_pipeline


DAY = date(2026, 5, 29)


def price_frame(returns: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=len(returns))
    close = 100.0 * (1.0 + pd.Series(returns, index=dates)).cumprod()
    return pd.DataFrame({"Close": close, "Open": close, "High": close + 1, "Low": close - 1, "Volume": 1_000_000}, index=dates)


class GapClosureTest(unittest.TestCase):
    def test_transaction_simulator_and_strategy_backtest(self) -> None:
        histories = {"AAA": price_frame([0.01, -0.005, 0.02])}
        targets = {"2026-01-01": {"AAA": 1.0}, "2026-01-02": {"AAA": 1.0}, "2026-01-05": {"AAA": 0.5}}
        sim = simulate_rebalanced_weights(histories, targets)
        self.assertGreater(sim.metrics["final_value"], 0)
        panel = {"AAA": pd.Series([100, 110, 121], index=pd.bdate_range("2026-01-01", periods=3))}
        routed = simulate(
            [DayDecision("2026-01-01", {"AAA": 1.0}), DayDecision("2026-01-02", {"AAA": 0.5}), DayDecision("2026-01-05", {"AAA": 0.5})],
            panel,
            {"costs": {"round_trip_bps": 0}},
        )
        self.assertGreater(routed.metrics["final_value"], 100000)
        self.assertGreater(routed.turnover, 0)
        backtest = run_strategy_backtest("2026-05-28", "2026-05-29", limit=2)
        self.assertEqual(backtest["schema_version"], "escape-top-greenfield-strategy-backtest-v1")
        self.assertIn("data_manifest_id", backtest)

    def test_param_sweep_scaffold_runs(self) -> None:
        payload = run_param_sweep("2026-05-28", "2026-05-29", limit=2, vol_budgets=(0.35,), corr_windows=(60,), penalties=(0.7,))
        self.assertEqual(len(payload["rows"]), 1)
        self.assertIn("data_manifest_id", payload)

    def test_labeling_and_purged_validation(self) -> None:
        close = pd.Series([100, 105, 112, 108, 95, 90], index=pd.bdate_range("2026-01-01", periods=6))
        labels = triple_barrier_labels(close, ["2026-01-01"], horizon=4, profit_take=0.10, stop_loss=-0.10)
        self.assertEqual(labels[0].label, 1)
        dd_labels = eval_labels(["2026-01-01"], close, H=4, dd_threshold=-0.04)
        self.assertEqual(int(dd_labels.iloc[0]["label"]), 1)
        folds = list(purged_kfold_indices(20, n_splits=4, purge=2, embargo=1))
        self.assertEqual(len(folds), 4)
        train, test = folds[0]
        self.assertTrue(set(train).isdisjoint(set(test)))
        self.assertLess(deflated_sharpe_ratio(1.0, trials=10, observations=100), 1.0)
        self.assertLess(deflated_sharpe([0.01, -0.005, 0.002, 0.004], n_trials=20, skew=1.0, kurt=5.0), 20)
        wf = walk_forward_splits(pd.bdate_range("2020-01-01", "2023-12-31"), is_years=2, oos_months=6, step_months=6, label_horizon=20)
        self.assertTrue(wf)
        self.assertLess(wf[0].train_idx[-1], wf[0].test_idx[0])

    def test_backtest_snapshot_costs_and_metrics_helpers(self) -> None:
        snapshots = build_snapshot("2026-05-29")
        self.assertIn("SOFT", snapshots)
        self.assertFalse(snapshots["SOFT"].is_missing("net_liq_chg10_pctl"))
        self.assertGreater(apply_cost(100000, 0.02, {"costs": {"round_trip_bps": 10, "fixed_slippage_bps": 5}}), 0)
        equity = pd.Series([100, 110, 99, 120], index=pd.bdate_range("2026-01-01", periods=4))
        metrics = compute_metrics(equity, benchmark=equity * 0.9, trades=[{"turnover": 0.2}])
        self.assertIn("calmar", metrics)
        self.assertEqual(metrics["turnover"], 0.2)

    def test_soft_data_contract_modules(self) -> None:
        histories = {"A": price_frame([0.01] * 60), "B": price_frame([-0.01] * 60)}
        breadth = component_breadth(histories, "2026-03-25")
        self.assertTrue(breadth["available"])
        macro = net_liquidity_from_series(
            pd.Series([10, 12], index=pd.bdate_range("2026-01-01", periods=2)),
            pd.Series([1, 1], index=pd.bdate_range("2026-01-01", periods=2)),
            pd.Series([2, 2], index=pd.bdate_range("2026-01-01", periods=2)),
            "2026-01-02",
        )
        self.assertTrue(macro.data_available)
        fred_frame = fred_net_liquidity_frame(
            pd.Series(range(1, 90), index=pd.bdate_range("2026-01-01", periods=89)),
            pd.Series([1] * 89, index=pd.bdate_range("2026-01-01", periods=89)),
            pd.Series([1] * 89, index=pd.bdate_range("2026-01-01", periods=89)),
            percentile_window=60,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"paths": {"soft_history_dir": tmp}, "features": {"data_net_liquidity": True}, "runtime": {"offline_replay_mode": True}}
            path = FredNetLiquiditySource().history_path(cfg)
            path.parent.mkdir(parents=True, exist_ok=True)
            fred_frame.to_csv(path, index=False)
            unavailable = FredNetLiquiditySource().fetch("2026-01-01", cfg)
            available = FredNetLiquiditySource().fetch(str(fred_frame["publish_date"].iloc[-1].date()), cfg)
            self.assertFalse(unavailable.data_available)
            self.assertTrue(available.data_available)
            self.assertIn("net_liq_chg10_pctl", available.fields)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "paths": {"history_dir": tmp, "legacy_history_dir": tmp, "archive_dir": str(Path(tmp) / "archive"), "soft_history_dir": str(Path(tmp) / "soft")},
                "features": {"data_skew_vvix": True},
                "runtime": {"offline_replay_mode": True},
            }
            dates = pd.bdate_range("2026-01-01", periods=70)
            for symbol, values in {
                "^VIX": [20.0] * 70,
                "^VIX3M": [25.0] * 70,
                "^VIX9D": [18.0] * 70,
                "^SKEW": list(np.linspace(120, 165, 70)),
                "^VVIX": list(np.linspace(70, 110, 69)) + [12.0],
            }.items():
                path = LocalStore(cfg).history_path(symbol)
                pd.DataFrame({"date": dates, "open": values, "high": values, "low": values, "close": values, "adj_close": values, "volume": 0}).to_csv(path, index=False)
            cboe = CboeIndicesSource().fetch("2026-04-10", cfg)
            self.assertTrue(cboe.data_available)
            self.assertGreater(cboe.fields["vvix_index"], 40)
            self.assertGreater(cboe.fields["skew_pctl"], 90)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"paths": {"soft_history_dir": tmp}, "features": {"data_aaii": True}, "runtime": {"offline_replay_mode": True}}
            path = AaiiSource().history_path(cfg)
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(
                {
                    "date": ["2026-01-08", "2026-01-15"],
                    "publish_date": ["2026-01-08", "2026-01-15"],
                    "aaii_bull": [0.30, 0.60],
                    "aaii_bear": [0.40, 0.20],
                    "aaii_bull_bear_spread": [-0.10, 0.40],
                    "aaii_bull_pctl": [50.0, 99.0],
                    "aaii_spread_pctl": [50.0, 99.0],
                }
            ).to_csv(path, index=False)
            self.assertFalse(AaiiSource().fetch("2026-01-07", cfg).data_available)
            self.assertEqual(AaiiSource().fetch("2026-01-15", cfg).fields["aaii_bull_pctl"], 99.0)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "paths": {"history_dir": tmp, "legacy_history_dir": tmp, "archive_dir": str(Path(tmp) / "archive"), "soft_history_dir": str(Path(tmp) / "soft")},
                "features": {"data_cboe_pcr": True},
                "runtime": {"offline_replay_mode": True},
            }
            store = LocalStore(cfg)
            path = store.history_path("^VIX")
            path.parent.mkdir(parents=True, exist_ok=True)
            dates = pd.bdate_range("2026-01-01", periods=80)
            values = list(np.linspace(20, 12, 80))
            pd.DataFrame({"date": dates, "open": values, "high": values, "low": values, "close": values, "adj_close": values, "volume": 0}).to_csv(path, index=False)
            pcr = PutCallSource().fetch("2026-04-22", cfg)
            self.assertTrue(pcr.data_available)
            self.assertEqual(pcr.source, "PCR_VIX_LIVE_PROXY")
            self.assertEqual(pcr.latency_days, 0)
            self.assertIn("equity_pcr_pctl", pcr.fields)
        soft_quality = quality_from_snapshots([
            SymbolSnapshot("SOFT", DAY, {
                "net_liq_chg10_pctl": Field("net_liq_chg10_pctl", 50.0, "FRED", DAY, latency_days=5),
                "aaii_bull_pctl": Field("aaii_bull_pctl", 50.0, "AAII", DAY, latency_days=9),
            })
        ])
        self.assertEqual(soft_quality.latency_score, 94.0)
        self.assertGreater(black_scholes_gamma(100, 100, 0.04, 0.30, 0.25), 0)
        self.assertTrue(gex_proxy([{"type": "call", "strike": 100, "rate": 0.04, "iv": 0.3, "tte": 0.25, "open_interest": 10}], 100, "2026-01-02").data_available)
        self.assertTrue(skew_record(0.4, 0.3, "2026-01-02").data_available)
        self.assertTrue(annualized_basis(105, 100, 30, "2026-01-02").data_available)
        self.assertFalse(valuation_missing("MSTR", "2026-01-02").data_available)

    def test_brkb_defense_degrades_defcon2_route(self) -> None:
        config = load_config()
        brkb = SymbolSnapshot("BRK.B", DAY, {"close": Field("close", 90.0, "unit", DAY), "ma200": Field("ma200", 100.0, "unit", DAY)})
        state = evaluate_brkb_defense({"BRK.B": brkb}, {}, config)
        self.assertTrue(state.degraded)
        score = ScoreResult("MSTR", DAY, module_scores={"D": 10.0}, status="EXIT", hard_valve_hits=[])
        decision = route_capital("MSTR", score, config, snapshots={"BRK.B": brkb})
        self.assertEqual(decision.destination, "BOXX")

    def test_audit_and_signal_journal(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        audit = load_last_audit(Path(payload["audit_log_path"]))
        self.assertIsNotNone(audit)
        self.assertTrue(audit_replay_matches(audit))
        with tempfile.TemporaryDirectory() as tmp:
            path = append_signal_journal(
                Path(tmp) / "signals.jsonl",
                [SignalJournalEntry("2026-01-01", "SOXL", "WATCH", 20.0, []), SignalJournalEntry("2026-01-02", "SOXL", "TRIM", 35.0, [])],
            )
            self.assertEqual(load_latest_status(path, "SOXL", before_as_of="2026-01-03"), "TRIM")
            self.assertEqual(trading_days_since_last_sell(path, "SOXL", "2026-01-05"), 1)


if __name__ == "__main__":
    unittest.main()
