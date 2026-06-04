"""Tests for Audit Exporter -- JSON, Markdown, and signal journal export."""

from __future__ import annotations

import json
import unittest

from hermes_escape_top.core.audit.exporter import (
    build_signal_entry,
    export_json,
    export_markdown,
    export_signal_journal,
)


def _sample_audit() -> dict:
    return {
        "as_of": "2026-06-01",
        "timestamp": "2026-06-01T18:00:00",
        "symbols": ["MSTR", "FNGU", "SOXL"],
        "scores_summary": {"MSTR": 65, "FNGU": 30, "SOXL": 25},
        "verdicts_summary": {
            "MSTR": {"status": "DEFENSIVE_EXIT", "rule_weight": 0.0375},
            "FNGU": {"status": "WATCH", "rule_weight": 0.20},
            "SOXL": {"status": "HOLD", "rule_weight": 0.30},
        },
        "risk_summary": {
            "portfolio_vol": 0.28,
            "gross_scaler": 0.85,
            "corr_regime": "NORMAL",
            "binding": "VOL",
        },
        "confidence": {
            "decision_confidence": 0.82,
            "mode": "NORMAL",
            "weakest_link": "data",
        },
        "sizing_summary": {
            "target_weights": {"MSTR": 0.03, "FNGU": 0.15, "SOXL": 0.25},
            "binding_constraint": {"MSTR": "R3_RULE", "FNGU": "VOL_BUDGET", "SOXL": "NONE"},
            "confidence_applied": 0.82,
        },
        "regime": {"MSTR": "NORMAL", "FNGU": "LOW_VOL_TREND", "SOXL": "NORMAL"},
        "fragility": {"MSTR": 0.15, "FNGU": 0.05, "SOXL": 0.02},
        "disagreement": {"MSTR": 0.10, "FNGU": 0.0, "SOXL": 0.0},
        "drift": {"psi": 0.08, "alert": False},
    }


class TestExportJson(unittest.TestCase):
    def test_valid_json(self) -> None:
        output = export_json(_sample_audit())
        parsed = json.loads(output)
        self.assertEqual(parsed["as_of"], "2026-06-01")

    def test_all_fields_present(self) -> None:
        output = export_json(_sample_audit())
        parsed = json.loads(output)
        for key in ("scores_summary", "verdicts_summary", "risk_summary", "confidence", "sizing_summary"):
            self.assertIn(key, parsed)


class TestExportMarkdown(unittest.TestCase):
    def test_contains_header(self) -> None:
        md = export_markdown(_sample_audit())
        self.assertIn("# Hermes Daily Audit", md)
        self.assertIn("2026-06-01", md)

    def test_contains_all_sections(self) -> None:
        md = export_markdown(_sample_audit())
        for section in ("## Scores", "## Verdicts", "## Risk", "## Confidence", "## Target Weights", "## Regime", "## Drift"):
            self.assertIn(section, md)

    def test_symbols_in_tables(self) -> None:
        md = export_markdown(_sample_audit())
        self.assertIn("MSTR", md)
        self.assertIn("FNGU", md)
        self.assertIn("SOXL", md)

    def test_confidence_mode_bold(self) -> None:
        md = export_markdown(_sample_audit())
        self.assertIn("**NORMAL**", md)


class TestSignalJournal(unittest.TestCase):
    def test_entry_has_required_fields(self) -> None:
        entry = build_signal_entry(
            "2026-06-01", "MSTR", "DEFENSIVE_EXIT", 65.0, 0.75,
            ["H-M1"], 0.03, "NORMAL",
        )
        for key in ("as_of", "symbol", "status", "score", "sell_fraction", "target_weight", "confidence_mode"):
            self.assertIn(key, entry)

    def test_jsonl_format(self) -> None:
        entries = [
            build_signal_entry("2026-06-01", "MSTR", "EXIT", 80, 1.0, ["H-M1"], 0.0, "NORMAL"),
            build_signal_entry("2026-06-01", "FNGU", "HOLD", 15, 0.0, [], 0.20, "NORMAL"),
        ]
        output = export_signal_journal(entries)
        lines = output.strip().split("\n")
        self.assertEqual(len(lines), 2)
        for line in lines:
            parsed = json.loads(line)
            self.assertIn("symbol", parsed)


if __name__ == "__main__":
    unittest.main()
