from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.adapters import collect_soft_data, default_sources
from hermes_escape_top.core.data.network_guard import assert_no_network
from hermes_escape_top.core.data.risk_signals import FredPercentileSource, fetch_fred_series_frame
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.pipeline import soft_data_snapshot


class Phase10AdapterTest(unittest.TestCase):
    def test_default_sources_return_missing_contracts(self) -> None:
        config = load_config()
        patched = json.loads(json.dumps(config))
        for key in ["data_gex", "data_skew_vvix", "data_net_liquidity", "data_aaii", "data_naaim", "data_cboe_pcr", "data_component_breadth", "data_btc_funding"]:
            patched["features"][key] = False
        names = [source.name for source in default_sources()]
        self.assertEqual(set(names), {"gex", "cboe_indices", "net_liquidity", "aaii", "naaim", "cboe_pcr", "component_breadth", "btc_funding_basis"})
        for source in default_sources():
            record = source.collect("2026-05-29", patched)
            self.assertFalse(record.data_available)
            self.assertIsNone(record.value)

    def test_collect_soft_data_writes_dated_snapshot_without_network(self) -> None:
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            patched = json.loads(json.dumps(config))
            patched["paths"]["archive_dir"] = tmp
            patched["paths"]["history_dir"] = tmp
            patched["paths"]["legacy_history_dir"] = tmp
            store = LocalStore(patched)
            with assert_no_network():
                payload = collect_soft_data("2026-05-29", patched, store)
            self.assertTrue(Path(payload["path"]).exists())
            self.assertIn("gex", payload["records"])

    def test_cli_pipeline_soft_data_snapshot(self) -> None:
        payload = soft_data_snapshot("2026-05-29")
        self.assertIn("records", payload)
        self.assertIn("net_liquidity", payload["records"])

    def test_fred_api_frame_publish_date_is_observation_date_plus_one(self) -> None:
        # realtime_start on FRED's observations endpoint is the query date for
        # every row; using it stamps the series with one future date and breaks
        # asof_pick (the 2026-06-13 real_rate/dollar outage). publish_date must be
        # the observation date + 1 (next-day release), per row.
        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({
                    "observations": [
                        {"date": "2026-06-05", "realtime_start": "2026-06-17", "value": "1.25"},
                        {"date": "2026-06-12", "realtime_start": "2026-06-24", "value": "1.35"},
                    ]
                }).encode("utf-8")

        with mock.patch("hermes_escape_top.core.data.risk_signals.fred_api_key", return_value="key"), mock.patch("hermes_escape_top.core.data.risk_signals.urlopen", return_value=FakeResponse()):
            frame = fetch_fred_series_frame("DFII10", start="2026-06-01", end="2026-06-30")

        # date+1, deliberately NOT the realtime_start values (06-17 / 06-24)
        self.assertEqual(frame["publish_date"].dt.date.astype(str).tolist(), ["2026-06-06", "2026-06-13"])

    def test_fred_percentile_source_preserves_fetched_publish_date(self) -> None:
        # build_frame must carry through the publish_date from fetch_fred_series_frame
        # (date+1), not recompute or drop it.
        raw = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-05", "2026-06-12"]),
                "publish_date": pd.to_datetime(["2026-06-06", "2026-06-13"]),
                "value": [1.25, 1.35],
            }
        )
        source = FredPercentileSource("real_rate", "data_real_rate", "DFII10", "real_rate_10y", window=2, min_periods=1)
        with mock.patch("hermes_escape_top.core.data.risk_signals.fetch_fred_series_frame", return_value=raw):
            frame = source.build_frame()

        self.assertEqual(frame["publish_date"].dt.date.astype(str).tolist(), ["2026-06-06", "2026-06-13"])
        self.assertEqual(frame["real_rate_10y_pctl"].tolist(), [100.0, 100.0])


if __name__ == "__main__":
    unittest.main()
