"""Tier-1/2 risk-signal soft-data sources (credit, rates, dollar, cross-asset).

ALL sources here are gated by a feature flag that defaults to OFF. They are only
added to the soft-source list when their flag is ON (see ``risk_sources``), so a
checkout with every flag OFF produces byte-identical output to before this module
existed — nothing new is collected, scored, or written.

Two parametric source types keep this DRY:
  - FredPercentileSource     : one FRED series → asof value + trailing percentile.
  - EtfRatioPercentileSource : ratio of two (equal-weight) ETF baskets → percentile,
                               computed from local OHLCV (no extra network).

Each exposes SOFT.<field> and SOFT.<field>_pctl, consumed by the A9–A16 factors
in core/scoring/factors_risk.py.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ...config import resolve_path
from .adapters import SoftDataRecord
from .macro import fetch_fred_graph_csv
from .pit import asof_pick
from .store import LocalStore, safe_symbol


def _last_percentile(window: pd.Series) -> float:
    current = window.iloc[-1]
    if pd.isna(current):
        return float("nan")
    valid = window.dropna()
    if valid.empty:
        return float("nan")
    return float((valid <= current).mean() * 100.0)


def _finite(value: Any) -> Optional[float]:
    try:
        out = float(value)
        return out if out == out else None
    except Exception:
        return None


# ── FRED single-series → percentile ──────────────────────────────────────────

class FredPercentileSource:
    """Generic FRED series exposed as SOFT.<field> and SOFT.<field>_pctl.

    PIT-safe: the percentile is a trailing rolling rank precomputed into the CSV
    (only looks backward); ``collect`` then asof-picks by publish_date.
    """

    def __init__(self, name: str, feature_flag: str, series_id: str, field: str,
                 window: int = 252, min_periods: int = 60, start: str = "2015-01-01") -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.series_id = series_id
        self.field = field
        self.window = window
        self.min_periods = min_periods
        self.start = start

    def history_path(self, config: Dict[str, Any]) -> Path:
        if config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / f"{self.name}.csv"

    def build_frame(self, end: Optional[str] = None) -> pd.DataFrame:
        series = fetch_fred_graph_csv(self.series_id, start=self.start, end=end)
        frame = series.rename("value").to_frame().sort_index()
        frame[f"{self.field}_pctl"] = (
            frame["value"].rolling(self.window, min_periods=self.min_periods).apply(_last_percentile, raw=False)
        )
        out = frame.reset_index().rename(columns={"index": "date", frame.index.name or "index": "date"})
        if "date" not in out.columns:
            out = out.rename(columns={out.columns[0]: "date"})
        out["date"] = pd.to_datetime(out["date"])
        out["publish_date"] = out["date"] + pd.Timedelta(days=1)
        out = out.rename(columns={"value": self.field})
        return out[["date", "publish_date", self.field, f"{self.field}_pctl"]]

    def backfill(self, config: Dict[str, Any], end: Optional[str] = None) -> Path:
        frame = self.build_frame(end=end)
        path = self.history_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        return path

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "FRED", False, reason=f"feature disabled: {self.feature_flag}")
        path = self.history_path(config)
        if not path.exists() and not config.get("runtime", {}).get("offline_replay_mode", False):
            try:
                self.backfill(config)
            except Exception as exc:  # noqa: BLE001
                return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0,
                                      reason=f"{self.series_id} backfill failed: {exc}")
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0,
                                  reason=f"{self.name} history missing")
        frame = pd.read_csv(path, parse_dates=["date", "publish_date"])
        records = [(row["publish_date"].date(), row) for row in frame.to_dict("records")]
        picked = asof_pick(records, day)
        if picked is None:
            return SoftDataRecord(self.name, day, None, "FRED", False, quality_penalty=5.0,
                                  reason="no record as of date")
        value = _finite(picked.get(self.field))
        pctl = _finite(picked.get(f"{self.field}_pctl"))
        available = value is not None
        return SoftDataRecord(
            self.name, day, pctl, "FRED", available, is_proxy=False,
            latency_days=max(0, (day - picked["publish_date"].date()).days),
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else f"{self.name} unavailable",
            fields={self.field: value, f"{self.field}_pctl": pctl},
        )


# ── ETF basket ratio → percentile (computed from local OHLCV) ────────────────

class EtfRatioPercentileSource:
    """Ratio of two equal-weight ETF baskets → SOFT.<field> + SOFT.<field>_pctl.

    Each ETF is normalised to its own first observation (so the basket is
    equal-weight, not price-weight); the percentile is scale-invariant. PIT-safe:
    only bars with index <= as_of are used.
    """

    def __init__(self, name: str, feature_flag: str, numerator: List[str], denominator: List[str],
                 field: str, window: int = 252, min_periods: int = 60) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.numerator = numerator
        self.denominator = denominator
        self.field = field
        self.window = window
        self.min_periods = min_periods

    def _basket_index(self, store: LocalStore, symbols: List[str], as_of: str) -> Optional[pd.Series]:
        cols = []
        for sym in symbols:
            hist = store.load_history(sym)
            if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
                return None
            local = hist.loc[hist.index <= pd.Timestamp(str(as_of)[:10]), "Close"].dropna()
            if local.empty or float(local.iloc[0]) == 0:
                return None
            cols.append(local / float(local.iloc[0]))
        frame = pd.concat(cols, axis=1).dropna()
        if frame.empty:
            return None
        return frame.mean(axis=1)

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "ETF_RATIO", False, reason=f"feature disabled: {self.feature_flag}")
        try:
            store = LocalStore(config)
            num = self._basket_index(store, self.numerator, as_of)
            den = self._basket_index(store, self.denominator, as_of)
        except Exception as exc:  # noqa: BLE001
            return SoftDataRecord(self.name, day, None, "ETF_RATIO", False, quality_penalty=5.0,
                                  reason=f"{self.name} compute failed: {exc}")
        if num is None or den is None:
            return SoftDataRecord(self.name, day, None, "ETF_RATIO", False, quality_penalty=5.0,
                                  reason=f"{self.name} missing OHLCV for {self.numerator}/{self.denominator}")
        ratio = (num / den).dropna()
        if ratio.empty:
            return SoftDataRecord(self.name, day, None, "ETF_RATIO", False, quality_penalty=5.0,
                                  reason=f"{self.name} empty ratio")
        window = ratio.iloc[-self.window:]
        pctl = _last_percentile(window) if len(window) >= self.min_periods else float("nan")
        value = float(ratio.iloc[-1])
        latency = max(0, (day - ratio.index[-1].date()).days)
        pctl_f = _finite(pctl)
        available = pctl_f is not None
        return SoftDataRecord(
            self.name, day, pctl_f, "ETF_RATIO", available, is_proxy=True,
            latency_days=latency,
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else f"{self.name} insufficient history",
            fields={self.field: value, f"{self.field}_pctl": pctl_f},
        )


# ── registry: which sources are active (flag-gated) ──────────────────────────

def _all_risk_sources() -> List[Any]:
    return [
        # Tier 1 — FRED (free, daily, long history)
        FredPercentileSource("hy_oas", "data_hy_oas", "BAMLH0A0HYM2", "hy_oas"),
        FredPercentileSource("real_rate", "data_real_rate", "DFII10", "real_rate_10y"),
        FredPercentileSource("dollar", "data_dollar", "DTWEXBGS", "dollar_broad"),
        FredPercentileSource("yield_curve", "data_yield_curve", "T10Y3M", "yield_curve_10y3m"),
        # Tier 2 — ETF ratios (free, from local OHLCV)
        EtfRatioPercentileSource("credit_etf", "data_credit_etf", ["HYG"], ["IEF"], "credit_etf_ratio"),
        EtfRatioPercentileSource("concentration", "data_concentration", ["RSP"], ["SPY"], "concentration_rsp_spy"),
        EtfRatioPercentileSource("defensive_rotation", "data_defensive_rotation",
                                 ["XLP", "XLU", "XLV"], ["XLY", "XLI", "XLF"], "defensive_cyclical"),
        EtfRatioPercentileSource("financial_stress", "data_financial_stress", ["XLF"], ["SPY"], "financial_stress_xlf"),
    ]


def risk_sources(config: Optional[Dict[str, Any]]) -> List[Any]:
    """Return only the risk sources whose feature flag is ON.

    With every flag OFF (the default) this returns [] — so nothing new is
    collected and the soft-data payload is byte-identical to before.
    """
    if not config:
        return []
    feats = config.get("features", {}) or {}
    return [src for src in _all_risk_sources() if bool(feats.get(src.feature_flag, False))]


# Symbols the Tier-2 ETF ratios need in the OHLCV store (for backfill wiring).
RISK_ETF_SYMBOLS = ["HYG", "IEF", "RSP", "XLP", "XLU", "XLV", "XLY", "XLI", "XLF", "KRE", "LQD"]
