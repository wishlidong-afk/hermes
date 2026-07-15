from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hermes_escape_top.core.features.indicators import indicator_frame
from hermes_escape_top.core.features.volatility import returns_from


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_indicator_and_volatility_returns_do_not_fill_missing_prices():
    prices = pd.Series([100.0, np.nan, 110.0])
    frame = pd.DataFrame({"Close": prices})

    indicators = indicator_frame(frame)
    volatility_returns = returns_from(prices)

    assert indicators["return_1d"].isna().tolist() == [True, True, True]
    assert volatility_returns.isna().tolist() == [True, True, True]
    assert indicators["return_2d"].iloc[-1] == pytest.approx(0.10)


def test_all_production_pct_change_calls_declare_fill_semantics():
    missing: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "pct_change":
                continue
            if not any(keyword.arg == "fill_method" for keyword in node.keywords):
                missing.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")

    assert missing == [], "pct_change must explicitly declare fill_method: " + ", ".join(missing)
