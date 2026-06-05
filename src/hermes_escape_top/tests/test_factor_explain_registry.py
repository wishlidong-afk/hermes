from __future__ import annotations

import unittest
from unittest import mock

from hermes_escape_top.core.scoring.explain_registry import explain_factor
from hermes_escape_top.pipeline import score_pipeline


class FactorExplainRegistryTest(unittest.TestCase):
    def test_known_factor_has_three_explain_fields(self) -> None:
        meta = explain_factor("A1_QQQ_MA200_BREAK", "A")
        self.assertIn("MA200", meta["professional_explain"])
        self.assertIn("纳指", meta["plain_explain"])
        self.assertIn("QQQ", meta["data_hint"])

    def test_unknown_factor_uses_module_fallback(self) -> None:
        meta = explain_factor("C99_UNIT_TEST", "C")
        self.assertIn("技术结构", meta["professional_explain"])
        self.assertIn("盘面结构", meta["plain_explain"])
        self.assertIn("均线", meta["data_hint"])

    def test_pipeline_factor_rows_include_explain_registry_fields(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        row = payload["scores"]["SOXL"]["factor_scores"]["A"][0]
        self.assertIn("professional_explain", row)
        self.assertIn("plain_explain", row)
        self.assertIn("data_hint", row)


if __name__ == "__main__":
    unittest.main()
