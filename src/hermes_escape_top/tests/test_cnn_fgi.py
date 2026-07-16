from __future__ import annotations

import copy
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.scoring.registry import FactorContext
from hermes_escape_top.core.scoring.scorer import build_registry
from hermes_escape_top.core.data.external_sources.ledger import latest_source_run
from hermes_escape_top.scripts.backfill_cnn_fgi import build


def _on():
    cfg = copy.deepcopy(load_config())
    cfg["features"]["data_cnn_fgi"] = True
    return cfg


def _factor(cfg, fg, pctl=None):
    day = date(2021, 11, 8)
    snaps = {
        "FNGU": SymbolSnapshot("FNGU", day, {"close": Field("close", 100.0, "u", day)}),
        "SOFT": SymbolSnapshot("SOFT", day, {
            "cnn_fear_greed": Field("cnn_fear_greed", fg, "u", day),
            "cnn_fear_greed_pctl": Field("cnn_fear_greed_pctl", pctl, "u", day),
        }),
    }
    factors = build_registry("FNGU", cfg).evaluate(FactorContext(symbol="FNGU", snapshots=snaps, config=cfg))
    return next(f for f in factors if f.factor_id == "A2_CNN_FEAR_GREED")


class CnnFgiFactorTest(unittest.TestCase):
    def test_flag_off_is_placeholder_excluded_from_confidence(self) -> None:
        f = _factor(load_config(), 90.0)  # flag off
        self.assertEqual(f.max_score, 0.0)  # missing_only stub → not in confidence-missing

    def test_extreme_greed_scores_2(self) -> None:
        f = _factor(_on(), 85.0)
        self.assertEqual(f.max_score, 2.0)
        self.assertEqual(f.score, 2.0)

    def test_greed_watch_scores_1(self) -> None:
        self.assertEqual(_factor(_on(), 72.0).score, 1.0)

    def test_fear_scores_0(self) -> None:
        self.assertEqual(_factor(_on(), 10.0).score, 0.0)

    def test_percentile_alone_can_trigger(self) -> None:
        # Raw value mild but percentile extreme → still fires.
        self.assertEqual(_factor(_on(), 60.0, pctl=95.0).score, 2.0)


def test_cnn_research_backfill_promotes_only_through_external_runner(tmp_path: Path) -> None:
    source = tmp_path / "fear-greed.csv"
    target = tmp_path / "soft_history" / "cnn_fear_greed.csv"
    archive = tmp_path / "archive"
    pd.DataFrame(
        {
            "Date": pd.date_range("2026-07-01", periods=3, freq="D"),
            "Fear Greed": [42.0, 55.0, 61.0],
        }
    ).to_csv(source, index=False)

    result = build(str(source), target, archive_dir=archive)

    assert result == target
    assert target.exists()
    ledger = latest_source_run(archive, "cnn_fear_greed_research")
    assert ledger is not None
    assert ledger["status"] == "OK"
    assert ledger["canonical_sha256"]


if __name__ == "__main__":
    unittest.main()
