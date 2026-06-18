from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

import pandas as pd

from ..config import load_config, resolve_path
from ..core.data.store import safe_symbol
from ..core.safe_io import atomic_write_csv


ROUTE_LEGS = ["BRK.B", "BOXX", "DBMF", "BIL", "SHV"]
EXTRA_MARKET = ["^VIX9D", "^SKEW", "^VVIX"]
YFINANCE_SYMBOL_MAP = {"BRK.B": "BRK-B"}
ONLINE_SOFT_HISTORY_SYMBOLS_BY_FLAG = {
    "data_credit_etf": ["HYG", "IEF"],
    "data_concentration": ["RSP", "SPY"],
    "data_defensive_rotation": ["XLP", "XLU", "XLV", "XLY", "XLI", "XLF"],
    "data_financial_stress": ["XLF", "SPY"],
    "data_move": ["^MOVE"],
    "data_ndx_concentration": ["QQQE", "QQQ"],
}


@dataclass(frozen=True)
class BackfillResult:
    symbol: str
    source_symbol: str
    path: str
    start_date: Optional[str]
    end_date: Optional[str]
    row_count: int
    missing_weekdays: int
    updated: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


Downloader = Callable[[str, str, Optional[str]], pd.DataFrame]


def all_backfill_symbols(config: Optional[Dict[str, object]] = None) -> list[str]:
    cfg = config or load_config()
    symbols = set(cfg.get("symbols", {}).keys())
    symbols.update(cfg.get("market_symbols", []))
    symbols.update(EXTRA_MARKET)
    symbols.update(ROUTE_LEGS)
    symbols.update(online_soft_history_symbols(cfg))
    for values in cfg.get("radars", {}).values():
        symbols.update(values)
    for values in cfg.get("component_proxies", {}).values():
        symbols.update(values)
    return sorted(symbols)


def online_soft_history_symbols(config: Optional[Dict[str, object]] = None) -> list[str]:
    cfg = config or load_config()
    features = cfg.get("features", {})
    if not isinstance(features, dict):
        return []
    symbols: set[str] = set()
    for flag, deps in ONLINE_SOFT_HISTORY_SYMBOLS_BY_FLAG.items():
        if features.get(flag):
            symbols.update(deps)
    return sorted(symbols)


def backfill(
    symbols: list[str],
    start: str = "2018-01-01",
    end: Optional[str] = None,
    store_dir: str | Path = "data/history",
    downloader: Optional[Downloader] = None,
    repair_overlap_days: int = 0,
) -> Dict[str, BackfillResult]:
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    out: Dict[str, BackfillResult] = {}
    for symbol in symbols:
        out[symbol] = _backfill_one(symbol, start, end, store, downloader or _download_yfinance, repair_overlap_days=repair_overlap_days)
    return out


def write_coverage_report(results: Dict[str, BackfillResult], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "| Symbol | Source | Start | End | Rows | Missing Weekdays | Updated | Note |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for symbol, result in sorted(results.items()):
        rows.append(
            f"| {symbol} | {result.source_symbol} | {result.start_date or '-'} | {result.end_date or '-'} | "
            f"{result.row_count} | {result.missing_weekdays} | {result.updated} | {result.reason or '-'} |"
        )
    path.write_text(
        "# N0 History Coverage\n\n"
        f"Generated: {date.today().isoformat()}\n\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    return path


def _backfill_one(
    symbol: str,
    start: str,
    end: Optional[str],
    store_dir: Path,
    downloader: Downloader,
    repair_overlap_days: int = 0,
) -> BackfillResult:
    path = store_dir / f"{safe_symbol(symbol)}.csv"
    existing = _read_existing(path)
    intervals: list[tuple[str, Optional[str]]] = []
    if not existing.empty:
        first = existing.index.min().date()
        last = existing.index.max().date()
        if pd.Timestamp(start).date() < first:
            intervals.append((start, first.isoformat()))
        tail_date = last + timedelta(days=1)
        if repair_overlap_days > 0:
            tail_date = max(pd.Timestamp(start).date(), last - timedelta(days=int(repair_overlap_days)))
        tail_start = tail_date.isoformat()
        if end is None or pd.Timestamp(tail_start) <= pd.Timestamp(end):
            intervals.append((tail_start, end))
    else:
        intervals.append((start, end))
    if not intervals:
        return _result(symbol, path, existing, updated=False, source_symbol=_yf_symbol(symbol), reason="already current")
    downloaded_frames: list[pd.DataFrame] = []
    reasons: list[str] = []
    for fetch_start, fetch_end in intervals:
        try:
            chunk = _normalize_download(downloader(_yf_symbol(symbol), fetch_start, fetch_end),
                                        expected_symbol=_yf_symbol(symbol))
            if chunk.empty:
                reasons.append(f"{fetch_start}->{fetch_end or 'latest'} returned no rows")
            downloaded_frames.append(chunk)
        except Exception as exc:
            reasons.append(f"{fetch_start}->{fetch_end or 'latest'} failed: {exc}")
    normalized = pd.concat(downloaded_frames).sort_index() if downloaded_frames else pd.DataFrame()
    if not normalized.empty and not existing.empty:
        sane, why = _sanity_check_download(symbol, existing, normalized)
        if not sane:
            print(f"[backfill] WARNING {symbol}: download REJECTED ({why}); keeping cached history")
            return _result(symbol, path, existing, updated=False,
                           source_symbol=_yf_symbol(symbol),
                           reason=f"REJECTED corrupt download: {why}")
    combined = pd.concat([existing, normalized]).sort_index()
    if not combined.empty:
        combined = combined[~combined.index.duplicated(keep="last")]
        _write_history(path, combined)
    return _result(symbol, path, combined, updated=not normalized.empty, source_symbol=_yf_symbol(symbol), reason="; ".join(reasons))


def _sanity_check_download(symbol: str, existing: pd.DataFrame, new: pd.DataFrame) -> tuple[bool, str]:
    """Reject cross-wired downloads (2026-06-12 incident: under Yahoo rate
    limiting, yfinance returned other tickers' prices — QQQ got ~218 bars,
    ^VIX got ^SOX values — firing QQQ-family hard valves on garbage).

    Overlap case: anchor on the OLDEST overlapping date (pre-corruption in a
    repair window) and require ±25% agreement. Pure append: bound the
    boundary jump — ±50% for equities/ETFs, ±200% for ^vol indices (VIX can
    legitimately double in a day; the cross-wiring deltas were 10-600x).
    """
    try:
        ex_close = pd.to_numeric(existing["Close"], errors="coerce").dropna()
        new_close = pd.to_numeric(new["Close"], errors="coerce").dropna()
        if ex_close.empty or new_close.empty:
            return True, ""
        overlap = new_close.index.intersection(ex_close.index)
        if len(overlap):
            # Majority vote over up to 3 oldest overlapping dates: a single
            # corrupt CACHED anchor row must not permanently veto a good
            # repair (the KLAC manual-surgery case). Garbage downloads still
            # lose every vote.
            anchors = sorted(overlap)[:3]
            agree = 0
            ratios = []
            for anchor in anchors:
                ratio = float(new_close.loc[anchor]) / float(ex_close.loc[anchor])
                ratios.append(f"{anchor.date()} x{ratio:.2f}")
                if 0.75 <= ratio <= 1.33:
                    agree += 1
            if agree * 2 <= len(anchors):     # strict majority required
                return False, f"anchor majority failed ({agree}/{len(anchors)}: {', '.join(ratios)})"
            return True, ""
        limit = 3.0 if symbol.startswith("^") else 1.5
        ratio = float(new_close.iloc[0]) / float(ex_close.iloc[-1])
        if not (1.0 / limit <= ratio <= limit):
            return False, f"boundary jump x{ratio:.2f} ({ex_close.index[-1].date()} -> {new_close.index[0].date()})"
        return True, ""
    except Exception as exc:
        return False, f"sanity check error: {exc!r}"


def _read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame = frame.rename(columns={"date": "Date", "open": "Open", "high": "High", "low": "Low", "close": "Close", "adj_close": "Adj Close", "volume": "Volume"})
    if "Date" not in frame:
        return pd.DataFrame()
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).set_index("Date").sort_index()
    return frame[[col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in frame.columns]]


def _normalize_download(frame: pd.DataFrame, expected_symbol: str | None = None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        # Deterministic cross-wiring detection: yfinance carries the ticker in
        # level 1 — flattening used to discard it, leaving only price-jump
        # heuristics to catch Yahoo serving another request's payload
        # (2026-06-12 incident). A name mismatch is rejected outright.
        tickers = {str(t) for t in out.columns.get_level_values(-1) if str(t)}
        if expected_symbol and tickers and tickers != {expected_symbol}:
            raise ValueError(f"ticker mismatch: downloaded {sorted(tickers)} for {expected_symbol}")
        out.columns = [col[0] for col in out.columns]
    rename = {"AdjClose": "Adj Close", "adjclose": "Adj Close", "adj_close": "Adj Close"}
    out = out.rename(columns=rename)
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
        out = out.dropna(subset=["Date"]).set_index("Date")
    out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    columns = [col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in out.columns]
    out = out[columns]
    for col in columns:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "Adj Close" not in out and "Close" in out:
        out["Adj Close"] = out["Close"]
    return out[[col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in out.columns]]


def _write_history(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    out.index.name = "date"
    out = out.reset_index()
    out = out.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    atomic_write_csv(out[["date", "open", "high", "low", "close", "adj_close", "volume"]], path, index=False)


def _result(symbol: str, path: Path, frame: pd.DataFrame, updated: bool, source_symbol: str, reason: str = "") -> BackfillResult:
    if frame.empty:
        return BackfillResult(symbol, source_symbol, str(path), None, None, 0, 0, updated, reason or "no rows")
    start = frame.index.min().date()
    end = frame.index.max().date()
    expected = pd.bdate_range(start, end)
    missing = len(expected.difference(pd.DatetimeIndex(frame.index.normalize().unique())))
    return BackfillResult(symbol, source_symbol, str(path), start.isoformat(), end.isoformat(), int(len(frame)), int(missing), updated, reason)


def _download_yfinance(symbol: str, start: str, end: Optional[str]) -> pd.DataFrame:
    import yfinance as yf  # type: ignore

    return yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)


def _yf_symbol(symbol: str) -> str:
    return YFINANCE_SYMBOL_MAP.get(symbol, symbol)


def default_store_dir() -> Path:
    return resolve_path(load_config(), "history_dir")
