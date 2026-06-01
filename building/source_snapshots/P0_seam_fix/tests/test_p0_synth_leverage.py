from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from hermes_escape_top.core.data.manifest import freeze_manifest
from hermes_escape_top.core.data.market import MarketData
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.data.synth_leverage import equal_weight_basket, reconstruct_leveraged_history, validate_synth
from hermes_escape_top.core.data.wso_index import fetch_wso_index, parse_wso_chart_payload
from hermes_escape_top.scripts.build_synth_history import DEFAULT_SPECS


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

    def test_wso_index_payload_parser_skips_null_rows_and_dates_to_us_session(self) -> None:
        payload = {
            "data": [
                [0, 100.0, 101.0, 99.0, 100.5, 0, 1586815200],
                [1, None],
                [2, 101.0, 103.0, 100.0, 102.5, 0, 1586901600],
            ]
        }
        frame = parse_wso_chart_payload(payload, "FANG3X")
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.index.min().date().isoformat(), "2020-04-14")
        self.assertAlmostEqual(float(frame["Close"].iloc[-1]), 102.5)

    def test_fetch_wso_index_uses_declared_endpoint_without_live_network(self) -> None:
        calls = []

        def fake_get(url, params, headers):
            calls.append((url, params, headers))
            return {"data": [[0, 100.0, 101.0, 99.0, 100.5, 0, 1586815200]]}

        result = fetch_wso_index("FANG3X", http_get=fake_get)
        self.assertEqual(result.symbol, "FANG3X")
        self.assertEqual(len(result.frame), 1)
        self.assertEqual(calls[0][1]["q[instId]"], "341241317")

    def test_default_specs_contain_seam_days(self) -> None:
        for symbol in ("FNGU", "FNGS"):
            self.assertIn("seam_days", DEFAULT_SPECS[symbol], f"{symbol} missing seam_days")
            self.assertIsInstance(DEFAULT_SPECS[symbol]["seam_days"], int)
            self.assertGreater(DEFAULT_SPECS[symbol]["seam_days"], 0)

    def test_seam_adjusted_gate_passes_when_seam_period_excluded(self) -> None:
        # Build a scenario where the first N days have large divergence and the
        # remainder tracks perfectly.  Verify that validate_synth passes when the
        # seam period is excluded but fails when the full window is used.
        seam_days = 10
        n_stable = 50
        n_total = seam_days + n_stable
        dates = pd.bdate_range("2025-01-01", periods=n_total)

        # Real: seam period has large random noise; stable period tracks 3x exactly.
        import numpy as np
        rng = np.random.default_rng(42)
        seam_close = 100.0 * (1.0 + rng.uniform(-0.05, 0.05, seam_days)).cumprod()
        stable_base = seam_close[-1]
        stable_ret = rng.normal(0.001, 0.002, n_stable)
        stable_close = stable_base * (1.0 + stable_ret).cumprod()
        real_closes = list(seam_close) + list(stable_close)
        real_df = pd.DataFrame(
            {"Open": real_closes, "High": real_closes, "Low": real_closes,
             "Close": real_closes, "Adj Close": real_closes, "Volume": 1.0},
            index=dates,
        )

        # Synth: matches real exactly from the stable period (seam period differs).
        seam_synth_close = 100.0 * (1.0 + rng.uniform(-0.05, 0.05, seam_days)).cumprod()
        synth_closes = list(seam_synth_close) + list(stable_close)
        synth_df = pd.DataFrame(
            {"Open": synth_closes, "High": synth_closes, "Low": synth_closes,
             "Close": synth_closes, "Adj Close": synth_closes, "Volume": 1.0},
            index=dates,
        )

        start = dates[0].date().isoformat()
        end = dates[-1].date().isoformat()
        stable_start = dates[seam_days].date().isoformat()

        full_result = validate_synth(real_df, synth_df, (start, end))
        seam_adj_result = validate_synth(real_df, synth_df, (stable_start, end))

        # Full window should fail TE gate due to seam divergence.
        self.assertFalse(full_result["pass_tracking_error"],
                         "Expected full-window TE gate to fail due to seam noise")
        # Seam-adjusted window should pass TE gate.
        self.assertTrue(seam_adj_result["pass_tracking_error"],
                        f"Expected seam-adjusted TE gate to pass; got TE={seam_adj_result['tracking_error_annual']:.4f}")


if __name__ == "__main__":
    unittest.main()
