from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.flow import chaikin_money_flow, money_flow_index, money_flow_metrics
from hermes_escape_top.core.data.network_guard import assert_no_network
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.pipeline import archive_soft_inputs, flow_snapshot


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


if __name__ == "__main__":
    unittest.main()
