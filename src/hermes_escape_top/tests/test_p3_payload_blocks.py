"""P3 (T22/T23/T24): risk contributions, stress scenarios, routing context."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from hermes_escape_top.pipeline import _risk_contribution_block, _stress_block


def _risk_state():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    return SimpleNamespace(cov=cov, legs_used=["AAA", "BBB"],
                           leg_vol={"AAA": 0.2, "BBB": 0.3})


def test_risk_contributions_sum_to_portfolio_vol():
    out = _risk_contribution_block(_risk_state(), {"AAA": 0.5, "BBB": 0.5})
    port = out["_portfolio"]["forecast_vol"]
    total = out["AAA"]["vol_contribution"] + out["BBB"]["vol_contribution"]
    assert abs(total - port) < 1e-6
    pct = out["AAA"]["vol_contribution_pct"] + out["BBB"]["vol_contribution_pct"]
    assert abs(pct - 1.0) < 1e-6
    assert "_error" not in out


def test_stress_block_scenarios_and_corr_regime():
    idx = pd.date_range("2026-01-01", periods=90, freq="B")
    rng = np.random.RandomState(7)
    base = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 90)), index=idx)
    histories = {
        "QQQ": pd.DataFrame({"Close": base}),
        "AAA": pd.DataFrame({"Close": base * (1 + rng.normal(0, 0.002, 90))}),
        "BBB": pd.DataFrame({"Close": base.iloc[::-1].values}, index=idx),
    }
    out = _stress_block(_risk_state(), {"AAA": 0.5, "BBB": 0.5}, histories)
    names = [s["name"] for s in out]
    assert "QQQ -5%" in names
    assert any("0.9" in n for n in names)
    corr = next(s for s in out if s["name"].startswith("correlation"))
    assert corr["forecast_vol_after"] > corr["forecast_vol_before"]  # corr up => vol up
    assert all("_error" not in s for s in out)


def test_blocks_never_raise_on_garbage():
    assert _risk_contribution_block(SimpleNamespace(legs_used=[]), {}) == {}
    assert _stress_block(SimpleNamespace(legs_used=[]), {}, {}) == []
