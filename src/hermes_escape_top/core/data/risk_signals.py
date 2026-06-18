"""Tier-1/2 risk-signal soft-data sources (credit, rates, dollar, cross-asset).

ALL sources here are gated by a feature flag that defaults to OFF. They are only
added to the soft-source list when their flag is ON (see ``risk_sources``), so a
checkout with every flag OFF produces byte-identical output to before this module
existed — nothing new is collected, scored, or written.

Parametric source types keep this DRY:
  - FredPercentileSource     : one FRED series → asof value + trailing percentile.
  - EtfRatioPercentileSource : ratio of two (equal-weight) ETF baskets → percentile,
                               computed from local OHLCV (no extra network).
  - OnchainMstrSource        : precomputed Coin Metrics community features for
                               T19 MSTR on-chain gates.
  - MstrMnavSource           : MSTR market cap / (BTC holdings × BTC price) → B6
                               valuation percentile.

Most expose SOFT.<field> and SOFT.<field>_pctl for the A9–A16 factors; mNAV
exposes SOFT.MSTR_valuation_pctl for B6.
"""
from __future__ import annotations

import os
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from ...config import load_config, resolve_path
from .adapters import SoftDataRecord
from .macro import fetch_fred_graph_csv
from ..safe_io import atomic_write_csv
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
    frame = fetch_fred_series_frame(series_id, start=start, end=end, config=config)
    if frame.empty:
        return pd.Series(dtype=float)
    return pd.Series(frame["value"].values, index=pd.to_datetime(frame["date"])).dropna().sort_index()


def fetch_fred_series_frame(series_id: str, start: str = "1990-01-01", end: Optional[str] = None,
                            config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Fetch one FRED series with a point-in-time publish date.

    ``publish_date = observation date + 1 day`` (next-day release). The API's
    ``realtime_start`` is deliberately NOT used: on the standard observations
    endpoint it returns the *query* date for every row (the current vintage),
    which stamps the whole series with "today" and makes ``asof_pick`` treat
    every value as published in the future (this caused the 2026-06-13
    real_rate/dollar outage). True per-row vintage would need an ALFRED query;
    date+1 is the PIT-safe behavior shared by every FRED series here.
    """
    key = fred_api_key(config)
    if key:
        try:
            params = {"series_id": series_id, "api_key": key, "file_type": "json",
                      "observation_start": start, "sort_order": "asc", "limit": 100000}
            if end:
                params["observation_end"] = end
            url = "https://api.stlouisfed.org/fred/series/observations?" + urlencode(params)
            with urlopen(url, timeout=30) as resp:
                obs = json.loads(resp.read().decode("utf-8")).get("observations", [])
            if obs:
                frame = pd.DataFrame(
                    {
                        "date": pd.to_datetime([o.get("date") for o in obs], errors="coerce"),
                        "value": pd.to_numeric(pd.Series([o.get("value") for o in obs]).replace(".", pd.NA), errors="coerce"),
                    }
                ).dropna(subset=["date", "value"]).sort_values("date")
                if not frame.empty:
                    # date+1, NOT realtime_start (see docstring): realtime_start is the
                    # query date for every row here, which breaks asof_pick.
                    frame["publish_date"] = frame["date"] + pd.Timedelta(days=1)
                    return frame[["date", "publish_date", "value"]]
        except Exception:
            pass  # fall through to the no-key endpoint
    series = fetch_fred_graph_csv(series_id, start=start, end=end)
    if series.empty:
        return pd.DataFrame(columns=["date", "publish_date", "value"])
    frame = series.rename("value").to_frame().reset_index()
    frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    frame["publish_date"] = frame["date"] + pd.Timedelta(days=1)
    return frame[["date", "publish_date", "value"]]


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


def _find_numeric_column(frame: pd.DataFrame, names: List[str]) -> Optional[pd.Series]:
    lookup = {str(col).lower(): col for col in frame.columns}
    for name in names:
        col = lookup.get(name.lower())
        if col is not None:
            return pd.to_numeric(frame[col], errors="coerce")
    return None


def _mstr_market_cap_series(history: pd.DataFrame) -> Optional[pd.Series]:
    market_cap = _find_numeric_column(
        history,
        ["mstr_market_cap_usd", "market_cap_usd", "market_cap", "Market Cap", "marketcap"],
    )
    if market_cap is not None:
        return market_cap
    shares = _find_numeric_column(history, ["shares_outstanding", "shares", "adso"])
    close = _find_numeric_column(history, ["Close", "close"])
    if shares is not None and close is not None:
        return shares * close
    return None


def _mstr_market_cap_from_shares_file(history: pd.DataFrame, config: Dict[str, Any]) -> Optional[pd.Series]:
    """Fallback: quarterly EDGAR shares seed x split-adjusted Close.

    soft_history/mstr_shares_outstanding.csv carries PIT filing dates and
    split-adjusted basic weighted-avg shares (see file header). Forward-filled
    onto trading days — real shares x real price, NOT the price-only proxy
    this module refuses. Lives outside MSTR.csv because the daily OHLCV
    refresh rewrites that file and would drop an added column.
    """
    path = resolve_path(config, "soft_history_dir") / "mstr_shares_outstanding.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path, comment="#", parse_dates=["date"])
    if frame.empty or "shares" not in frame.columns:
        return None
    shares = (
        frame.assign(shares=pd.to_numeric(frame["shares"], errors="coerce"))
        .dropna(subset=["date", "shares"])
        .set_index("date")["shares"]
        .sort_index()
    )
    close = _find_numeric_column(history, ["Close", "close"])
    if close is None or shares.empty:
        return None
    aligned = shares.reindex(close.index.union(shares.index)).ffill().reindex(close.index)
    out = (aligned * close).dropna()
    return out if not out.empty else None


# ── FRED single-series → percentile ──────────────────────────────────────────

class FredPercentileSource:
    """Generic FRED series exposed as SOFT.<field> and SOFT.<field>_pctl.

    PIT-safe: the percentile is a trailing rolling rank precomputed into the CSV
    (only looks backward); ``collect`` then asof-picks by publish_date.
    """

    def __init__(self, name: str, feature_flag: str, series_id: str, field: str,
                 window: int = 252, min_periods: int = 60, start: str = "1990-01-01",
                 max_age_days: Optional[int] = None) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.series_id = series_id
        self.field = field
        self.window = window
        self.min_periods = min_periods
        self.start = start
        # When set, a record older than max_age_days is returned as missing rather
        # than as a stale value. This prevents the scoring engine from silently
        # using weeks-old percentiles as if they were current.
        self.max_age_days = max_age_days

    def history_path(self, config: Dict[str, Any]) -> Path:
        if config.get("paths", {}).get("soft_history_dir"):
            base = resolve_path(config, "soft_history_dir")
        else:
            base = Path("data/soft_history")
        return base / f"{self.name}.csv"

    def build_frame(self, end: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        raw = fetch_fred_series_frame(self.series_id, start=self.start, end=end, config=config)
        frame = raw.set_index("date")[["value", "publish_date"]].sort_index()
        frame[f"{self.field}_pctl"] = (
            frame["value"].rolling(self.window, min_periods=self.min_periods).apply(_last_percentile, raw=False)
        )
        out = frame.reset_index().rename(columns={"index": "date", frame.index.name or "index": "date"})
        if "date" not in out.columns:
            out = out.rename(columns={out.columns[0]: "date"})
        out["date"] = pd.to_datetime(out["date"])
        out["publish_date"] = pd.to_datetime(out["publish_date"]).fillna(out["date"] + pd.Timedelta(days=1))
        out = out.rename(columns={"value": self.field})
        return out[["date", "publish_date", self.field, f"{self.field}_pctl"]]

    def backfill(self, config: Dict[str, Any], end: Optional[str] = None) -> Path:
        frame = self.build_frame(end=end, config=config)
        path = self.history_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_csv(frame, path, index=False)
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
        latency = max(0, (day - picked["publish_date"].date()).days)
        # Stale-data guard: if max_age_days is set and the record is older than
        # that threshold, treat it as missing so the scoring engine uses the
        # missing_weight/blind-spot path instead of silently scoring stale values.
        if self.max_age_days is not None and latency > self.max_age_days:
            return SoftDataRecord(
                self.name, day, None, "FRED", False, is_proxy=False,
                latency_days=latency, quality_penalty=5.0,
                reason=f"{self.name} stale ({latency}d > max {self.max_age_days}d)",
            )
        available = value is not None
        return SoftDataRecord(
            self.name, day, pctl, "FRED", available, is_proxy=False,
            latency_days=latency,
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
                 field: str, window: int = 252, min_periods: int = 60,
                 max_age_days: Optional[int] = None) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.numerator = numerator
        self.denominator = denominator
        self.field = field
        self.window = window
        self.min_periods = min_periods
        self.max_age_days = max_age_days

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
        if self.max_age_days is not None and latency > self.max_age_days:
            return SoftDataRecord(
                self.name, day, None, "ETF_RATIO", False, is_proxy=True,
                latency_days=latency, quality_penalty=5.0,
                reason=f"{self.name} stale ({latency}d > max {self.max_age_days}d)",
            )
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
                 window: int = 252, min_periods: int = 60,
                 max_age_days: Optional[int] = None) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.symbol = symbol
        self.field = field
        self.window = window
        self.min_periods = min_periods
        self.max_age_days = max_age_days

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
        value = float(local.iloc[-1])
        latency = max(0, (day - local.index[-1].date()).days)
        if self.max_age_days is not None and latency > self.max_age_days:
            return SoftDataRecord(
                self.name, day, None, "INDEX_LEVEL", False, is_proxy=False,
                latency_days=latency, quality_penalty=5.0,
                reason=f"{self.name} stale ({latency}d > max {self.max_age_days}d)",
            )
        pctl_f = _finite(pctl)
        available = pctl_f is not None
        return SoftDataRecord(
            self.name, day, pctl_f, "INDEX_LEVEL", available, is_proxy=False,
            latency_days=latency,
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else f"{self.name} insufficient history",
            fields={self.field: value, f"{self.field}_pctl": pctl_f},
        )


# ── CFTC COT net-positioning percentile ──────────────────────────────────────

class CotPercentileSource:
    """CFTC Commitments of Traders (TFF) → net-long/OI percentile for NQ.

    Reads from a locally-maintained CSV at ``soft_history_dir/cot_<contract>.csv``.
    Expected columns: ``date``, ``combined_net_oi_pct``
    (= (asset_mgr_net + levered_funds_net) / open_interest).

    Published weekly (Friday, for Tuesday snapshot). Backfilled by
    ``scripts/backfill_cot.py``; max_age_days=14 allows one missed week.

    Signal direction: HIGH percentile = crowded long = elevated distribution
    risk (contrarian; use _bucket_high in factors_risk.py).
    """

    def __init__(self, name: str, feature_flag: str, contract: str, field: str,
                 window: int = 252, min_periods: int = 52,
                 max_age_days: Optional[int] = 14) -> None:
        self.name = name
        self.feature_flag = feature_flag
        self.contract = contract
        self.field = field
        self.window = window
        self.min_periods = min_periods
        self.max_age_days = max_age_days

    def history_path(self, config: Dict[str, Any]) -> Path:
        return resolve_path(config, "soft_history_dir") / f"cot_{self.contract}.csv"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False,
                                  reason=f"feature disabled: {self.feature_flag}")
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False, quality_penalty=5.0,
                                  reason=f"{self.name} CSV missing — run backfill_cot.py")
        try:
            df = _read_csv_cached(path, parse_dates=["date"])
        except Exception as exc:  # noqa: BLE001
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False, quality_penalty=5.0,
                                  reason=f"{self.name} read failed: {exc}")
        if df.empty or "date" not in df.columns or "combined_net_oi_pct" not in df.columns:
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False, quality_penalty=5.0,
                                  reason=f"{self.name} CSV malformed (expected date + combined_net_oi_pct)")
        df = df.set_index("date").sort_index()
        local = df.loc[df.index <= pd.Timestamp(str(as_of)[:10])]["combined_net_oi_pct"].dropna()
        if local.empty:
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False, quality_penalty=5.0,
                                  reason=f"{self.name} no data on or before {as_of}")
        latency = max(0, (day - local.index[-1].date()).days)
        if self.max_age_days is not None and latency > self.max_age_days:
            return SoftDataRecord(self.name, day, None, "CFTC_COT", False, is_proxy=False,
                                  latency_days=latency, quality_penalty=5.0,
                                  reason=f"{self.name} stale ({latency}d > max {self.max_age_days}d)")
        window = local.iloc[-self.window:]
        pctl = _last_percentile(window) if len(window) >= self.min_periods else float("nan")
        value = float(local.iloc[-1])
        pctl_f = _finite(pctl)
        available = pctl_f is not None
        return SoftDataRecord(
            self.name, day, pctl_f, "CFTC_COT", available, is_proxy=False,
            latency_days=latency,
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else f"{self.name} insufficient history (need {self.min_periods} weeks)",
            fields={self.field: value, f"{self.field}_pctl": pctl_f},
        )


# ── MSTR mNAV valuation percentile ──────────────────────────────────────────

class MstrMnavSource:
    """MSTR mNAV premium percentile from manual BTC holdings + local histories.

    Required PIT inputs:
    - soft_history/mstr_btc_holdings.csv: date, btc_count (official report dates)
    - history/MSTR.csv: market_cap_usd (or market_cap / close×shares_outstanding)
    - history/BTC_USD.csv: BTC close

    No market-cap approximation is attempted from MSTR price alone; that would
    silently turn mNAV into a scale-broken proxy and make the gate meaningless.
    """

    name = "mstr_mnav"
    feature_flag = "data_mstr_mnav"

    def __init__(self, window: int = 252, min_periods: int = 60) -> None:
        self.window = window
        self.min_periods = min_periods

    def holdings_path(self, config: Dict[str, Any]) -> Path:
        return resolve_path(config, "soft_history_dir") / "mstr_btc_holdings.csv"

    def _holdings(self, config: Dict[str, Any]) -> pd.Series:
        path = self.holdings_path(config)
        frame = pd.read_csv(path, comment="#", parse_dates=["date"])
        if frame.empty or "date" not in frame.columns or "btc_count" not in frame.columns:
            raise ValueError("expected columns: date, btc_count")
        out = (
            frame.assign(btc_count=pd.to_numeric(frame["btc_count"], errors="coerce"))
            .dropna(subset=["date", "btc_count"])
            .set_index("date")["btc_count"]
            .sort_index()
        )
        if out.empty:
            raise ValueError("no valid holdings rows")
        return out

    def _panel(self, as_of: str, config: Dict[str, Any]) -> tuple[pd.DataFrame, pd.Timestamp]:
        cutoff = pd.Timestamp(str(as_of)[:10])
        store = LocalStore(config)
        mstr_history = store.load_history("MSTR")
        btc_history = store.load_history("BTC-USD")
        if mstr_history.empty:
            raise ValueError("MSTR history missing")
        if btc_history.empty or "Close" not in btc_history:
            raise ValueError("BTC-USD history missing close")
        market_cap = _mstr_market_cap_series(mstr_history)
        if market_cap is None:
            market_cap = _mstr_market_cap_from_shares_file(mstr_history, config)
        if market_cap is None:
            raise ValueError(
                "MSTR market cap unavailable: no market_cap/shares column in history "
                "and no soft_history/mstr_shares_outstanding.csv"
            )
        market_cap = market_cap.loc[mstr_history.index <= cutoff].dropna().sort_index()
        btc_close = pd.to_numeric(btc_history["Close"], errors="coerce").loc[btc_history.index <= cutoff].dropna().sort_index()
        holdings = self._holdings(config).loc[lambda s: s.index <= cutoff]
        if market_cap.empty:
            raise ValueError("no MSTR market cap on or before as_of")
        if btc_close.empty:
            raise ValueError("no BTC close on or before as_of")
        if holdings.empty:
            raise ValueError("no BTC holdings row on or before as_of")

        index = market_cap.index.sort_values()
        panel = pd.DataFrame(index=index)
        panel["mstr_market_cap_usd"] = market_cap.reindex(index).ffill()
        panel["btc_price_usd"] = btc_close.reindex(index, method="ffill")
        panel["mstr_btc_holdings"] = holdings.reindex(index, method="ffill")
        panel = panel.dropna()
        panel = panel[(panel["btc_price_usd"] > 0) & (panel["mstr_btc_holdings"] > 0)]
        if panel.empty:
            raise ValueError("mNAV panel empty after alignment")
        panel["mnav"] = panel["mstr_market_cap_usd"] / (panel["mstr_btc_holdings"] * panel["btc_price_usd"])
        panel["mnav_premium"] = panel["mnav"] - 1.0
        panel = panel.dropna(subset=["mnav_premium"])
        if panel.empty:
            raise ValueError("mNAV premium unavailable after alignment")
        return panel, holdings.index[-1]

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "MSTR_MNAV", False,
                                  reason=f"feature disabled: {self.feature_flag}")
        path = self.holdings_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "MSTR_MNAV", False, quality_penalty=5.0,
                                  reason=f"{self.name} CSV missing — append {path.name}")
        try:
            panel, holdings_date = self._panel(as_of, config)
        except Exception as exc:  # noqa: BLE001
            return SoftDataRecord(self.name, day, None, "MSTR_MNAV", False, quality_penalty=5.0,
                                  reason=f"{self.name} compute failed: {exc}")
        window = panel["mnav_premium"].iloc[-self.window:]
        if len(window.dropna()) < self.min_periods:
            return SoftDataRecord(self.name, day, None, "MSTR_MNAV", False, quality_penalty=5.0,
                                  reason=f"{self.name} insufficient history (need {self.min_periods} days)")
        row = panel.iloc[-1]
        pctl = _finite(_last_percentile(window))
        if pctl is None:
            return SoftDataRecord(self.name, day, None, "MSTR_MNAV", False, quality_penalty=5.0,
                                  reason=f"{self.name} percentile unavailable")
        latency = max(0, (day - panel.index[-1].date()).days)
        return SoftDataRecord(
            self.name, day, pctl, "MSTR_MNAV", True, is_proxy=False,
            latency_days=latency,
            quality_penalty=0.0,
            reason=f"holdings_asof={holdings_date.date().isoformat()}",
            fields={
                "MSTR_valuation_pctl": pctl,
                "mstr_btc_holdings": float(row["mstr_btc_holdings"]),
                "btc_price_usd": float(row["btc_price_usd"]),
                "mstr_market_cap_usd": float(row["mstr_market_cap_usd"]),
                "mnav": float(row["mnav"]),
                "mnav_premium": float(row["mnav_premium"]),
                "mnav_premium_pctl_252": pctl,
            },
        )


# ── MSTR on-chain gate candidates ───────────────────────────────────────────

class OnchainMstrSource:
    """Precomputed Coin Metrics community features for MSTR D-axis gates.

    The CSV is generated by the T16 offline lab with Coin Metrics daily rows
    shifted by one calendar day before US-equity alignment. This source does not
    fetch network data inside production/backtest replay.
    """

    name = "onchain_mstr"
    feature_flag = "data_onchain_mstr"

    def history_path(self, config: Dict[str, Any]) -> Path:
        return resolve_path(config, "soft_history_dir") / "onchain_mstr_features.csv"

    def collect(self, as_of: str, config: Dict[str, Any]) -> SoftDataRecord:
        day = date.fromisoformat(str(as_of)[:10])
        if not bool(config.get("features", {}).get(self.feature_flag, False)):
            return SoftDataRecord(self.name, day, None, "COINMETRICS_COMMUNITY", False,
                                  reason=f"feature disabled: {self.feature_flag}")
        path = self.history_path(config)
        if not path.exists():
            return SoftDataRecord(self.name, day, None, "COINMETRICS_COMMUNITY", False, quality_penalty=5.0,
                                  reason=f"{self.name} CSV missing — run T16 feature export")
        try:
            df = _read_csv_cached(path, parse_dates=["date"])
        except Exception as exc:  # noqa: BLE001
            return SoftDataRecord(self.name, day, None, "COINMETRICS_COMMUNITY", False, quality_penalty=5.0,
                                  reason=f"{self.name} read failed: {exc}")
        required = {"date", "flow_in_ex_mcap_z90", "flow_net_ex_mcap_z90"}
        if df.empty or not required.issubset(df.columns):
            return SoftDataRecord(self.name, day, None, "COINMETRICS_COMMUNITY", False, quality_penalty=5.0,
                                  reason=f"{self.name} CSV malformed (expected {sorted(required)})")
        df = df.set_index("date").sort_index()
        local = df.loc[df.index <= pd.Timestamp(str(as_of)[:10])]
        if local.empty:
            return SoftDataRecord(self.name, day, None, "COINMETRICS_COMMUNITY", False, quality_penalty=5.0,
                                  reason=f"{self.name} no PIT row on or before {as_of}")
        row = local.iloc[-1]
        inflow = _finite(row.get("flow_in_ex_mcap_z90"))
        netflow = _finite(row.get("flow_net_ex_mcap_z90"))
        latency = max(0, (day - local.index[-1].date()).days)
        available = inflow is not None or netflow is not None
        return SoftDataRecord(
            self.name, day, None, "COINMETRICS_COMMUNITY", available, is_proxy=False,
            latency_days=latency,
            quality_penalty=0.0 if available else 5.0,
            reason="" if available else f"{self.name} rolling z-score unavailable",
            fields={
                "cm_exchange_inflow_pressure": inflow,
                "cm_exchange_netflow_pressure": netflow,
            },
        )


# ── registry: which sources are active (flag-gated) ──────────────────────────

def _all_risk_sources() -> List[Any]:
    return [
        # Tier 1 — FRED. Daily-published series get 10d (2 holiday weekends);
        # weekly-published series (DTWEXBGS, NFCI) get 14d — their normal
        # publication lag can reach ~12d around holidays, 10d would false-alarm.
        FredPercentileSource("hy_oas", "data_hy_oas", "BAMLH0A0HYM2", "hy_oas", max_age_days=10),
        FredPercentileSource("real_rate", "data_real_rate", "DFII10", "real_rate_10y", max_age_days=10),
        FredPercentileSource("dollar", "data_dollar", "DTWEXBGS", "dollar_broad", max_age_days=14),
        FredPercentileSource("yield_curve", "data_yield_curve", "T10Y3M", "yield_curve_10y3m", max_age_days=10),
        # Tier 2 — ETF ratios (free, from local OHLCV); 7-day = one week of missing OHLCV is suspicious
        EtfRatioPercentileSource("credit_etf", "data_credit_etf", ["HYG"], ["IEF"], "credit_etf_ratio", max_age_days=7),
        EtfRatioPercentileSource("concentration", "data_concentration", ["RSP"], ["SPY"], "concentration_rsp_spy", max_age_days=7),
        EtfRatioPercentileSource("defensive_rotation", "data_defensive_rotation",
                                 ["XLP", "XLU", "XLV"], ["XLY", "XLI", "XLF"], "defensive_cyclical", max_age_days=7),
        EtfRatioPercentileSource("financial_stress", "data_financial_stress", ["XLF"], ["SPY"], "financial_stress_xlf", max_age_days=7),
        # Axis-A additions (2026-06-08): pre-built financial-conditions composite + bond vol
        FredPercentileSource("nfci", "data_nfci", "NFCI", "nfci", max_age_days=14),
        LevelPercentileSource("move", "data_move", "^MOVE", "move", max_age_days=7),
        # Axis-B: equal-weight vs cap-weight Nasdaq-100 = NDX concentration/breadth
        # (target-relevant for the tech-heavy FNGU/QQQ sleeve; distinct from A14 SPX, A3 components)
        EtfRatioPercentileSource("ndx_concentration", "data_ndx_concentration", ["QQQE"], ["QQQ"], "ndx_concentration", max_age_days=7),
        # CFTC COT: NQ futures asset-mgr + leveraged-fund net long / OI; weekly; orthogonal to price
        CotPercentileSource("cot_nq", "data_cot_nq", "nq", "cot_nq_net_oi_pct"),
        # T19 MSTR on-chain D-axis gate candidates. Default OFF → not registered.
        OnchainMstrSource(),
        # MSTR valuation: B6 mNAV premium percentile, manual holdings + local market data.
        MstrMnavSource(),
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
RISK_ETF_SYMBOLS = ["HYG", "IEF", "RSP", "XLP", "XLU", "XLV", "XLY", "XLI", "XLF", "KRE", "LQD", "^MOVE", "QQQE"]
