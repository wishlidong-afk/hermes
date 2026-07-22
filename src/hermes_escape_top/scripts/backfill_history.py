from __future__ import annotations

import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

import pandas as pd
from dateutil.easter import easter

from ..config import load_config, resolve_path
from ..core.data.market_admission import (
    MarketAdmissionSession,
    market_admission_evidence_paths,
    prepare_market_admission_session,
    write_market_admission_evidence,
)
from ..core.data.history_transaction import (
    HistoryPromotionTransaction,
    recover_history_transactions,
)
from ..core.data.market_witness import is_alpaca_supported_symbol
from ..core.data.external_sources.cboe_indices import CBOE_INDEX_SYMBOLS
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


# Mirrors yfinance: start is inclusive and end is exclusive when provided.
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
    if bool((cfg.get("features") or {}).get("use_cboe_official_indices", False)):
        symbols.difference_update(CBOE_INDEX_SYMBOLS)
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
    admission_session: MarketAdmissionSession | None = None,
    admission_archive: str | Path | None = None,
    repair_history_head: bool = False,
) -> Dict[str, BackfillResult]:
    config = load_config()
    if bool((config.get("features") or {}).get("use_cboe_official_indices", False)):
        forbidden = sorted(set(symbols).intersection(CBOE_INDEX_SYMBOLS))
        if forbidden:
            raise PermissionError(
                "CBOE official writer owns canonical history for: "
                + ", ".join(forbidden)
            )
    store = Path(store_dir)
    store.mkdir(parents=True, exist_ok=True)
    admission_archive_path = Path(admission_archive) if admission_archive is not None else None
    allowed_roots = [store]
    if (config.get("paths") or {}).get("archive_dir"):
        configured_archive_path = resolve_path(config, "archive_dir")
        if configured_archive_path not in allowed_roots:
            allowed_roots.append(configured_archive_path)
    if admission_archive_path is not None and admission_archive_path not in allowed_roots:
        allowed_roots.append(admission_archive_path)
    recovered = recover_history_transactions(store, allowed_roots=allowed_roots)
    if recovered:
        print(f"[backfill] recovered interrupted history transactions: {', '.join(recovered)}")

    active_admission = admission_session
    if active_admission is None and downloader is None:
        if bool((config.get("features") or {}).get("use_market_admission_gate", False)):
            btc_spot_witness_enabled = bool(
                (config.get("features") or {}).get("use_btc_spot_witness", False)
            )
            admission_start = _market_admission_start(
                symbols,
                store,
                start,
                repair_overlap_days,
                btc_spot_witness_enabled=btc_spot_witness_enabled,
                repair_history_head=repair_history_head,
            )
            admission_end = str(end)[:10] if end else (date.today() + timedelta(days=1)).isoformat()
            admission_kwargs = (
                {"btc_spot_witness_enabled": True}
                if btc_spot_witness_enabled
                else {}
            )
            active_admission = prepare_market_admission_session(
                symbols,
                admission_start,
                admission_end,
                **admission_kwargs,
            )
            admission_archive_path = resolve_path(config, "archive_dir")
    if admission_archive_path is not None:
        if admission_archive_path not in allowed_roots:
            allowed_roots.append(admission_archive_path)
    transaction = HistoryPromotionTransaction(
        store,
        allowed_roots=allowed_roots,
        operation_id=(active_admission.operation_id if active_admission is not None else None),
    )
    out: Dict[str, BackfillResult] = {}
    snapshots = {
        store / f"{safe_symbol(symbol)}.csv": _history_snapshot(
            store / f"{safe_symbol(symbol)}.csv"
        )
        for symbol in symbols
    } if active_admission is not None and active_admission.enabled else {}
    try:
        for symbol in symbols:
            out[symbol] = _backfill_one(
                symbol,
                start,
                end,
                store,
                downloader or _download_yfinance,
                repair_overlap_days=repair_overlap_days,
                admission_session=active_admission,
                repair_history_head=repair_history_head,
                history_transaction=transaction,
            )
        if active_admission is not None and admission_archive_path is not None:
            for evidence_path in market_admission_evidence_paths(
                admission_archive_path,
                active_admission.payload(),
            ):
                transaction.track_path(evidence_path)
        transaction.prepare()
        transaction.promote()
        if active_admission is not None:
            active_admission.bind_canonical_files(store, symbols)
        if active_admission is not None and admission_archive_path is not None:
            write_market_admission_evidence(
                admission_archive_path,
                active_admission.payload(),
            )
        transaction.mark_committed()
    except BaseException as exc:
        rollback_error: BaseException | None = None
        try:
            transaction.rollback()
        except BaseException as restore_exc:
            rollback_error = restore_exc
        for path, snapshot in snapshots.items():
            try:
                _restore_history_snapshot(path, snapshot)
            except BaseException as restore_exc:
                rollback_error = restore_exc
        if active_admission is not None:
            active_admission.run_error = f"{exc.__class__.__name__}: {exc}"
            active_admission.bind_canonical_files(store, symbols)
        evidence_error: BaseException | None = None
        if active_admission is not None and admission_archive_path is not None:
            try:
                write_market_admission_evidence(
                    admission_archive_path,
                    active_admission.payload(),
                )
            except BaseException as write_exc:
                evidence_error = write_exc
        if rollback_error is not None or evidence_error is not None:
            raise RuntimeError(
                "market admission failed and rollback/evidence recovery was incomplete: "
                f"rollback={rollback_error!r} evidence={evidence_error!r}"
            ) from (rollback_error or evidence_error)
        raise
    return out


def _history_snapshot(path: Path) -> tuple[bool, bytes, int | None]:
    if not path.exists():
        return False, b"", None
    return True, path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def _restore_history_snapshot(
    path: Path,
    snapshot: tuple[bool, bytes, int | None],
) -> None:
    existed, content, mode = snapshot
    if not existed:
        path.unlink(missing_ok=True)
        return
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.rollback.")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temp.chmod(mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _market_admission_start(
    symbols: Iterable[str],
    store_dir: Path,
    configured_start: str,
    repair_overlap_days: int,
    *,
    btc_spot_witness_enabled: bool = False,
    repair_history_head: bool = False,
) -> str:
    floor = pd.Timestamp(configured_start).date()
    starts: list[date] = []
    for symbol in symbols:
        if not is_alpaca_supported_symbol(symbol) and not (
            btc_spot_witness_enabled and str(symbol).upper() == "BTC-USD"
        ):
            continue
        existing = _read_existing(store_dir / f"{safe_symbol(symbol)}.csv")
        if existing.empty:
            starts.append(floor)
            continue
        first = existing.index.min().date()
        last = existing.index.max().date()
        tail_start = max(floor, last - timedelta(days=max(0, int(repair_overlap_days))))
        starts.append(
            floor
            if repair_history_head and floor < first
            else tail_start
        )
    return min(starts, default=floor).isoformat()


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
    admission_session: MarketAdmissionSession | None = None,
    repair_history_head: bool = False,
    history_transaction: HistoryPromotionTransaction | None = None,
) -> BackfillResult:
    path = store_dir / f"{safe_symbol(symbol)}.csv"
    existing = _read_existing(path)
    intervals: list[tuple[str, Optional[str]]] = []
    if not existing.empty:
        first = existing.index.min().date()
        last = existing.index.max().date()
        if repair_history_head and pd.Timestamp(start).date() < first:
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
        calendar_days = bool(
            admission_session is not None
            and admission_session.uses_calendar_days(symbol)
        )
        if not existing.empty and not _interval_has_probable_trading_day(
            fetch_start,
            fetch_end,
            calendar_days=calendar_days,
        ):
            reasons.append(f"{fetch_start}->{fetch_end or 'latest'} skipped no trading days")
            continue
        try:
            chunk = _normalize_download(downloader(_yf_symbol(symbol), fetch_start, fetch_end),
                                        expected_symbol=_yf_symbol(symbol))
            candidate_rows = len(chunk)
            chunk = _clip_download_to_interval(chunk, fetch_start, fetch_end)
            clipped_rows = candidate_rows - len(chunk)
            if clipped_rows:
                reasons.append(
                    f"{fetch_start}->{fetch_end or 'latest'} clipped {clipped_rows} out-of-range rows"
                )
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
    if admission_session is not None and not normalized.empty:
        candidate_rows = len(normalized)
        normalized, _ = admission_session.admit(symbol, normalized)
        frozen_rows = candidate_rows - len(normalized)
        if frozen_rows:
            reasons.append(f"market admission froze {frozen_rows}/{candidate_rows} rows")
        if normalized.empty:
            return _result(
                symbol,
                path,
                existing,
                updated=False,
                source_symbol=_yf_symbol(symbol),
                reason="; ".join(reasons),
            )
    combined = pd.concat([existing, normalized]).sort_index()
    if not combined.empty:
        combined = combined[~combined.index.duplicated(keep="last")]
        _write_history(path, combined, history_transaction=history_transaction)
    return _result(symbol, path, combined, updated=not normalized.empty, source_symbol=_yf_symbol(symbol), reason="; ".join(reasons))


def _clip_download_to_interval(
    frame: pd.DataFrame,
    start: str,
    end: Optional[str],
) -> pd.DataFrame:
    if frame.empty:
        return frame
    start_date = pd.Timestamp(start).date()
    end_date = pd.Timestamp(end).date() if end is not None else None
    dates = pd.DatetimeIndex(frame.index).date
    mask = dates >= start_date
    if end_date is not None:
        mask &= dates < end_date
    return frame.loc[mask]


def _interval_has_probable_trading_day(
    start: str,
    end: Optional[str],
    *,
    calendar_days: bool = False,
) -> bool:
    if end is None:
        return True
    try:
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
    except Exception:
        return True
    if start_ts >= end_ts:
        return False
    if calendar_days:
        return True
    business_days = pd.bdate_range(start_ts, end_ts - pd.Timedelta(days=1))
    if business_days.empty:
        return False
    holidays = _likely_nyse_full_holidays(business_days.min().date(), business_days.max().date())
    return any(day.date() not in holidays for day in business_days)


def _likely_nyse_full_holidays(start: date, end: date) -> set[date]:
    out: set[date] = set()
    for year in range(start.year - 1, end.year + 2):
        out.add(_observed_weekday(date(year, 1, 1)))          # New Year's Day
        out.add(_nth_weekday(year, 1, 0, 3))                  # MLK Day
        out.add(_nth_weekday(year, 2, 0, 3))                  # Washington's Birthday
        out.add(easter(year) - timedelta(days=2))             # Good Friday
        out.add(_last_weekday(year, 5, 0))                    # Memorial Day
        if year >= 2022:
            out.add(_observed_weekday(date(year, 6, 19)))     # Juneteenth
        out.add(_observed_weekday(date(year, 7, 4)))          # Independence Day
        out.add(_nth_weekday(year, 9, 0, 1))                  # Labor Day
        out.add(_nth_weekday(year, 11, 3, 4))                 # Thanksgiving
        out.add(_observed_weekday(date(year, 12, 25)))        # Christmas
    return {day for day in out if start <= day <= end}


def _observed_weekday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    day = date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        day = date(year, month + 1, 1) - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


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
    if "Close" in out:
        # Vendors can expose an in-progress row with OH(L) populated but no
        # settled close. Never let that partial row replace a valid cached bar.
        out = out[out["Close"].notna() & (out["Close"] > 0)]
    if "Adj Close" not in out and "Close" in out:
        out["Adj Close"] = out["Close"]
    elif "Adj Close" in out and "Close" in out:
        out["Adj Close"] = out["Adj Close"].fillna(out["Close"])
    return out[[col for col in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if col in out.columns]]


def _write_history(
    path: Path,
    frame: pd.DataFrame,
    *,
    history_transaction: HistoryPromotionTransaction | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    out.index.name = "date"
    out = out.reset_index()
    out = out.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
    canonical = out[["date", "open", "high", "low", "close", "adj_close", "volume"]]
    if history_transaction is not None:
        history_transaction.stage_bytes(path, canonical.to_csv(index=False).encode("utf-8"))
    else:
        atomic_write_csv(canonical, path, index=False)


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
