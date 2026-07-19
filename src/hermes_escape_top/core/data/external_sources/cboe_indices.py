from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Callable

import pandas as pd

from ..market_clock import latest_completed_us_market_session
from .registry import ExternalSourceSpec


@dataclass(frozen=True)
class CboeIndexDefinition:
    source_id: str
    symbol: str
    file_name: str
    value_column: str
    minimum: float
    maximum: float

    @property
    def url(self) -> str:
        return f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{self.file_name}"


CBOE_INDEX_DEFINITIONS = {
    definition.source_id: definition
    for definition in (
        CboeIndexDefinition("cboe_vix", "^VIX", "VIX_History.csv", "CLOSE", 1.0, 200.0),
        CboeIndexDefinition("cboe_vix3m", "^VIX3M", "VIX3M_History.csv", "CLOSE", 1.0, 200.0),
        CboeIndexDefinition("cboe_vix9d", "^VIX9D", "VIX9D_History.csv", "CLOSE", 1.0, 250.0),
        CboeIndexDefinition("cboe_skew", "^SKEW", "SKEW_History.csv", "SKEW", 50.0, 250.0),
        CboeIndexDefinition("cboe_vvix", "^VVIX", "VVIX_History.csv", "VVIX", 10.0, 300.0),
    )
}

CBOE_INDEX_SYMBOLS = frozenset(
    definition.symbol for definition in CBOE_INDEX_DEFINITIONS.values()
)

FetchText = Callable[[str], str]
FetchWitness = Callable[[str, str, str], pd.DataFrame]


class CboeVolatilityIndexAdapter:
    def __init__(
        self,
        definition: CboeIndexDefinition,
        *,
        fetch_text: FetchText | None = None,
        fetch_witness: FetchWitness | None = None,
        now: datetime | None = None,
        seed_path: Path | None = None,
    ) -> None:
        self.definition = definition
        self.fetch_text = fetch_text or _requests_text
        self.fetch_witness = fetch_witness or _fetch_yahoo_witness
        self.now = now
        self.seed_path = Path(seed_path) if seed_path is not None else None

    def fetch_raw(self) -> dict[str, object]:
        csv_text = self.fetch_text(self.definition.url)
        completed = latest_completed_us_market_session(self.now)
        official = parse_cboe_index_csv(self.definition, csv_text)
        official = official[official["date"] <= completed.isoformat()]
        witness_rows: list[dict[str, object]] = []
        witness_error: str | None = None
        if official.empty:
            witness_error = "official file has no completed sessions"
        else:
            latest = pd.Timestamp(official.iloc[-1]["date"]).date()
            start = (latest - timedelta(days=14)).isoformat()
            end = (latest + timedelta(days=1)).isoformat()
            try:
                witness = _normalize_witness(
                    self.fetch_witness(self.definition.symbol, start, end),
                    self.definition.symbol,
                )
                witness_rows = witness.reset_index().to_dict(orient="records")
            except Exception as exc:
                witness_error = f"{exc.__class__.__name__}: {exc}"
        return {
            "source_url": self.definition.url,
            "file_name": self.definition.file_name,
            "content_sha256": hashlib.sha256(csv_text.encode("utf-8")).hexdigest(),
            "csv_text": csv_text,
            "completed_through": completed.isoformat(),
            "ohlc_repair_count": int(official.attrs.get("ohlc_repair_count", 0)),
            "witness_source": "Yahoo Finance daily history",
            "witness_rows": witness_rows,
            "witness_error": witness_error,
        }

    def parse(self, raw: dict[str, object]) -> pd.DataFrame:
        frame = parse_cboe_index_csv(
            self.definition,
            str(raw.get("csv_text") or ""),
        )
        completed = str(raw.get("completed_through") or "")[:10]
        if completed:
            frame = frame[frame["date"] <= completed].reset_index(drop=True)
        witness_rows = list(raw.get("witness_rows") or [])
        witness_dates = pd.to_datetime(
            [row.get("Date") for row in witness_rows if isinstance(row, dict)],
            errors="coerce",
            utc=True,
        )
        witness_dates = pd.DatetimeIndex(witness_dates).dropna()
        witness_latest = (
            witness_dates.max().tz_localize(None).date().isoformat()
            if len(witness_dates)
            else ""
        )
        official_latest = str(frame.iloc[-1]["date"]) if not frame.empty else ""
        certified_latest = _latest_seed_as_of(self.seed_path)
        # A regressed secondary witness cannot revoke a tail already certified
        # against these same official rows; continuity validation still checks it.
        preserved_certified_tail = bool(
            witness_latest
            and certified_latest
            and witness_latest < certified_latest <= official_latest
        )
        if witness_latest:
            cutoff = certified_latest if preserved_certified_tail else witness_latest
            frame = frame[frame["date"] <= cutoff].reset_index(drop=True)
        frame.attrs["completed_through"] = completed
        frame.attrs["official_latest_as_of"] = official_latest
        frame.attrs["witness_latest_as_of"] = witness_latest
        frame.attrs["certified_latest_as_of"] = certified_latest
        frame.attrs["certified_tail_preserved"] = preserved_certified_tail
        retained_latest = str(frame.iloc[-1]["date"]) if not frame.empty else ""
        frame.attrs["unconfirmed_tail_trimmed"] = bool(
            official_latest
            and witness_latest
            and (not retained_latest or retained_latest < official_latest)
        )
        frame.attrs["ohlc_repair_count"] = int(raw.get("ohlc_repair_count") or 0)
        frame.attrs["witness_rows"] = witness_rows
        frame.attrs["witness_error"] = raw.get("witness_error")
        return frame


def parse_cboe_index_csv(
    definition: CboeIndexDefinition,
    csv_text: str,
) -> pd.DataFrame:
    raw = pd.read_csv(StringIO(csv_text))
    raw.columns = [str(column).strip().upper() for column in raw.columns]
    if "DATE" not in raw.columns or definition.value_column not in raw.columns:
        raise ValueError(
            f"{definition.file_name} missing DATE/{definition.value_column} columns"
        )
    dates = pd.to_datetime(raw["DATE"], errors="coerce")
    close = pd.to_numeric(raw[definition.value_column], errors="coerce")
    if {"OPEN", "HIGH", "LOW", "CLOSE"}.issubset(raw.columns):
        open_ = pd.to_numeric(raw["OPEN"], errors="coerce")
        high = pd.to_numeric(raw["HIGH"], errors="coerce")
        low = pd.to_numeric(raw["LOW"], errors="coerce")
    else:
        open_ = close.copy()
        high = close.copy()
        low = close.copy()
    out = pd.DataFrame(
        {
            "date": dates.dt.strftime("%Y-%m-%d"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": 0.0,
        }
    )
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    invalid_ohlc = (
        (out["high"] < out[["open", "close"]].max(axis=1))
        | (out["low"] > out[["open", "close"]].min(axis=1))
        | (out["low"] > out["high"])
    )
    repair_count = int(invalid_ohlc.sum())
    if repair_count:
        for column in ("open", "high", "low"):
            out.loc[invalid_ohlc, column] = out.loc[invalid_ohlc, "close"]
    out = out.reset_index(drop=True)
    out.attrs["ohlc_repair_count"] = repair_count
    return out


def cboe_index_spec(
    definition: CboeIndexDefinition,
    target_path: Path,
    *,
    min_rows: int = 60,
    allow_initial_rebaseline: bool = False,
) -> ExternalSourceSpec:
    target = Path(target_path)

    def validate(frame: pd.DataFrame) -> str | None:
        semantic_error = _validate_cboe_index(definition, frame)
        if semantic_error is not None:
            return semantic_error
        return _validate_history_continuity(
            target,
            frame,
            allow_initial_rebaseline=allow_initial_rebaseline,
        )

    return ExternalSourceSpec(
        source_id=definition.source_id,
        target_path=target,
        required_columns=("date", "open", "high", "low", "close", "adj_close", "volume"),
        min_rows=min_rows,
        semantic_validator=validate,
        pit_rule=(
            "controlled_initial_rebaseline_then_daily_witness"
            if allow_initial_rebaseline
            else "official_close_after_completed_us_session_with_yahoo_witness"
        ),
        source_url=definition.url,
        allow_validated_same_date_promotion=True,
    )


def _validate_cboe_index(
    definition: CboeIndexDefinition,
    frame: pd.DataFrame,
) -> str | None:
    values = frame[["open", "high", "low", "close", "adj_close"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if values.isna().any().any():
        return "official index file contains non-numeric OHLC values"
    if not values["close"].between(definition.minimum, definition.maximum).all():
        return (
            f"official close outside semantic range "
            f"[{definition.minimum}, {definition.maximum}]"
        )
    invalid_ohlc = (
        (values["high"] < values[["open", "close"]].max(axis=1))
        | (values["low"] > values[["open", "close"]].min(axis=1))
        | (values["low"] > values["high"])
    )
    if invalid_ohlc.any():
        return "official index file violates OHLC ordering"
    witness_error = frame.attrs.get("witness_error")
    if witness_error:
        return f"Yahoo witness unavailable: {witness_error}"
    witness_rows = frame.attrs.get("witness_rows") or []
    witness = pd.DataFrame(witness_rows)
    if witness.empty or "Date" not in witness or "Close" not in witness:
        return "Yahoo witness unavailable: no normalized rows"
    witness["Date"] = pd.to_datetime(witness["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    witness["Close"] = pd.to_numeric(witness["Close"], errors="coerce")
    witness = witness.dropna(subset=["Date", "Close"]).drop_duplicates("Date", keep="last")
    official = frame[["date", "close"]].copy()
    latest = str(official.iloc[-1]["date"])
    latest_witness = witness[witness["Date"] == latest]
    certified_tail_preserved = bool(frame.attrs.get("certified_tail_preserved"))
    if latest_witness.empty and not certified_tail_preserved:
        return f"Yahoo witness missing latest official session {latest}"
    witness_latest = str(frame.attrs.get("witness_latest_as_of") or "")
    comparison_source = official
    if certified_tail_preserved and witness_latest:
        comparison_source = official[official["date"] <= witness_latest]
    comparison = comparison_source.tail(3).merge(
        witness,
        left_on="date",
        right_on="Date",
        how="inner",
    )
    if comparison.empty:
        return "Yahoo witness unavailable: no overlapping official rows"
    for row in comparison.itertuples(index=False):
        official_close = float(row.close)
        witness_close = float(row.Close)
        tolerance = max(0.25, abs(official_close) * 0.02)
        if abs(official_close - witness_close) > tolerance:
            return (
                f"Yahoo witness mismatch {row.date}: official={official_close:.4f} "
                f"witness={witness_close:.4f} tolerance={tolerance:.4f}"
            )
    return None


def _validate_history_continuity(
    target_path: Path,
    frame: pd.DataFrame,
    *,
    allow_initial_rebaseline: bool,
) -> str | None:
    if allow_initial_rebaseline:
        return None
    if not target_path.exists():
        return (
            "history continuity: canonical missing; controlled initial "
            "rebaseline is required"
        )
    try:
        existing = pd.read_csv(target_path)
    except Exception as exc:
        return f"history continuity: existing canonical cannot be read: {exc}"
    existing_dates = pd.to_datetime(existing["date"], errors="coerce").dropna()
    incoming_dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if existing_dates.empty:
        return (
            "history continuity: canonical has no valid dates; controlled "
            "initial rebaseline is required"
        )
    if incoming_dates.empty:
        return "history continuity: incoming official history is empty"
    existing_days = set(existing_dates.dt.strftime("%Y-%m-%d"))
    incoming_days = set(incoming_dates.dt.strftime("%Y-%m-%d"))
    missing = sorted(existing_days - incoming_days)
    if missing:
        return (
            f"history continuity: missing {len(missing)} existing dates "
            f"({', '.join(missing[:5])})"
        )
    if incoming_dates.min() > existing_dates.min():
        return (
            "history continuity: incoming start "
            f"{incoming_dates.min().date().isoformat()} is later than canonical start "
            f"{existing_dates.min().date().isoformat()}"
        )
    if len(frame) < len(existing):
        return (
            f"history continuity: incoming rows {len(frame)} below canonical rows "
            f"{len(existing)}"
        )
    existing_values = existing.copy()
    incoming_values = frame.copy()
    existing_values["_day"] = pd.to_datetime(
        existing_values["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    incoming_values["_day"] = pd.to_datetime(
        incoming_values["date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    common = existing_values.merge(
        incoming_values,
        on="_day",
        suffixes=("_existing", "_incoming"),
    )
    for column in ("open", "high", "low", "close", "adj_close", "volume"):
        existing_column = f"{column}_existing"
        incoming_column = f"{column}_incoming"
        if existing_column not in common or incoming_column not in common:
            return f"history continuity: missing comparison column {column}"
        old = pd.to_numeric(common[existing_column], errors="coerce")
        new = pd.to_numeric(common[incoming_column], errors="coerce")
        mismatch = old.isna() != new.isna()
        mismatch |= (old - new).abs().fillna(0.0) > 1e-9
        if mismatch.any():
            changed_day = str(common.loc[mismatch, "_day"].iloc[0])
            return f"history continuity: changed existing row {changed_day} column {column}"
    return None


def _normalize_witness(frame: pd.DataFrame, expected_symbol: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError("empty Yahoo witness")
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        tickers = {str(value) for value in out.columns.get_level_values(-1) if str(value)}
        if tickers and tickers != {expected_symbol}:
            raise ValueError(
                f"Yahoo witness ticker mismatch: expected {expected_symbol}, got {sorted(tickers)}"
            )
        out.columns = [column[0] for column in out.columns]
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
        out = out.dropna(subset=["Date"]).set_index("Date")
    if "Close" not in out.columns:
        raise ValueError("Yahoo witness missing Close")
    out.index = pd.to_datetime(out.index, errors="coerce", utc=True).tz_localize(None).normalize()
    out = out[~out.index.isna()]
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    out = out.dropna(subset=["Close"])
    out.index.name = "Date"
    return out[["Close"]].sort_index()


def _latest_seed_as_of(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    try:
        frame = pd.read_csv(path, usecols=["date"])
    except Exception:
        return ""
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return dates.max().date().isoformat() if not dates.empty else ""


def _requests_text(url: str) -> str:
    import requests  # type: ignore

    response = requests.get(
        url,
        headers={"User-Agent": "Hermes/1.0 official-index-refresh"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def _fetch_yahoo_witness(symbol: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf  # type: ignore

    return yf.download(
        symbol,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
