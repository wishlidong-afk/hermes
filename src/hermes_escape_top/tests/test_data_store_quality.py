from __future__ import annotations

import pandas as pd

from hermes_escape_top.core.data.store import _quality_filter_history


def test_btc_quality_filter_preserves_real_2020_crash_close() -> None:
    dates = pd.to_datetime(["2020-03-11", "2020-03-12", "2020-03-13"])
    frame = pd.DataFrame(
        {
            "Open": [7910.09, 7913.62, 5017.83],
            "High": [7950.81, 7929.12, 5838.11],
            "Low": [7642.81, 4860.35, 4106.98],
            "Close": [7911.43, 4970.79, 5563.71],
            "Volume": [38_682_762_605.0, 53_980_357_243.0, 74_156_772_075.0],
        },
        index=dates,
    )

    filtered = _quality_filter_history("BTC-USD", frame)

    assert list(filtered.index) == list(dates)
    assert float(filtered.loc[pd.Timestamp("2020-03-12"), "Close"]) == 4970.79


def test_btc_quality_filter_still_rejects_non_positive_prices() -> None:
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    frame = pd.DataFrame({"Close": [100000.0, 0.0, -1.0]}, index=dates)

    filtered = _quality_filter_history("BTC-USD", frame)

    assert list(filtered.index) == [dates[0]]
