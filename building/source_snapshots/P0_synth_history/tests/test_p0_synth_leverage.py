from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hermes_escape_top.core.data.manifest import freeze_manifest
from hermes_escape_top.core.data.market import MarketData
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.data.synth_leverage import equal_weight_basket, reconstruct_leveraged_history, validate_synth


def history(start: str, closes: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close,
            "Low": close,
            "Close": close,
            "Adj Close": close,
            "Volume": 100,
        },
        index=idx,
    )


class P0SynthLeverageTest(unittest.TestCase):
    def test_equal_weight_basket_rebalances_deterministically(self) -> None:
        basket = equal_weight_basket(
            {
                "AAA": history("2026-01-01", [100, 101, 102]),
                "BBB": history("2026-01-01", [200, 198, 202]),
            }
        )
        self.assertEqual(len(basket), 3)
        self.assertAlmostEqual(float(basket.iloc[0]), 0.0)
        self.assertAlmostEqual(float(basket.iloc[1]), 0.0, places=6)

    def test_reconstruct_backward_splices_continuously_and_marks_proxy(self) -> None:
        real = history("2026-01-06", [121.0, 122.0])
        dates = pd.bdate_range("2026-01-01", "2026-01-07")
        underlying_ret = pd.Series(0.01, index=dates)
        combined = reconstruct_leveraged_history(
            "AAA",
            2.0,
            underlying_ret,
            real,
            {"start": "2026-01-01", "source": "synth_2x_TEST", "underlying": "TEST", "leverage": 2.0},
        )
        self.assertEqual(combined.index.min().date().isoformat(), "2026-01-01")
        self.assertFalse(bool(combined.loc[pd.Timestamp("2026-01-06"), "is_proxy"]))
        self.assertTrue(bool(combined.loc[pd.Timestamp("2026-01-05"), "is_proxy"]))
        self.assertAlmostEqual(float(combined.loc[pd.Timestamp("2026-01-05"), "Close"]) * 1.02, 121.0)

    def test_validate_synth_reports_corr_and_tracking_error(self) -> None:
        real = history("2026-01-01", [100, 102, 101, 104])
        synth = history("2026-01-01", [100, 102, 101, 104])
        result = validate_synth(real, synth, ("2026-01-01", "2026-01-06"))
        self.assertTrue(result["passed"])
        self.assertAlmostEqual(float(result["tracking_error_annual"]), 0.0)

    def test_manifest_records_proxy_range_and_market_fields_carry_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "AAA.csv"
            csv_path.write_text(
                "date,open,high,low,close,adj_close,volume,is_proxy,source\n"
                "2026-01-01,10,10,10,10,10,0,true,synth_2x_TEST\n"
                "2026-01-02,11,11,11,11,11,100,false,real_history\n",
                encoding="utf-8",
            )
            manifest = freeze_manifest(root)
            entry = manifest.entries["AAA.csv"]
            self.assertEqual(entry.proxy_rows, 1)
            self.assertEqual(entry.proxy_start_date, "2026-01-01")
            cfg = {"paths": {"history_dir": str(root), "legacy_history_dir": str(root), "archive_dir": str(root / "archive")}, "atr": {}}
            store = LocalStore(cfg)
            snap = MarketData(cfg, store).snapshot("AAA", "2026-01-01")
            self.assertTrue(snap.field("close").is_proxy)
            self.assertEqual(snap.field("close").source, "synth_2x_TEST")


if __name__ == "__main__":
    unittest.main()
