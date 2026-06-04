from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RollingNormalizer:
    """Causal rolling transforms used by scoring modules.

    Every value at timestamp T is calculated from observations at or before T.
    Future observations are never read, which keeps offline replay and backtest
    behavior aligned with live execution.
    """

    window: int = 252
    min_periods: int = 60

    def percentile(self, values: pd.Series) -> pd.Series:
        series = _numeric_series(values)

        def rank_last(window_values: pd.Series) -> float:
            valid = window_values.dropna()
            if len(valid) < self.min_periods:
                return float("nan")
            current = valid.iloc[-1]
            return float((valid <= current).sum() / len(valid) * 100.0)

        return series.rolling(self.window, min_periods=self.min_periods).apply(rank_last, raw=False)

    def zscore(self, values: pd.Series) -> pd.Series:
        series = _numeric_series(values)
        rolling = series.rolling(self.window, min_periods=self.min_periods)
        mean = rolling.mean()
        std = rolling.std(ddof=0).replace(0.0, np.nan)
        return (series - mean) / std

    def value_percentile(self, values: pd.Series, as_of: Optional[str] = None) -> Optional[float]:
        series = _numeric_series(values)
        if as_of is not None and isinstance(series.index, pd.DatetimeIndex):
            series = series.loc[series.index <= pd.Timestamp(as_of)]
        ranked = self.percentile(series).dropna()
        if ranked.empty:
            return None
        return float(ranked.iloc[-1])


def to_score(percentile: Optional[float], ladder: Mapping[float, int]) -> Optional[int]:
    """Map a percentile to a discrete score without hiding missing data.

    Example:
        to_score(96, {95: 5, 90: 3, 80: 2}) -> 5
    """

    if percentile is None:
        return None
    if isinstance(percentile, float) and math.isnan(percentile):
        return None
    for threshold, score in sorted(ladder.items(), key=lambda item: float(item[0]), reverse=True):
        if float(percentile) >= float(threshold):
            return int(score)
    return 0


def _numeric_series(values: pd.Series) -> pd.Series:
    if isinstance(values, pd.Series):
        return pd.to_numeric(values, errors="coerce")
    return pd.to_numeric(pd.Series(values), errors="coerce")
