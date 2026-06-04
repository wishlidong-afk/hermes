from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.adapters import collect_soft_data, default_sources
from hermes_escape_top.core.data.network_guard import assert_no_network
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


if __name__ == "__main__":
    unittest.main()
