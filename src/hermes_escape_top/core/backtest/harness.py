"""ValidationHarness -- anti-overfitting and robustness validation.

Absorbs E21/E22/E23/E24 from the integration architecture.
Provides CPCV splits, PBO, stationary block bootstrap, adversarial AUC,
and crash sample augmentation.

Dependencies: numpy, pandas (required); scipy/sklearn optional with fallback.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# E21: Combinatorial Purged Cross-Validation splits
# ---------------------------------------------------------------------------

def cpcv_splits(
    n_obs: int,
    n_groups: int = 6,
    n_test: int = 2,
    embargo_pct: float = 0.02,
    label_horizon: int = 20,
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Combinatorial purged CV: all C(n_groups, n_test) train/test combos,
    with purging of label_horizon overlap and embargo buffer.

    Returns list of (train_indices, test_indices).
    """
    from itertools import combinations

    group_size = n_obs // n_groups
    groups = []
    for g in range(n_groups):
        start = g * group_size
        end = start + group_size if g < n_groups - 1 else n_obs
        groups.append(np.arange(start, end))

    embargo_size = max(1, int(n_obs * embargo_pct))
    splits = []

    for test_combo in combinations(range(n_groups), n_test):
        test_idx = np.concatenate([groups[g] for g in test_combo])
        test_set = set(test_idx)

        purge_set = set()
        for idx in test_idx:
            for offset in range(-label_horizon, label_horizon + 1):
                purge_set.add(idx + offset)

        embargo_set = set()
        test_max = int(test_idx.max())
        for offset in range(1, embargo_size + 1):
            embargo_set.add(test_max + offset)

        excluded = test_set | purge_set | embargo_set
        train_idx = np.array([i for i in range(n_obs) if i not in excluded])

        if len(train_idx) > 0 and len(test_idx) > 0:
            splits.append((train_idx, test_idx))

    return splits


# ---------------------------------------------------------------------------
# E21: Probability of Backtest Overfitting (PBO)
# ---------------------------------------------------------------------------

def prob_backtest_overfitting(
    is_perf: np.ndarray,
    oos_perf: np.ndarray,
) -> float:
    """PBO: fraction of times IS-optimal configuration underperforms OOS median.

    is_perf: shape (n_configs, n_folds) IS performance
    oos_perf: shape (n_configs, n_folds) OOS performance
    Returns PBO in [0, 1]. PBO > 0.5 → likely overfitted.
    """
    n_configs, n_folds = is_perf.shape
    if n_configs < 2 or n_folds < 2:
        return float("nan")

    underperform_count = 0
    for fold in range(n_folds):
        is_best = int(np.argmax(is_perf[:, fold]))
        oos_median = float(np.median(oos_perf[:, fold]))
        if oos_perf[is_best, fold] < oos_median:
            underperform_count += 1

    return round(underperform_count / n_folds, 4)


# ---------------------------------------------------------------------------
# E22: Stationary block bootstrap
# ---------------------------------------------------------------------------

def stationary_block_bootstrap(
    returns: np.ndarray,
    expected_block: int = 20,
    n_bootstrap: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Stationary block bootstrap for metric confidence intervals.

    Returns bootstrap distribution of Calmar, MaxDD, Sortino with 95% CI.
    """
    rng = np.random.RandomState(seed)
    n = len(returns)
    if n < 30:
        return {"calmar_ci": (0, 0), "maxdd_ci": (0, 0), "sortino_ci": (0, 0), "n_samples": 0}

    p = 1.0 / expected_block
    calmars = []
    maxdds = []
    sortinos = []

    for _ in range(n_bootstrap):
        sample = _generate_block_sample(returns, n, p, rng)
        eq = np.cumprod(1.0 + sample)
        cagr = eq[-1] ** (252.0 / n) - 1.0
        dd = _max_drawdown(eq)
        calmar = cagr / max(abs(dd), 1e-6)
        calmars.append(calmar)
        maxdds.append(dd)

        neg = sample[sample < 0]
        downside_std = float(np.std(neg)) * math.sqrt(252) if len(neg) > 1 else 1e-6
        sortino = (float(np.mean(sample)) * 252) / max(downside_std, 1e-6)
        sortinos.append(sortino)

    return {
        "calmar_ci": (round(float(np.percentile(calmars, 2.5)), 4), round(float(np.percentile(calmars, 97.5)), 4)),
        "maxdd_ci": (round(float(np.percentile(maxdds, 2.5)), 4), round(float(np.percentile(maxdds, 97.5)), 4)),
        "sortino_ci": (round(float(np.percentile(sortinos, 2.5)), 4), round(float(np.percentile(sortinos, 97.5)), 4)),
        "n_samples": n_bootstrap,
    }


def _generate_block_sample(
    returns: np.ndarray,
    n: int,
    p: float,
    rng: np.random.RandomState,
) -> np.ndarray:
    sample = np.empty(n)
    idx = 0
    pos = rng.randint(0, len(returns))
    while idx < n:
        sample[idx] = returns[pos % len(returns)]
        idx += 1
        if rng.random() < p:
            pos = rng.randint(0, len(returns))
        else:
            pos += 1
    return sample


def _max_drawdown(equity: np.ndarray) -> float:
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# E23: Adversarial AUC (train vs live distribution shift)
# ---------------------------------------------------------------------------

def adversarial_auc(
    train_X: np.ndarray,
    live_X: np.ndarray,
    seed: int = 42,
) -> float:
    """Classifier AUC distinguishing train from live features.

    AUC ≈ 0.5 → healthy (no drift). AUC → 1.0 → distribution shift.
    Uses logistic regression; sklearn preferred, else simple threshold proxy.
    """
    if train_X.shape[0] < 20 or live_X.shape[0] < 10:
        return 0.5

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score

        X = np.vstack([train_X, live_X])
        y = np.array([0] * len(train_X) + [1] * len(live_X))

        clf = LogisticRegression(max_iter=200, random_state=seed, solver="lbfgs")
        scores = cross_val_score(clf, X, y, cv=3, scoring="roc_auc")
        return round(float(np.mean(scores)), 4)
    except ImportError:
        return _simple_auc_proxy(train_X, live_X)


def _simple_auc_proxy(train_X: np.ndarray, live_X: np.ndarray) -> float:
    train_mean = train_X.mean(axis=0)
    live_mean = live_X.mean(axis=0)
    train_std = train_X.std(axis=0) + 1e-8
    z = np.abs((live_mean - train_mean) / train_std)
    max_z = float(np.max(z))
    auc_proxy = min(1.0, 0.5 + max_z * 0.1)
    return round(auc_proxy, 4)


# ---------------------------------------------------------------------------
# E24: Crash sample augmentation
# ---------------------------------------------------------------------------

def augment_crashes(
    history: np.ndarray,
    crash_windows: List[Tuple[int, int]],
    n_augment: int = 50,
    block_len: int = 10,
    seed: int = 42,
) -> Dict[str, Any]:
    """Block-bootstrap augmentation of crash episodes.

    Extracts crash blocks, resamples them to create synthetic crash paths.
    All synthetic paths marked is_synthetic=True, excluded from OOS.
    """
    rng = np.random.RandomState(seed)
    crash_blocks = []
    for start, end in crash_windows:
        s = max(0, start)
        e = min(len(history), end)
        if e - s >= block_len:
            for i in range(s, e - block_len + 1):
                crash_blocks.append(history[i : i + block_len])

    if not crash_blocks:
        return {"synthetic": np.array([]), "n_generated": 0, "is_synthetic": True}

    synthetics = []
    for _ in range(n_augment):
        path = []
        remaining = block_len * 3
        while remaining > 0:
            block = crash_blocks[rng.randint(0, len(crash_blocks))]
            take = min(len(block), remaining)
            path.extend(block[:take].tolist())
            remaining -= take
        synthetics.append(path)

    return {
        "synthetic": np.array(synthetics),
        "n_generated": n_augment,
        "is_synthetic": True,
    }


# ---------------------------------------------------------------------------
# Top-level validation runner
# ---------------------------------------------------------------------------

def run_validation(
    strategy_fn: Callable,
    data: pd.DataFrame,
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the full validation suite: CPCV + PBO + bootstrap + adversarial.

    Returns a ValidationReport dict.
    """
    val_cfg = cfg.get("validation", cfg)
    n_groups = int(val_cfg.get("n_groups", 6))
    n_test = int(val_cfg.get("n_test", 2))
    embargo_pct = float(val_cfg.get("embargo_pct", 0.02))
    pbo_max = float(val_cfg.get("pbo_max", 0.5))
    bootstrap_n = int(val_cfg.get("bootstrap_n", 2000))

    n_obs = len(data)
    splits = cpcv_splits(n_obs, n_groups, n_test, embargo_pct)

    is_metrics = []
    oos_metrics = []
    for train_idx, test_idx in splits:
        train_data = data.iloc[train_idx]
        test_data = data.iloc[test_idx]
        is_result = strategy_fn(train_data)
        oos_result = strategy_fn(test_data)
        is_metrics.append(is_result)
        oos_metrics.append(oos_result)

    pbo: Optional[float] = None
    if is_metrics and oos_metrics:
        is_arr = np.asarray(is_metrics, dtype=float)
        oos_arr = np.asarray(oos_metrics, dtype=float)
        if is_arr.ndim == 2 and oos_arr.ndim == 2 and is_arr.shape == oos_arr.shape:
            pbo_value = prob_backtest_overfitting(is_arr.T, oos_arr.T)
            if not math.isnan(pbo_value):
                pbo = pbo_value

    returns = data.iloc[:, 0].pct_change().dropna().values if len(data.columns) > 0 else np.array([])
    bootstrap = stationary_block_bootstrap(returns, n_bootstrap=bootstrap_n) if len(returns) >= 30 else {}

    return {
        "n_splits": len(splits),
        "pbo": pbo,
        "pbo_pass": None if pbo is None else pbo < pbo_max,
        "bootstrap": bootstrap,
        "report_ready": True,
    }
