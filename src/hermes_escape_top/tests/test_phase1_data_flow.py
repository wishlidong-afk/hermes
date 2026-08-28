from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.flow import basket_flow, chaikin_money_flow, money_flow_index, money_flow_metrics
from hermes_escape_top.core.data.network_guard import assert_no_network
from hermes_escape_top.core.data.quality import quality_from_snapshots
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.pipeline import (
    _decision_quality_excluded_fields,
    _quality_breakdown,
    _quality_payloads,
    archive_soft_inputs,
    flow_snapshot,
)


def synthetic_ohlcv(close_location: str) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=30)
    rows = []
    close = 100.0
    for i, dt in enumerate(dates):
        high = close + 5.0
        low = close - 5.0
        if close_location == "upper":
            c = high - 0.5
        elif close_location == "lower":
            c = low + 0.5
        else:
            c = close
        rows.append({"Date": dt, "Open": close, "High": high, "Low": low, "Close": c, "Volume": 1000000 + i})
        close += 0.2 if close_location == "upper" else -0.2
    return pd.DataFrame(rows).set_index("Date")


class Phase1DataFlowTest(unittest.TestCase):
    def test_cmf_distribution_and_accumulation_signs(self) -> None:
        distribution = synthetic_ohlcv("lower")
        accumulation = synthetic_ohlcv("upper")
        self.assertLess(float(chaikin_money_flow(distribution).dropna().iloc[-1]), 0)
        self.assertGreater(float(chaikin_money_flow(accumulation).dropna().iloc[-1]), 0)

    def test_mfi_available_and_flow_metrics_classifies(self) -> None:
        frame = synthetic_ohlcv("lower")
        mfi = money_flow_index(frame).dropna()
        self.assertTrue(len(mfi) > 0)
        metrics = money_flow_metrics("TEST", frame, "2026-02-15")
        self.assertIn(metrics.severity, {"WATCH", "ABNORMAL", "SEVERE"})

    def test_basket_flow_reports_component_staleness(self) -> None:
        fresh = synthetic_ohlcv("upper")
        stale = synthetic_ohlcv("upper").iloc[:-2]
        payload = basket_flow({"FRESH", "STALE"}, {"FRESH": fresh, "STALE": stale}, "2026-02-11")
        self.assertEqual(payload["component_min_as_of"], stale.index[-1].date().isoformat())
        self.assertGreater(payload["component_max_stale_days"], 0)
        self.assertEqual(payload["stale_components"][0]["symbol"], "STALE")

    def test_load_dated_snapshot_never_returns_future(self) -> None:
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            patched = json.loads(json.dumps(config))
            patched["paths"]["archive_dir"] = tmp
            patched["paths"]["history_dir"] = tmp
            patched["paths"]["legacy_history_dir"] = tmp
            store = LocalStore(patched)
            store.write_dated_snapshot("valuation", "2026-05-30", {"as_of": "2026-05-30"})
            self.assertIsNone(store.load_dated_snapshot("valuation", "2026-05-29"))
            store.write_dated_snapshot("valuation", "2026-05-28", {"as_of": "2026-05-28"})
            snap = store.load_dated_snapshot("valuation", "2026-05-29")
            self.assertEqual(snap["as_of"], "2026-05-28")

    def test_offline_no_network_hook(self) -> None:
        with assert_no_network():
            payload = flow_snapshot("2026-05-29")
        self.assertEqual(payload["schema_version"], "escape-top-greenfield-flow-v2-v1")

    def test_archive_soft_inputs_seed(self) -> None:
        payload = archive_soft_inputs("2026-05-29")
        self.assertIn("enrichment_cache", payload["archives"])
        for path in payload["archives"].values():
            self.assertTrue(Path(path).exists())

    def test_quality_penalties_are_grouped_by_source_and_cadence_aware(self) -> None:
        day = pd.Timestamp("2026-05-29").date()
        snap = SymbolSnapshot(
            "SOFT",
            day,
            {
                "aaii": Field("aaii", 0.1, "AAII", day, latency_days=8, quality_penalty=1.5),
                "aaii_bull": Field("aaii_bull", 0.5, "AAII", day, latency_days=8, quality_penalty=1.5),
                "aaii_spread": Field("aaii_spread", 0.2, "AAII", day, latency_days=8, quality_penalty=1.5),
                "pcr": Field("pcr", 0.6, "PCR_PROXY", day, is_proxy=True, quality_penalty=1.5),
                "pcr_pctl": Field("pcr_pctl", 20.0, "PCR_PROXY", day, is_proxy=True, quality_penalty=1.5),
            },
        )
        quality = quality_from_snapshots([snap])
        self.assertEqual(quality.latency_score, 97.0)
        self.assertEqual(quality.quality_score, 98.5)

    def test_quality_can_exclude_research_fields_without_hiding_decision_penalties(self) -> None:
        day = pd.Timestamp("2026-05-29").date()
        snap = SymbolSnapshot(
            "SOFT",
            day,
            {
                "btc_funding_basis": Field(
                    "btc_funding_basis",
                    0.01,
                    "BTC_FUNDING_PROXY",
                    day,
                    is_proxy=True,
                    quality_penalty=2.0,
                ),
                "component_breadth": Field(
                    "component_breadth",
                    0.55,
                    "LOCAL_COMPONENT_HISTORY",
                    day,
                    is_proxy=True,
                    quality_penalty=2.0,
                ),
                "unknown_record": Field(
                    "unknown_record",
                    1.0,
                    "UNKNOWN_WEEKLY",
                    day,
                    latency_days=9,
                ),
            },
        )

        all_source = quality_from_snapshots([snap])
        decision = quality_from_snapshots(
            [snap],
            excluded_fields={"SOFT.btc_funding_basis"},
        )

        self.assertEqual(all_source.quality_score, 96.0)
        self.assertEqual(decision.quality_score, 98.0)
        self.assertEqual(decision.latency_score, 80.0)
        self.assertTrue(
            any("SOFT.component_breadth" in row["field"] for row in decision.penalties)
        )
        self.assertTrue(
            any("SOFT.unknown_record" in row["field"] for row in decision.penalties)
        )
        self.assertFalse(
            any("SOFT.btc_funding_basis" in row["field"] for row in decision.penalties)
        )

    def test_decision_quality_excludes_only_known_nondecision_soft_records(self) -> None:
        config = {
            "features": {
                "data_btc_funding": True,
                "data_aaii": True,
            }
        }
        soft_data = {
            "records": {
                "btc_funding_basis": {
                    "fields": {
                        "btc_funding_pctl": 91.0,
                        "btc_basis_pctl": 88.0,
                    }
                },
                "aaii": {"fields": {"aaii_spread": -0.1}},
                "unknown_record": {"fields": {"unknown_child": 1.0}},
            }
        }

        excluded = _decision_quality_excluded_fields(soft_data, config)

        self.assertEqual(
            excluded,
            {
                "SOFT.btc_funding_basis",
                "SOFT.btc_funding_pctl",
                "SOFT.btc_basis_pctl",
            },
        )

    def test_quality_payloads_keep_decision_and_all_source_scores_separate(self) -> None:
        day = pd.Timestamp("2026-05-29").date()
        snapshots = {
            "SOFT": SymbolSnapshot(
                "SOFT",
                day,
                {
                    "btc_funding_basis": Field(
                        "btc_funding_basis",
                        0.01,
                        "BTC_FUNDING_PROXY",
                        day,
                        is_proxy=True,
                        quality_penalty=2.0,
                    ),
                    "btc_basis_pctl": Field(
                        "btc_basis_pctl",
                        88.0,
                        "BTC_BASIS_FROM_FUNDING_PROXY",
                        day,
                        is_proxy=True,
                        quality_penalty=2.0,
                    ),
                    "component_breadth": Field(
                        "component_breadth",
                        0.55,
                        "LOCAL_COMPONENT_HISTORY",
                        day,
                        is_proxy=True,
                        quality_penalty=2.0,
                    ),
                },
            )
        }
        soft_data = {
            "records": {
                "btc_funding_basis": {"fields": {"btc_basis_pctl": 88.0}},
                "component_breadth": {"fields": {}},
            }
        }
        config = {"features": {"data_btc_funding": True}}

        decision, all_source = _quality_payloads(snapshots, soft_data, config)

        self.assertEqual(decision["quality_score"], 98.0)
        self.assertEqual(all_source["quality_score"], 94.0)
        self.assertTrue(
            any("SOFT.component_breadth" in row["field"] for row in decision["penalties"])
        )
        self.assertFalse(
            any("btc_" in row["field"] for row in decision["penalties"])
        )

    def test_quality_breakdown_labels_soft_sources_by_decision_role(self) -> None:
        payload = {
            "data_quality": {"level": "HIGH", "overall_score": 93.4},
            "all_source_data_quality": {"level": "HIGH", "overall_score": 92.2},
            "soft_data": {
                "records": {
                    "gex": {
                        "as_of": "2026-05-29",
                        "data_available": False,
                        "reason": "feature disabled: data_gex",
                    },
                    "btc_funding_basis": {
                        "as_of": "2026-05-29",
                        "data_available": False,
                        "reason": "stale research input",
                    },
                    "aaii": {
                        "as_of": "2026-05-29",
                        "data_available": True,
                    },
                }
            },
            "ibkr": {"source": "disabled"},
        }
        config = {
            "features": {
                "data_gex": False,
                "data_btc_funding": True,
                "data_aaii": True,
            }
        }

        breakdown = _quality_breakdown(payload, {}, {}, config)
        rows = {row["name"]: row for row in breakdown["sources"]}

        self.assertEqual(breakdown["overall_score"], 92.2)
        self.assertEqual(breakdown["strategy_overall_score"], 93.4)
        self.assertEqual(rows["btc_funding_basis"]["decision_role"], "research")
        self.assertEqual(rows["aaii"]["decision_role"], "strategy")
        self.assertFalse(rows["gex"]["decision_bearing"])
        self.assertFalse(rows["btc_funding_basis"]["decision_bearing"])
        self.assertTrue(rows["aaii"]["decision_bearing"])


if __name__ == "__main__":
    unittest.main()
