from __future__ import annotations

import pandas as pd

from hermes_escape_top.core.data.external_sources.fred import FredPercentileAdapter, fred_percentile_spec
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
