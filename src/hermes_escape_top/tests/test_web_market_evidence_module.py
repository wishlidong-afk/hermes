from __future__ import annotations

import ast
import importlib
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PACKAGE_ROOT / "web" / "market_evidence.py"
SERVER_PATH = PACKAGE_ROOT / "web" / "server.py"


def test_market_admission_selection_lives_in_focused_web_module():
    assert MODULE_PATH.exists(), "market-admission evidence selection is still embedded in server.py"
    module = importlib.import_module("hermes_escape_top.web.market_evidence")
    assert callable(module.attach_market_admission_status)

    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    wrapper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_attach_market_admission_status"
    )
    assert wrapper.end_lineno - wrapper.lineno + 1 <= 8
