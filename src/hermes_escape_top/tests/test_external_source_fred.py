from __future__ import annotations

import pandas as pd

from hermes_escape_top.core.data.external_sources.fred import (
    FredNetLiquidityAdapter,
    fred_net_liquidity_spec,
    FredPercentileAdapter,
    fred_percentile_spec,
)
from hermes_escape_top.core.data.external_sources.ledger import latest_source_run
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh


def test_fred_percentile_adapter_promotes_existing_soft_history_shape(tmp_path):
    def fetch_frame(series_id, start="1990-01-01", end=None, config=None):
        assert series_id == "DTWEXBGS"
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"]),
                "publish_date": pd.to_datetime(["2026-06-02", "2026-06-03", "2026-06-04"]),
                "value": [100.0, 101.0, 102.0],
            }
        )

    target = tmp_path / "soft_history" / "dollar.csv"
    spec = fred_percentile_spec(
        source_id="dollar",
        target_path=target,
        field="dollar_broad",
    )
    adapter = FredPercentileAdapter(
        series_id="DTWEXBGS",
        field="dollar_broad",
        window=2,
        min_periods=1,
        fetch_frame=fetch_frame,
    )

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    assert run.status == "OK"
    assert list(out.columns) == ["date", "publish_date", "dollar_broad", "dollar_broad_pctl"]
    assert out["publish_date"].tolist() == ["2026-06-02", "2026-06-03", "2026-06-04"]
    assert out["dollar_broad"].tolist() == [100.0, 101.0, 102.0]
    assert out["dollar_broad_pctl"].round(2).tolist() == [100.0, 100.0, 100.0]
    assert latest_source_run(tmp_path / "archive", "dollar")["latest_promoted_as_of"] == "2026-06-03"


def test_fred_net_liquidity_adapter_promotes_existing_soft_history_shape(tmp_path):
    dates = pd.date_range("2026-01-01", periods=70, freq="D")

    def fetch_series(series_id, start="2015-01-01", end=None):
        base = {"WALCL": 8_000_000, "WTREGEN": 500_000, "RRPONTSYD": 1_000_000}[series_id]
        return pd.Series([base + i * 1000 for i in range(len(dates))], index=dates)

    target = tmp_path / "soft_history" / "fred_net_liquidity.csv"
    spec = fred_net_liquidity_spec(target_path=target)
    adapter = FredNetLiquidityAdapter(fetch_series=fetch_series, percentile_window=60, start="2026-01-01")

    run = run_external_source_refresh(spec, adapter, tmp_path / "archive")

    out = pd.read_csv(target)
    assert run.status == "OK"
    assert list(out.columns) == [
        "date",
        "publish_date",
        "walcl",
        "wtregen",
        "rrp",
        "net_liq",
        "net_liq_chg10",
        "net_liq_chg10_pctl",
    ]
    assert out["publish_date"].iloc[-1] == "2026-03-12"
    assert out["net_liq"].iloc[-1] > 0
    assert latest_source_run(tmp_path / "archive", "fred_net_liquidity")["latest_promoted_as_of"] == "2026-03-11"
