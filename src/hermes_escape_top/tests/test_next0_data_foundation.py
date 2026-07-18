from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from hermes_escape_top.core.data.manifest import verify_manifest, write_manifest
from hermes_escape_top.core.data.pit import asof_pick
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.routing.leg_proxy import leg_price_series, leg_proxy_metadata
from hermes_escape_top.scripts.backfill_history import backfill


def frame(start: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    close = pd.Series(closes, index=dates)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Adj Close": close,
            "Volume": 1000,
        },
        index=dates,
    )


class Next0DataFoundationTest(unittest.TestCase):
    def test_asof_pick_uses_publish_date_not_future_period(self) -> None:
        records = [(date(2026, 1, 8), "published"), (date(2026, 1, 15), "future")]
        self.assertIsNone(asof_pick(records, date(2026, 1, 7)))
        self.assertEqual(asof_pick(records, date(2026, 1, 8)), "published")
        self.assertEqual(asof_pick(records, date(2026, 1, 14)), "published")
        self.assertEqual(asof_pick(records, date(2026, 1, 15)), "future")
        self.assertIsNone(asof_pick([(date(2026, 1, 8), "lagged")], date(2026, 1, 8), publish_lag_days=1))

    def test_manifest_freeze_and_verify_detects_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "AAA.csv"
            data.write_text("date,open,high,low,close,adj_close,volume\n2026-01-01,1,1,1,1,1,10\n", encoding="utf-8")
            manifest = root / "manifest.json"
            write_manifest(root, manifest)
            self.assertTrue(verify_manifest(root, manifest))
            data.write_text("date,open,high,low,close,adj_close,volume\n2026-01-01,1,1,1,2,2,10\n", encoding="utf-8")
            self.assertFalse(verify_manifest(root, manifest))

    def test_backfill_idempotent_append_and_store_reads_lowercase_schema(self) -> None:
        calls: list[tuple[str, str, str | None]] = []

        def downloader(symbol: str, start: str, end: str | None) -> pd.DataFrame:
            calls.append((symbol, start, end))
            if start >= "2026-01-05":
                return pd.DataFrame()
            return frame(start, [100, 101])

        with tempfile.TemporaryDirectory() as tmp:
            first = backfill(["AAA"], start="2026-01-01", end="2026-01-03", store_dir=tmp, downloader=downloader)
            second = backfill(["AAA"], start="2026-01-01", end="2026-01-03", store_dir=tmp, downloader=downloader)
            self.assertTrue(first["AAA"].updated)
            self.assertFalse(second["AAA"].updated)
            cfg = {"paths": {"history_dir": tmp, "legacy_history_dir": tmp, "archive_dir": str(Path(tmp) / "archive")}}
            history = LocalStore(cfg).load_history("AAA")
            self.assertIn("Close", history.columns)
            self.assertEqual(float(history["Close"].iloc[-1]), 101.0)
            self.assertEqual(len(calls), 1)

    def test_backfill_repairs_head_gap_before_existing_inception(self) -> None:
        calls: list[tuple[str, str, str | None]] = []

        def downloader(symbol: str, start: str, end: str | None) -> pd.DataFrame:
            calls.append((symbol, start, end))
            return frame(start, [90, 91])

        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "AAA.csv"
            existing.write_text(
                "date,open,high,low,close,adj_close,volume\n2026-01-05,100,101,99,100,100,10\n",
                encoding="utf-8",
            )
            result = backfill(
                ["AAA"],
                start="2026-01-01",
                end="2026-01-05",
                store_dir=tmp,
                downloader=downloader,
                repair_history_head=True,
            )
            self.assertTrue(result["AAA"].updated)
            self.assertEqual(calls[0][1], "2026-01-01")
            self.assertEqual(calls[0][2], "2026-01-05")
            history = LocalStore({"paths": {"history_dir": tmp, "legacy_history_dir": tmp, "archive_dir": str(Path(tmp) / "archive")}}).load_history("AAA")
            self.assertEqual(history.index.min().date().isoformat(), "2026-01-01")

    def test_route_leg_proxy_splices_without_switch_jump(self) -> None:
        dates = pd.bdate_range("2022-12-28", periods=5)
        histories = {
            "BIL": frame("2022-12-28", [100, 100.1, 100.2, 100.3, 100.4]),
            "BOXX": frame("2022-12-28", [50, 50.1, 50.2, 50.3, 50.4]),
        }
        series = leg_price_series("BOXX", dates, histories)
        self.assertEqual(len(series), len(dates))
        self.assertAlmostEqual(float(series.iloc[0]), 100.0)
        self.assertLess(float(series.diff().abs().dropna().max()), 1.0)
        meta = leg_proxy_metadata("BOXX", dates)
        self.assertTrue(bool(meta["is_proxy"].iloc[0]))
        self.assertFalse(bool(meta["is_proxy"].iloc[-1]))


if __name__ == "__main__":
    unittest.main()
