from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.state_store import (
    latest_score_payload_before,
    latest_execution_confirmations,
    recent_calibration_logs,
    recent_ibkr_snapshots,
    record_execution_confirmation,
    sync_execution_confirmations,
    write_ibkr_snapshot,
    write_refresh_run,
    write_state_snapshot,
)
from hermes_escape_top.core.decision.action_intents import build_action_context
from hermes_escape_top.core.reentry.plan import ReentryPlan


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _temp_config(tmp: str) -> Path:
    cfg_path = PACKAGE_ROOT / "config" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["paths"]["archive_dir"] = str(Path(tmp) / "archive")
    cfg["paths"]["history_dir"] = str(PACKAGE_ROOT / "data" / "history")
    cfg["paths"]["soft_history_dir"] = str(PACKAGE_ROOT / "data" / "soft_history")
    cfg["paths"]["aaii_sentiment_xls"] = str(PACKAGE_ROOT / "data" / "sentiment.xls")
    path = Path(tmp) / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _minimal_payload(as_of: str) -> dict:
    return {
        "schema_version": "unit-test-state-v1",
        "as_of": as_of,
        "config_version": "unit",
        "input_hash": f"hash-{as_of}",
        "scores": {
            "SOXL": {
                "status": "HOLD",
                "final_score": 1,
                "sell_fraction": 0,
                "hard_valve_hits": [],
                "factor_scores": {
                    "A": [{"factor_id": "A1_QQQ_MA200_BREAK", "score": 1, "max_score": 4, "explain": "unit"}],
                },
            },
        },
        "sizing": {"SOXL": {"target_weight": 0.3}},
        "routing": {"SOXL": {"destination": "HOLD"}},
        "decision_layers": {},
        "action_intents": {},
        "data_quality": {"level": "HIGH", "overall_score": 100},
        "data_quality_breakdown": {"sources": [{"name": "SOXL", "category": "price", "status": "FRESH"}]},
        "posterior_pnl": {
            "portfolio_value": 100000,
            "escape": {"SOXL": {"symbol": "SOXL", "notional": 30000, "shares": 100, "pnl": 0, "return_pct": 0}},
            "mirror": {},
        },
        "reentry": {"SOXL": {"tranche": "LOCKED", "eligible": False, "locked_reason": "unit"}},
        "reentry_state": {"states": {}, "execution_confirmations": {}},
        "ibkr": {"source": "disabled", "sync_time": as_of},
    }


def _snapshot(symbol: str, close: float) -> SymbolSnapshot:
    as_of = date(2026, 6, 11)
    return SymbolSnapshot(
        symbol=symbol,
        as_of=as_of,
        fields={"close": Field("close", close, "unit", as_of)},
    )


class StateStoreAndActionTest(unittest.TestCase):
    def test_action_context_expands_defcon_combo_into_execution_legs(self) -> None:
        payload = {
            "scores": {
                "MSTR": {
                    "status": "EXIT",
                    "final_score": 80,
                    "sell_fraction": 1.0,
                    "hard_valve_hits": ["H-M1"],
                    "module_scores": {},
                    "factor_scores": {},
                },
            },
            "sizing": {"MSTR": {"sleeve_cap": 0.15, "target_weight": 0.0}},
            "routing": {
                "MSTR": {
                    "applies": True,
                    "defcon": "DEFCON1",
                    "destination": "BOXX",
                    "weights": {"BOXX": 0.5, "DBMF": 0.3, "GLD": 0.2},
                    "reason": "unit combo route",
                },
            },
            "reentry": {"MSTR": {"eligible": False}},
            "posterior_pnl": {"portfolio_value": 100000},
            "data_quality": {"overall_score": 100},
            "ibkr": {"source": "disabled"},
        }
        snapshots = {
            "MSTR": _snapshot("MSTR", 400),
            "BOXX": _snapshot("BOXX", 100),
            "DBMF": _snapshot("DBMF", 25),
            "GLD": _snapshot("GLD", 200),
        }

        result = build_action_context(payload, snapshots)

        intent = result["action_intents"]["MSTR"]
        self.assertEqual(intent["target_symbol"], "BOXX/DBMF/GLD")
        self.assertIsNone(intent["target_shares"])
        defense = {
            leg["symbol"]: leg
            for leg in intent["trade_plan"]["legs"]
            if leg["role"] == "defense_route"
        }
        self.assertEqual(set(defense), {"BOXX", "DBMF", "GLD"})
        self.assertAlmostEqual(defense["BOXX"]["target_weight"], 0.075)
        self.assertAlmostEqual(defense["DBMF"]["target_weight"], 0.045)
        self.assertAlmostEqual(defense["GLD"]["target_weight"], 0.03)
        self.assertEqual(defense["BOXX"]["target_notional"], 7500.0)
        self.assertEqual(defense["DBMF"]["target_notional"], 4500.0)
        self.assertEqual(defense["GLD"]["target_notional"], 3000.0)
        self.assertEqual(defense["BOXX"]["target_shares"], 75.0)
        self.assertEqual(defense["DBMF"]["target_shares"], 180.0)
        self.assertEqual(defense["GLD"]["target_shares"], 15.0)
        self.assertEqual(
            result["today_ops"]["destinations"],
            {"BOXX": 7500.0, "DBMF": 4500.0, "GLD": 3000.0},
        )

        payload["portfolio_target_weights"] = {"BOXX": 0.85, "MSTR": 0.0, "IAU": 0.15}
        payload["route_transition"] = {"applied": True, "changed_leg": "IAU"}
        buffered = build_action_context(payload, snapshots)
        self.assertEqual(buffered["today_ops"]["execution_target_source"], "portfolio_target_weights")
        self.assertEqual(buffered["today_ops"]["portfolio_target_weights"], payload["portfolio_target_weights"])
        self.assertTrue(buffered["today_ops"]["route_transition"]["applied"])

    def test_pipeline_writes_unified_state_and_action_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = _temp_config(tmp)
            # Use default config paths but disable IBKR to avoid live dependency.
            with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
                payload = score_pipeline("2026-06-04", config_path=config_path, include_ibkr=True)
            self.assertIn("state", payload)
            self.assertIn("today_ops", payload)
            self.assertIn("action_intents", payload)
            self.assertIn("decision_layers", payload)
            self.assertIn("data_quality_breakdown", payload)
            self.assertIn("ibkr_history", payload)
            self.assertIn("calibration_history", payload)
            self.assertEqual(set(payload["action_intents"]), {"FNGU", "MSTR", "SOXL"})
            db_path = Path(payload["state"]["db_path"])
            self.assertTrue(db_path.exists())
            with sqlite3.connect(db_path) as conn:
                runs = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
                decisions = conn.execute("SELECT COUNT(*) FROM decisions WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
                sources = conn.execute("SELECT COUNT(*) FROM data_sources WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
                reentry = conn.execute("SELECT COUNT(*) FROM reentry_states WHERE score_run_id=?", (payload["state"]["score_run_id"],)).fetchone()[0]
                calibration = conn.execute("SELECT COUNT(*) FROM calibration_logs WHERE as_of='2026-06-04'").fetchone()[0]
            self.assertGreaterEqual(runs, 1)
            self.assertEqual(decisions, 3)
            self.assertGreater(sources, 0)
            self.assertEqual(reentry, 3)
            self.assertGreater(calibration, 0)
            self.assertGreaterEqual(len(recent_ibkr_snapshots(db_path)), 1)
            self.assertGreaterEqual(len(recent_calibration_logs(db_path)), 1)
            self.assertTrue(str(db_path).startswith(tmp))

    def test_refresh_run_writer_records_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            meta = write_refresh_run(
                path,
                requested_as_of="latest",
                effective_as_of="2026-06-04",
                status="OK",
                steps=[{"name": "history_refresh", "status": "SKIPPED"}],
                refresh_status={"symbols_updated": 0},
                payload_hash="abc",
            )
            self.assertEqual(meta["refresh_run_id"], 1)
            with sqlite3.connect(path) as conn:
                row = conn.execute("SELECT status, payload_hash FROM refresh_runs").fetchone()
        self.assertEqual(row, ("OK", "abc"))

    def test_execution_confirmation_writer_records_latest_by_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            meta = record_execution_confirmation(
                path,
                symbol="soxl",
                tranche="T1",
                status="CONFIRMED",
                source="unit_test",
                payload={"shares": 10},
            )
            self.assertEqual(meta["symbol"], "SOXL")
            latest = latest_execution_confirmations(path)
        self.assertEqual(latest["SOXL"]["tranche"], "T1")
        self.assertEqual(latest["SOXL"]["status"], "CONFIRMED")

    def test_execution_confirmation_sync_dedupes_external_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            row = {
                "symbol": "SOXL",
                "tranche": "T1",
                "status": "AUTO_CONFIRMED",
                "source": "ibkr_executions",
                "external_key": "exec-1",
                "payload": {"shares": 10},
            }
            first = sync_execution_confirmations(path, [row])
            second = sync_execution_confirmations(path, [row])
            latest = latest_execution_confirmations(path)
        self.assertEqual(first["inserted_count"], 1)
        self.assertEqual(second["inserted_count"], 0)
        self.assertEqual(second["skipped_count"], 1)
        self.assertEqual(latest["SOXL"]["payload"]["external_key"], "exec-1")

    def test_retention_prunes_runs_and_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            for day in ["2026-06-01", "2026-06-02", "2026-06-03"]:
                write_state_snapshot(path, _minimal_payload(day), retention={
                    "score_runs": 2,
                    "ibkr_snapshots": 2,
                    "calibration_logs": 2,
                    "refresh_runs": 2,
                    "execution_confirmations": 2,
                })
            for idx in range(3):
                write_refresh_run(
                    path,
                    requested_as_of="latest",
                    effective_as_of=f"2026-06-0{idx + 1}",
                    status="OK",
                    steps=[],
                    refresh_status={},
                    retention={"refresh_runs": 2},
                )
            with sqlite3.connect(path) as conn:
                score_runs = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
                decisions = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
                factors = conn.execute("SELECT COUNT(*) FROM factor_values").fetchone()[0]
                refresh_runs = conn.execute("SELECT COUNT(*) FROM refresh_runs").fetchone()[0]
                ibkr_snapshots = conn.execute("SELECT COUNT(*) FROM ibkr_snapshots").fetchone()[0]
        self.assertEqual(score_runs, 2)
        self.assertEqual(decisions, 2)
        self.assertEqual(factors, 2)
        self.assertEqual(refresh_runs, 2)
        self.assertEqual(ibkr_snapshots, 2)

    def test_latest_score_payload_before_is_strictly_prior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            for day in ["2026-06-01", "2026-06-02", "2026-06-03"]:
                write_state_snapshot(path, _minimal_payload(day), retention={"score_runs": 10})

            prior = latest_score_payload_before(path, "2026-06-03")
            none = latest_score_payload_before(path, "2026-06-01")

        self.assertEqual(prior["as_of"], "2026-06-02")
        self.assertIsNone(none)

    def test_ibkr_only_snapshot_retention_does_not_prune_score_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hermes_state.sqlite"
            for day in ["2026-06-01", "2026-06-02", "2026-06-03"]:
                write_state_snapshot(path, _minimal_payload(day), retention={"score_runs": 10})
            for day in ["2026-06-04", "2026-06-05", "2026-06-06"]:
                write_ibkr_snapshot(
                    path,
                    as_of=day,
                    ibkr={"source": "tws", "account_id": "U_TEST", "net_liq": 100000, "sync_time": f"{day}T13:30:00+00:00"},
                    retention={"score_runs": 1, "ibkr_snapshots": 2},
                )
            with sqlite3.connect(path) as conn:
                score_runs = conn.execute("SELECT COUNT(*) FROM score_runs").fetchone()[0]
                ibkr_snapshots = conn.execute("SELECT COUNT(*) FROM ibkr_snapshots").fetchone()[0]
        self.assertEqual(score_runs, 3)
        self.assertEqual(ibkr_snapshots, 2)

    def test_pipeline_auto_confirms_t1_from_ibkr_executions(self) -> None:
        class Snapshot:
            def to_dict(self) -> dict:
                return {
                    "source": "tws",
                    "sync_time": "2026-06-04T21:00:00+00:00",
                    "lookback_days": 21,
                    "records": [
                        {
                            "exec_id": "exec-soxl-1",
                            "symbol": "SOXL",
                            "side": "BOT",
                            "shares": 12,
                            "price": 42.5,
                            "time": "2026-06-04T20:50:00+00:00",
                        }
                    ],
                }

        def fake_plan(symbol, *_args, **_kwargs):
            if symbol == "SOXL":
                return ReentryPlan(symbol, True, "T1", 0.3, "", ["unit eligible"])
            return ReentryPlan(symbol, False, "LOCKED", 0.0, "unit", ["unit locked"])

        with tempfile.TemporaryDirectory() as tmp:
            config_path = _temp_config(tmp)
            with mock.patch(
                "hermes_escape_top.pipeline._ibkr_payload",
                return_value={"source": "tws", "sync_time": "2026-06-04T21:00:00+00:00", "net_liq": 100000},
            ), mock.patch(
                "hermes_escape_top.pipeline.build_reentry_plan",
                side_effect=fake_plan,
            ), mock.patch(
                "hermes_escape_top.ibkr.executions.read_executions",
                return_value=Snapshot(),
            ):
                payload = score_pipeline("2026-06-04", config_path=config_path, include_ibkr=True)
            sync = payload["execution_sync"]
            latest = payload["reentry_state"]["execution_confirmations"]
        self.assertEqual(sync["status"], "OK")
        self.assertEqual(sync["inserted_count"], 1)
        self.assertEqual(latest["SOXL"]["tranche"], "T1")
        self.assertEqual(latest["SOXL"]["source"], "ibkr_executions")


if __name__ == "__main__":
    unittest.main()
