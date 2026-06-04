from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WalkForwardSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray
    train_start: str
    train_end: str
    test_start: str
    test_end: str


def purged_kfold_indices(n_samples: int, n_splits: int = 5, purge: int = 0, embargo: int = 0) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    indices = np.arange(n_samples)
    folds = np.array_split(indices, n_splits)
    for test in folds:
        if len(test) == 0:
            continue
        start, end = int(test[0]), int(test[-1])
        train_mask = np.ones(n_samples, dtype=bool)
        left = max(0, start - purge)
        right = min(n_samples, end + embargo + 1)
        train_mask[left:right] = False
        yield indices[train_mask], test


def walk_forward_splits(
    dates,
    is_years: int = 2,
    oos_months: int = 6,
    step_months: int = 6,
    label_horizon: int = 20,
    embargo_pct: float = 0.02,
) -> list[WalkForwardSplit]:
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates))).sort_values()
    if idx.empty:
        return []
    out: list[WalkForwardSplit] = []
    start = idx[0]
    end = idx[-1]
    train_delta = pd.DateOffset(years=is_years)
    test_delta = pd.DateOffset(months=oos_months)
    step_delta = pd.DateOffset(months=step_months)
    embargo = max(label_horizon, int(round(len(idx) * embargo_pct)))
    train_start = start
    while True:
        train_end = train_start + train_delta
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + test_delta
        if test_start > end:
            break
        train_mask = (idx >= train_start) & (idx <= train_end)
        test_mask = (idx >= test_start) & (idx <= min(test_end, end))
        train_positions = np.flatnonzero(train_mask)
        test_positions = np.flatnonzero(test_mask)
        if len(train_positions) and len(test_positions):
            left = max(0, int(test_positions[0]) - int(label_horizon))
            right = min(len(idx), int(test_positions[-1]) + embargo + 1)
            keep = np.ones(len(train_positions), dtype=bool)
            for pos_i, pos in enumerate(train_positions):
                if left <= pos < right:
                    keep[pos_i] = False
            purged_train = train_positions[keep]
            if len(purged_train):
                out.append(
                    WalkForwardSplit(
                        purged_train,
                        test_positions,
                        idx[purged_train[0]].date().isoformat(),
                        idx[purged_train[-1]].date().isoformat(),
                        idx[test_positions[0]].date().isoformat(),
                        idx[test_positions[-1]].date().isoformat(),
                    )
                )
        train_start = train_start + step_delta
    return out


def deflated_sharpe_ratio(sharpe: float, trials: int, observations: int) -> float:
    if observations <= 1:
        return 0.0
    penalty = math.sqrt(2.0 * math.log(max(1, trials))) / math.sqrt(observations - 1)
    return float(sharpe - penalty)


def deflated_sharpe(returns, n_trials: int, skew: float = 0.0, kurt: float = 3.0) -> float:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) <= 1:
        return 0.0
    std = float(values.std(ddof=0))
    if std <= 0:
        return 0.0
    sharpe = float(values.mean() / std * math.sqrt(252))
    # Conservative small-sample correction. Skew/kurtosis increase the penalty
    # when the return stream is asymmetric or fat-tailed.
    shape_penalty = max(0.0, abs(float(skew)) * 0.05 + max(0.0, float(kurt) - 3.0) * 0.02)
    return deflated_sharpe_ratio(sharpe - shape_penalty, trials=n_trials, observations=len(values))


def leakage_gap_score(labels: np.ndarray, ordinary_scores: np.ndarray, purged_scores: np.ndarray) -> float:
    # A simple diagnostic: positive means ordinary validation was more optimistic.
    if len(ordinary_scores) == 0 or len(purged_scores) == 0:
        return 0.0
    return float(np.nanmean(ordinary_scores) - np.nanmean(purged_scores))
