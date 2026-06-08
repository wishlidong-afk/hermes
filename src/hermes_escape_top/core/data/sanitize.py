"""E1 Data Sanitization -- prevent false hard-valve triggers from bad data.

Detects: split/adjustment inconsistencies, bad ticks (zero volume + cross-source mismatch),
winsorize outliers, stale data, cross-source verification.

Hard-valve K-bars flagged as suspect → hard valve downgrades to "pending confirmation".
Real crashes (volume + cross-source consistent) are never suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class Anomaly:
    date: str
    field: str
    kind: str  # BAD_TICK, STALE, OUTLIER, SPLIT_MISMATCH, CROSS_SOURCE
    severity: str  # LOW, MEDIUM, HIGH
    detail: str


@dataclass
class SanitizeResult:
    clean_df: pd.DataFrame
    anomalies: List[Anomaly]
    data_confidence: float  # [0,1], 1 = fully clean
    suspect_dates: List[str]  # dates where hard-valve triggers should be "pending"


def sanitize_ohlcv(
    df: pd.DataFrame,
    cfg: Dict[str, Any],
    cross_source: Optional[pd.DataFrame] = None,
) -> SanitizeResult:
    """Main sanitization entry point.

    Returns clean DataFrame + list of anomalies + data_confidence score.
    """
    if df.empty:
        return SanitizeResult(df, [], 0.0, [])

    anomalies: List[Anomaly] = []
    suspect_dates: List[str] = []
    clean = df.copy()

    # 1. Bad tick detection (zero volume + extreme move)
    anomalies.extend(_detect_bad_ticks(clean, cfg))

    # 2. Split/adjustment consistency
    anomalies.extend(_detect_split_mismatch(clean, cfg))

    # 3. Stale detection (repeated closes)
    anomalies.extend(_detect_stale(clean, cfg))

    # 4. Outlier winsorize (mark but preserve)
    outlier_anoms = _detect_outliers(clean, cfg)
    anomalies.extend(outlier_anoms)

    # 5. Cross-source verification
    if cross_source is not None and not cross_source.empty:
        anomalies.extend(_cross_source_check(clean, cross_source, cfg))

    # Collect suspect dates (HIGH severity anomalies)
    for a in anomalies:
        if a.severity == "HIGH":
            if a.date not in suspect_dates:
                suspect_dates.append(a.date)

    # Data confidence: 1.0 - penalty per anomaly
    high_count = sum(1 for a in anomalies if a.severity == "HIGH")
    med_count = sum(1 for a in anomalies if a.severity == "MEDIUM")
    n_bars = max(len(clean), 1)
    penalty = (high_count * 0.05 + med_count * 0.01) / n_bars
    data_confidence = max(0.0, min(1.0, 1.0 - penalty * 100))

    return SanitizeResult(
        clean_df=clean,
        anomalies=anomalies,
        data_confidence=round(data_confidence, 4),
        suspect_dates=suspect_dates,
    )


def is_suspect_on(history: Optional[pd.DataFrame], as_of: Any, cfg: Optional[Dict[str, Any]]) -> bool:
    """True iff the ``as_of`` bar is flagged suspect (HIGH-severity anomaly).

    Shared by the live pipeline and the backtest loop. Fail-safe by design: on
    missing data or any error → False, so a hard valve behaves exactly as before
    and we never *fabricate* suspicion (which would suppress a genuine valve).
    """
    if history is None or getattr(history, "empty", True):
        return False
    try:
        df = history.rename(columns={c: str(c).lower() for c in history.columns})
        result = sanitize_ohlcv(df, cfg or {})
        target = str(as_of)[:10]
        return any(str(d)[:10] == target for d in result.suspect_dates)
    except Exception:
        return False


def _detect_bad_ticks(df: pd.DataFrame, cfg: Dict[str, Any]) -> List[Anomaly]:
    """Zero-volume bars with extreme price moves → BAD_TICK."""
    anomalies = []
    ret_threshold = float(cfg.get("bad_tick_ret_threshold", 0.15))

    if "volume" not in df.columns or "close" not in df.columns:
        return anomalies

    # If volume is structurally absent for this series (e.g. FNGU and other ETNs
    # report ~0 volume), a zero-volume bar cannot distinguish a bad tick from a
    # real move — using it would flag genuine crash days (COVID/2022) as suspect
    # and wrongly hold a hard valve. Disable volume-based bad-tick detection then.
    max_zero_frac = float(cfg.get("bad_tick_max_zero_vol_frac", 0.5))
    if len(df) and float((df["volume"] == 0).mean()) > max_zero_frac:
        return anomalies

    ret = df["close"].pct_change()
    for i in range(1, len(df)):
        vol = df["volume"].iloc[i]
        r = abs(ret.iloc[i]) if pd.notna(ret.iloc[i]) else 0.0
        if vol == 0 and r > ret_threshold:
            dt = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])
            anomalies.append(Anomaly(
                date=dt, field="close", kind="BAD_TICK", severity="HIGH",
                detail=f"zero volume with {r:.1%} return",
            ))
    return anomalies


def _detect_split_mismatch(df: pd.DataFrame, cfg: Dict[str, Any]) -> List[Anomaly]:
    """Overnight gap > threshold without corresponding volume → possible split artifact."""
    anomalies = []
    gap_threshold = float(cfg.get("split_gap_threshold", 0.40))

    if "close" not in df.columns:
        return anomalies

    for i in range(1, len(df)):
        prev_close = df["close"].iloc[i - 1]
        curr_open = df["open"].iloc[i] if "open" in df.columns else df["close"].iloc[i]
        if prev_close > 0:
            gap = abs(curr_open - prev_close) / prev_close
            if gap > gap_threshold:
                dt = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])
                anomalies.append(Anomaly(
                    date=dt, field="open", kind="SPLIT_MISMATCH", severity="MEDIUM",
                    detail=f"overnight gap {gap:.1%}",
                ))
    return anomalies


def _detect_stale(df: pd.DataFrame, cfg: Dict[str, Any]) -> List[Anomaly]:
    """Repeated identical closes for N+ consecutive days."""
    anomalies = []
    stale_days = int(cfg.get("stale_days_threshold", 3))

    if "close" not in df.columns or len(df) < stale_days:
        return anomalies

    closes = df["close"].values
    streak = 1
    for i in range(1, len(closes)):
        if closes[i] == closes[i - 1]:
            streak += 1
            if streak >= stale_days:
                dt = str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i])
                anomalies.append(Anomaly(
                    date=dt, field="close", kind="STALE", severity="MEDIUM",
                    detail=f"close unchanged for {streak} days",
                ))
        else:
            streak = 1
    return anomalies


def _detect_outliers(df: pd.DataFrame, cfg: Dict[str, Any]) -> List[Anomaly]:
    """Extreme returns beyond N sigma → OUTLIER (marked, not removed)."""
    anomalies = []
    sigma_threshold = float(cfg.get("outlier_sigma", 5.0))

    if "close" not in df.columns or len(df) < 30:
        return anomalies

    ret = df["close"].pct_change().dropna()
    mu = ret.mean()
    sigma = ret.std()
    if sigma < 1e-8:
        return anomalies

    for i in range(len(ret)):
        z = abs((ret.iloc[i] - mu) / sigma)
        if z > sigma_threshold:
            dt = str(ret.index[i].date()) if hasattr(ret.index[i], "date") else str(ret.index[i])
            anomalies.append(Anomaly(
                date=dt, field="close", kind="OUTLIER", severity="LOW",
                detail=f"return {ret.iloc[i]:.2%} is {z:.1f}σ",
            ))
    return anomalies


def _cross_source_check(
    df: pd.DataFrame,
    cross: pd.DataFrame,
    cfg: Dict[str, Any],
) -> List[Anomaly]:
    """Compare close prices across two sources; flag divergence."""
    anomalies = []
    tolerance = float(cfg.get("cross_source_tolerance", 0.02))

    common = df.index.intersection(cross.index)
    for dt in common:
        c1 = df.loc[dt, "close"] if "close" in df.columns else None
        c2 = cross.loc[dt, "close"] if "close" in cross.columns else None
        if c1 is not None and c2 is not None and c1 > 0:
            diff = abs(c1 - c2) / c1
            if diff > tolerance:
                dt_str = str(dt.date()) if hasattr(dt, "date") else str(dt)
                anomalies.append(Anomaly(
                    date=dt_str, field="close", kind="CROSS_SOURCE", severity="HIGH",
                    detail=f"cross-source divergence {diff:.2%}",
                ))
    return anomalies
