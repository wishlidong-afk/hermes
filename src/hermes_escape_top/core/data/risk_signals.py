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

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ...config import load_config, resolve_path
from .adapters import SoftDataRecord
from .macro import fetch_fred_graph_csv
from .pit import asof_pick
from .store import LocalStore, safe_symbol


def fred_api_key(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Read the FRED API key from env → gitignored data/fred_api_key.txt → config.

    Never stored in the (public) repo config; the file is gitignored.
    """
    env = os.environ.get("FRED_API_KEY")
    if env and env.strip():
        return env.strip()
    try:
        cfg = config or load_config()
        path = resolve_path(cfg, "soft_history_dir").parent / "fred_api_key.txt"
        if path.exists():
            txt = path.read_text(encoding="utf-8").strip()
            if txt:
                return txt
    except Exception:
        pass
    if config and config.get("fred_api_key"):
        return str(config["fred_api_key"]).strip()
    return None


def fetch_fred_series(series_id: str, start: str = "1990-01-01", end: Optional[str] = None,
                      config: Optional[Dict[str, Any]] = None) -> pd.Series:
    """Full-history FRED fetch via the API (when a key is present), else the
    no-key fredgraph CSV. The API avoids the fredgraph export window cap and is
    more reliable / rate-limit-friendly.
    """
    key = fred_api_key(config)
    if key:
        try:
            import requests
            params = {"series_id": series_id, "api_key": key, "file_type": "json",
                      "observation_start": start, "sort_order": "asc", "limit": 100000}
            if end:
                params["observation_end"] = end
            resp = requests.get("https://api.stlouisfed.org/fred/series/observations",
                                params=params, timeout=30)
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            if obs:
                idx = pd.to_datetime([o["date"] for o in obs], errors="coerce")
                vals = pd.to_numeric(pd.Series([o.get("value") for o in obs]).replace(".", pd.NA), errors="coerce")
                series = pd.Series(vals.values, index=idx).dropna().sort_index()
                if not series.empty:
                    return series
        except Exception:
            pass  # fall through to the no-key endpoint
    return fetch_fred_graph_csv(series_id, start=start, end=end)


# Process-level caches keyed by (path, mtime) — safe (auto-invalidate on file
# change) and only touched when a risk flag is ON, so OFF stays byte-identical.
# Makes the calibration backtest feasible (no per-day disk reload of full history).
_CSV_CACHE: Dict[tuple, pd.DataFrame] = {}
_CLOSE_CACHE: Dict[tuple, pd.Series] = {}


def _read_csv_cached(path: Path, parse_dates=None) -> pd.DataFrame:
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    key = (str(path), mtime, tuple(parse_dates or ()))
    if key not in _CSV_CACHE:
        _CSV_CACHE[key] = pd.read_csv(path, parse_dates=list(parse_dates) if parse_dates else None)
    return _CSV_CACHE[key]


def _close_series_cached(store: "LocalStore", symbol: str) -> Optional[pd.Series]:
    path = store.history_dir / f"{safe_symbol(symbol)}.csv"
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = 0.0
    key = (symbol, str(path), mtime)
    if key not in _CLOSE_CACHE:
        hist = store.load_history(symbol)
        if hist is None or getattr(hist, "empty", True) or "Close" not in hist:
            _CLOSE_CACHE[key] = None
        else:
            _CLOSE_CACHE[key] = hist["Close"].dropna()
    return _CLOSE_CACHE[key]


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
                 window: int = 252, min_periods: int = 60, start: str = "1990-01-01") -> None:
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

    def build_frame(self, end: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        series = fetch_fred_series(self.series_id, start=self.start, end=end, config=config)
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
        frame = self.build_frame(end=end, config=config)
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
        frame = _read_csv_cached(path, parse_dates=["date", "publish_date"])
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
        cutoff = pd.Timestamp(str(as_of)[:10])
        for sym in symbols:
            closes = _close_series_cached(store, sym)
            if closes is None:
                return None
            local = closes.loc[closes.index <= cutoff].dropna()
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


class LevelPercentileSource:
    """Single index level (e.g. MOVE bond-vol) → SOFT.<field> + SOFT.<field>_pctl.

    Reads one symbol's close from the OHLCV store and takes the trailing-window
    percentile of the latest level. PIT-safe (only bars <= as_of). Gated.
    """

    def __init__(self, name: str, feature_flag: str, symbol: str, field: str,
                 window: int = 252, min_periods: int = 60) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.symbol = symbol
        self.field = field
        self.window = window
        self.min_periods = min_periods

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "INDEX_LEVEL", False, reason=f"feature disabled: {self.feature_flag}")
        try:
            store = LocalStore(config)
            closes = _close_series_cached(store, self.symbol)
        except Exception as exc:  # noqa: BLE001
            return SoftDataRecord(self.name, day, None, "INDEX_LEVEL", False, quality_penalty=5.0,
                                  reason=f"{self.name} load failed: {exc}")
        if closes is None:
            return SoftDataRecord(self.name, day, None, "INDEX_LEVEL", False, quality_penalty=5.0,
                                  reason=f"{self.name} missing OHLCV for {self.symbol}")
        local = closes.loc[closes.index <= pd.Timestamp(str(as_of)[:10])].dropna()
        if local.empty:
            return SoftDataRecord(self.name, day, None, "INDEX_LEVEL", False, quality_penalty=5.0,
                                  reason=f"{self.name} no data as of date")
        window = local.iloc[-self.window:]
        pctl = _last_percentile(window) if len(window) >= self.min_periods else float("nan")
        value = float(local.iloc[-1]); pctl_f = _finite(pctl)
        available = pctl_f is not None
        return SoftDataRecord(
            self.name, day, pctl_f, "INDEX_LEVEL", available, is_proxy=False,
            latency_days=max(0, (day - local.index[-1].date()).days),
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
        # Axis-A additions (2026-06-08): pre-built financial-conditions composite + bond vol
        FredPercentileSource("nfci", "data_nfci", "NFCI", "nfci"),
        LevelPercentileSource("move", "data_move", "^MOVE", "move"),
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
RISK_ETF_SYMBOLS = ["HYG", "IEF", "RSP", "XLP", "XLU", "XLV", "XLY", "XLI", "XLF", "KRE", "LQD", "^MOVE"]
