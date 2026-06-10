"""FactorLab -- factor IC monitoring, deduplication, pruning, and probability calibration.

Absorbs E2/E3/E23 from the integration architecture.
Provides the statistical backbone for score → probability conversion and
factor health monitoring (dead factor detection, redundancy weighting).

Dependencies: numpy, pandas (required); scipy/sklearn optional with fallback.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------

def build_panel(replay_results: List[Dict[str, Any]]) -> pd.DataFrame:
    """Build a date × factor_id score panel from replay results.

    Each replay_result dict must have 'date' and 'factors' (dict of factor_id→score).
    Returns a DataFrame with dates as index and factor_ids as columns.
    """
    if not replay_results:
        return pd.DataFrame()

    rows = []
    for r in replay_results:
        row = {"date": r["date"]}
        row.update(r.get("factors", {}))
        rows.append(row)

    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
    return df


# ---------------------------------------------------------------------------
# E3: Factor IC (Information Coefficient)
# ---------------------------------------------------------------------------

def factor_ic(
    panel: pd.DataFrame,
    fwd_outcome: pd.Series,
    method: str = "spearman",
) -> Dict[str, Dict[str, float]]:
    """Compute per-factor IC (Spearman rank correlation with forward outcome).

    Returns {factor_id: {"ic": float, "t_stat": float, "status": "alive"|"dead"}}.
    A factor with |IC| < dead_threshold is marked dead.
    """
    dead_threshold = 0.02
    result = {}

    aligned = panel.join(fwd_outcome.rename("_outcome"), how="inner").dropna(subset=["_outcome"])
    if len(aligned) < 20:
        for col in panel.columns:
            result[col] = {"ic": 0.0, "t_stat": 0.0, "status": "dead"}
        return result

    outcome = aligned["_outcome"]
    for col in panel.columns:
        if col == "_outcome":
            continue
        factor_vals = aligned[col].dropna()
        common = factor_vals.index.intersection(outcome.index)
        if len(common) < 20:
            result[col] = {"ic": 0.0, "t_stat": 0.0, "status": "dead"}
            continue

        x = factor_vals.loc[common].values
        y = outcome.loc[common].values

        if method == "spearman":
            ic = _spearman_corr(x, y)
        else:
            ic = _pearson_corr(x, y)

        n = len(common)
        t_stat = ic * math.sqrt((n - 2) / max(1.0 - ic ** 2, 1e-12)) if abs(ic) < 1.0 else 0.0
        status = "alive" if abs(ic) >= dead_threshold else "dead"

        result[col] = {"ic": round(ic, 6), "t_stat": round(t_stat, 4), "status": status}

    return result


# ---------------------------------------------------------------------------
# E3: Cluster and prune (redundancy weighting)
# ---------------------------------------------------------------------------

def cluster_and_prune(
    panel: pd.DataFrame,
    ic_results: Dict[str, Dict[str, float]],
    corr_threshold: float = 0.80,
) -> Dict[str, float]:
    """Hierarchical clustering by correlation distance; within each cluster,
    keep the highest-IC factor at weight 1.0, demote others.

    Returns {factor_id: weight_multiplier}.

    Uses scipy if available, else greedy correlation-threshold clustering.
    """
    factors = [c for c in panel.columns if c in ic_results and ic_results[c]["status"] == "alive"]
    if not factors:
        return {c: 0.0 for c in panel.columns}

    if len(factors) == 1:
        result = {c: 0.0 for c in panel.columns}
        result[factors[0]] = 1.0
        return result

    sub = panel[factors].dropna()
    if len(sub) < 20:
        return {c: 1.0 for c in panel.columns}

    corr_mat = sub.corr().values
    abs_corr = np.abs(corr_mat)

    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        dist = 1.0 - abs_corr
        np.fill_diagonal(dist, 0.0)
        condensed = dist[np.triu_indices_from(dist, k=1)]
        Z = linkage(condensed, method="average")
        labels = fcluster(Z, t=1.0 - corr_threshold, criterion="distance")
    except ImportError:
        labels = _greedy_cluster(abs_corr, corr_threshold)

    clusters: Dict[int, List[int]] = {}
    for i, lab in enumerate(labels):
        clusters.setdefault(lab, []).append(i)

    weights = {c: 0.0 for c in panel.columns}
    for _, members in clusters.items():
        member_factors = [factors[m] for m in members]
        best = max(member_factors, key=lambda f: abs(ic_results[f]["ic"]))
        for f in member_factors:
            weights[f] = 1.0 if f == best else 0.3
    return weights


def _greedy_cluster(abs_corr: np.ndarray, threshold: float) -> np.ndarray:
    n = abs_corr.shape[0]
    labels = np.zeros(n, dtype=int)
    current_label = 0
    assigned = set()
    for i in range(n):
        if i in assigned:
            continue
        current_label += 1
        labels[i] = current_label
        assigned.add(i)
        for j in range(i + 1, n):
            if j not in assigned and abs_corr[i, j] >= threshold:
                labels[j] = current_label
                assigned.add(j)
    for i in range(n):
        if labels[i] == 0:
            current_label += 1
            labels[i] = current_label
    return labels


# ---------------------------------------------------------------------------
# E2: Score probability calibration (isotonic regression)
# ---------------------------------------------------------------------------

def calibrate_score(
    scores: np.ndarray,
    fwd_dd: np.ndarray,
    dd_threshold: float,
) -> Dict[str, Any]:
    """Isotonic regression: P(drawdown >= threshold | score).

    Returns a calibration map (breakpoints + probabilities) for score → P.
    sklearn IsotonicRegression preferred; fallback: monotone binning.
    """
    labels = (fwd_dd >= dd_threshold).astype(float)
    n = len(scores)
    if n < 20:
        return {"breakpoints": [], "probabilities": [], "method": "insufficient_data"}

    try:
        from sklearn.isotonic import IsotonicRegression
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(scores, labels)
        bp = np.linspace(float(scores.min()), float(scores.max()), 50)
        probs = ir.predict(bp)
        return {
            "breakpoints": bp.tolist(),
            "probabilities": probs.tolist(),
            "method": "isotonic_regression",
        }
    except ImportError:
        return _monotone_bin_calibration(scores, labels)


def _monotone_bin_calibration(
    scores: np.ndarray,
    labels: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, Any]:
    order = np.argsort(scores)
    sorted_scores = scores[order]
    sorted_labels = labels[order]

    bin_size = max(1, len(scores) // n_bins)
    breakpoints = []
    probabilities = []

    for i in range(0, len(scores), bin_size):
        chunk = sorted_labels[i : i + bin_size]
        sc = sorted_scores[i : i + bin_size]
        breakpoints.append(float(sc.mean()))
        probabilities.append(float(chunk.mean()))

    for i in range(1, len(probabilities)):
        probabilities[i] = max(probabilities[i], probabilities[i - 1])

    return {
        "breakpoints": breakpoints,
        "probabilities": probabilities,
        "method": "monotone_bin",
    }


# ---------------------------------------------------------------------------
# Reliability diagram + ECE
# ---------------------------------------------------------------------------

def reliability_diagram(
    calib: Dict[str, Any],
    scores: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Compute reliability diagram data + Expected Calibration Error (ECE).

    Returns {bins: [{predicted_mean, observed_freq, count}], ece: float}.
    """
    if len(scores) < 10:
        return {"bins": [], "ece": 1.0}

    bp = np.array(calib.get("breakpoints", []))
    pr = np.array(calib.get("probabilities", []))

    if len(bp) == 0:
        pred_probs = np.full_like(scores, 0.5)
    else:
        pred_probs = np.interp(scores, bp, pr)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins_data = []
    ece = 0.0

    for i in range(n_bins):
        mask = (pred_probs >= bin_edges[i]) & (pred_probs < bin_edges[i + 1])
        if i == n_bins - 1:
            mask |= pred_probs == bin_edges[i + 1]
        count = int(mask.sum())
        if count == 0:
            bins_data.append({"predicted_mean": 0.0, "observed_freq": 0.0, "count": 0})
            continue
        pred_mean = float(pred_probs[mask].mean())
        obs_freq = float(outcomes[mask].mean())
        bins_data.append({
            "predicted_mean": round(pred_mean, 4),
            "observed_freq": round(obs_freq, 4),
            "count": count,
        })
        ece += abs(pred_mean - obs_freq) * count

    ece /= max(len(scores), 1)
    return {"bins": bins_data, "ece": round(ece, 6)}


# ---------------------------------------------------------------------------
# Factor lead-time analysis (how far in advance does a factor fire before tops?)
# ---------------------------------------------------------------------------

def factor_lead_time_analysis(
    factor_series: pd.Series,
    labeled_tops: List[Any],
    lead_window: int = 60,
    fire_threshold: float = 0.0,
) -> Dict[str, Any]:
    """Measure calendar days of advance notice each factor gives before labeled tops.

    For each labeled top, searches the window [top - lead_window, top) for the
    FIRST day the factor value exceeds ``fire_threshold``. Reports how many
    calendar days before the top that first fire occurred.

    Args:
        factor_series: Date-indexed pd.Series (factor scores, any numeric).
        labeled_tops: Confirmed top dates (list of str/date/Timestamp).
        lead_window:  Look-back horizon in calendar days.
        fire_threshold: Minimum value to count as "fired". Default 0 = any positive.

    Returns dict with per-top lead times plus summary statistics.
    """
    if factor_series.empty or not labeled_tops:
        return {"lead_times_days": {}, "median_lead_days": None, "mean_lead_days": None,
                "hit_rate": 0.0, "hits": 0, "total_tops": 0, "factor_fire_rate": 0.0}

    idx = pd.to_datetime(factor_series.index)
    vals = factor_series.values
    # overall fire rate (fraction of days above threshold)
    fire_rate = float((pd.Series(vals) > fire_threshold).mean())

    lead_times: Dict[str, Optional[int]] = {}
    for top in labeled_tops:
        top_ts = pd.Timestamp(top)
        top_date_str = top_ts.date().isoformat()
        window_start = top_ts - pd.Timedelta(days=lead_window)
        # PIT-safe: only look at days strictly before the top
        mask = (idx >= window_start) & (idx < top_ts)
        mask = getattr(mask, "values", mask)
        if not mask.any():
            lead_times[top_date_str] = None
            continue
        window_vals = pd.Series(vals[mask], index=idx[mask]).sort_index()
        fires = window_vals[window_vals > fire_threshold]
        if fires.empty:
            lead_times[top_date_str] = None
        else:
            first_fire = fires.index[0]
            lead_times[top_date_str] = (top_ts - first_fire).days

    valid = [v for v in lead_times.values() if v is not None]
    hits = len(valid)
    total = len(labeled_tops)
    return {
        "lead_times_days": lead_times,
        "median_lead_days": float(np.median(valid)) if valid else None,
        "mean_lead_days": float(np.mean(valid)) if valid else None,
        "min_lead_days": int(min(valid)) if valid else None,
        "max_lead_days": int(max(valid)) if valid else None,
        "hit_rate": round(hits / total, 4) if total > 0 else 0.0,
        "hits": hits,
        "total_tops": total,
        "factor_fire_rate": round(fire_rate, 4),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _spearman_corr(x: np.ndarray, y: np.ndarray) -> float:
    rx = _rank(x)
    ry = _rank(y)
    return _pearson_corr(rx, ry)


def _pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx, my = x.mean(), y.mean()
    dx, dy = x - mx, y - my
    denom = math.sqrt(float(np.dot(dx, dx) * np.dot(dy, dy)))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(dx, dy) / denom)


def _rank(arr: np.ndarray) -> np.ndarray:
    order = np.argsort(arr)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(arr) + 1, dtype=float)
    return ranks
