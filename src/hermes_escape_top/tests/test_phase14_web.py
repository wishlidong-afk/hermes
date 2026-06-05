from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.web.render import render_dashboard, write_dashboard


class Phase14WebTest(unittest.TestCase):
    def test_render_dashboard_contains_core_sections(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        html = render_dashboard(payload)
        self.assertIn("Escape Decisions", html)
        self.assertIn("System Health", html)
        self.assertIn("Audit Detail", html)
        self.assertIn("Portfolio Risk", html)
        self.assertIn("Mirror Reference", html)
        self.assertIn("IBKR Live 验收", html)
        self.assertIn("更新持仓", html)
        self.assertIn("IBKR 现有总资产", html)
        self.assertIn("宏观 A 模块评分", html)
        self.assertIn("底层持仓资金流入/流出监控", html)

    def test_write_dashboard_file(self) -> None:
        with mock.patch("hermes_escape_top.pipeline._ibkr_payload", return_value={"source": "disabled"}):
            payload = score_pipeline("2026-05-29")
        with tempfile.TemporaryDirectory() as tmp:
            path = write_dashboard(payload, Path(tmp) / "dashboard.html")
            self.assertTrue(path.exists())
            self.assertIn("Hermes Escape Top", path.read_text())


if __name__ == "__main__":
    unittest.main()
