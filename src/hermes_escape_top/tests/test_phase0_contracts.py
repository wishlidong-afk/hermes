from __future__ import annotations

import unittest
from datetime import date

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.quality import analyze_missing_fields
from hermes_escape_top.core.scoring.result import ScoreResult
from hermes_escape_top.pipeline import empty_score_pipeline


class Phase0ContractsTest(unittest.TestCase):
    def test_field_snapshot_roundtrip(self) -> None:
        snap = SymbolSnapshot(
            symbol="MSTR",
            as_of=date(2026, 5, 29),
            fields={"close": Field("close", 123.45, "unit", date(2026, 5, 29))},
        )
        restored = SymbolSnapshot.from_dict(snap.to_dict())
        self.assertEqual(restored.symbol, "MSTR")
        self.assertEqual(restored.get("close"), 123.45)
        self.assertFalse(restored.is_missing("close"))

    def test_score_result_empty_contract(self) -> None:
        result = ScoreResult.empty("SOXL", date(2026, 5, 29))
        payload = result.to_dict()
        self.assertEqual(payload["status"], "HOLD")
        self.assertEqual(payload["sell_fraction"], 0.0)
        self.assertEqual(set(payload["module_scores"]), {"A", "B", "C", "D"})

    def test_missing_data_not_safe(self) -> None:
        config = load_config()
        missing = analyze_missing_fields(["close"], 0.0, config)
        self.assertTrue(missing.critical_missing)
        self.assertEqual(missing.adjusted_score, 100.0)

    def test_empty_pipeline_deterministic(self) -> None:
        first = empty_score_pipeline("2026-05-29")
        second = empty_score_pipeline("2026-05-29")
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "escape-top-greenfield-phase0-empty-v1")


if __name__ == "__main__":
    unittest.main()
