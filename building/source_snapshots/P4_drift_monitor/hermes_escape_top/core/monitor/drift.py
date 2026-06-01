"""E9 Drift Monitor -- online monitoring of distribution shift, precision decay, IC decay.

Detects when the live environment diverges from calibration conditions.
PSI > threshold triggers alert; alerts feed into ConfidenceSpine as drift_state.

All computations are stateless pure functions (state stored externally in audit log).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class DriftMonitor:
    """Stateless drift detection: PSI, precision tracking, IC decay, quality trend."""

    def __init__(self, cfg: Dict[str, Any]):
        self._cfg = cfg
        self._psi_threshold = float(cfg.get("psi_threshold", 0.25))
        self._precision_drop = float(cfg.get("precision_drop_threshold", 0.10))
        self._ic_decay_threshold = float(cfg.get("ic_decay_threshold", 0.50))

    def evaluate(
        self,
        train_scores: np.ndarray,
        live_scores: np.ndarray,
        train_precision: Optional[float] = None,
        live_precision: Optional[float] = None,
        train_ic: Optional[Dict[str, float]] = None,
        live_ic: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Evaluate all drift dimensions; return drift_state for ConfidenceSpine."""
        psi = compute_psi(train_scores, live_scores)
        alert = psi > self._psi_threshold

        precision_alert = False
        precision_drop = 0.0
        if train_precision is not None and live_precision is not None:
            precision_drop = train_precision - live_precision
            if precision_drop > self._precision_drop:
                precision_alert = True
                alert = True

        ic_decay_alert = False
        ic_ratios = {}
        if train_ic and live_ic:
            for factor in train_ic:
                if factor in live_ic and abs(train_ic[factor]) > 0.01:
                    ratio = live_ic[factor] / train_ic[factor]
                    ic_ratios[factor] = round(ratio, 4)
                    if ratio < self._ic_decay_threshold:
                        ic_decay_alert = True
                        alert = True

        recommendations = []
        if psi > self._psi_threshold:
            recommendations.append("score distribution shifted; consider recalibration")
        if precision_alert:
            recommendations.append(f"defense precision dropped {precision_drop:.1%}; review factor weights")
        if ic_decay_alert:
            decayed = [f for f, r in ic_ratios.items() if r < self._ic_decay_threshold]
            recommendations.append(f"IC decayed for {decayed}; consider pruning or recalibration")

        return {
            "psi": round(psi, 4),
            "alert": alert,
            "precision_drop": round(precision_drop, 4),
            "precision_alert": precision_alert,
            "ic_ratios": ic_ratios,
            "ic_decay_alert": ic_decay_alert,
            "recommendations": recommendations,
        }


def compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Population Stability Index between two score distributions.

    PSI < 0.10: no significant shift
    PSI 0.10-0.25: moderate shift
    PSI > 0.25: significant shift (alert)
    """
    if len(expected) < 10 or len(actual) < 10:
        return 0.0

    breakpoints = np.linspace(
        min(float(expected.min()), float(actual.min())),
        max(float(expected.max()), float(actual.max())),
        n_bins + 1,
    )

    expected_counts = np.histogram(expected, bins=breakpoints)[0].astype(float)
    actual_counts = np.histogram(actual, bins=breakpoints)[0].astype(float)

    expected_pct = expected_counts / max(expected_counts.sum(), 1)
    actual_pct = actual_counts / max(actual_counts.sum(), 1)

    eps = 1e-4
    expected_pct = np.clip(expected_pct, eps, None)
    actual_pct = np.clip(actual_pct, eps, None)

    psi = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
    return max(0.0, psi)


def compute_rolling_precision(
    signals: pd.DataFrame,
    window: int = 60,
) -> pd.Series:
    """Rolling defense precision: fraction of TRIM+ signals followed by drawdown >= threshold.

    signals must have columns: date, status, fwd_max_dd.
    """
    if signals.empty or "status" not in signals.columns:
        return pd.Series(dtype=float)

    defense_mask = signals["status"].isin(["TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"])
    if "fwd_max_dd" not in signals.columns:
        return pd.Series(dtype=float)

    correct = defense_mask & (signals["fwd_max_dd"].abs() >= 0.05)
    return correct.rolling(window, min_periods=10).mean()
