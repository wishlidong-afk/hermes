from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urlencode
import urllib.request

import pandas as pd

from ..macro import FredNetLiquiditySource, fetch_fred_graph_csv, fred_net_liquidity_frame
from ..risk_signals import _last_percentile, fetch_fred_series_frame, fred_api_key
from .provenance import source_provenance
from .registry import ExternalSourceSpec


FetchFredFrame = Callable[..., pd.DataFrame]
FetchFredSeries = Callable[..., pd.Series]
FetchText = Callable[[str], str]
FetchReleaseCalendar = Callable[[tuple[str, ...], dict[str, Any] | None], dict[str, Any]]


def fetch_fred_release_calendar(
    release_ids: tuple[str, ...],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch exact publisher dates without making canonical refresh depend on them."""
    ids = tuple(str(value) for value in release_ids if str(value).strip())
    if not ids:
        return {
            "status": "UNAVAILABLE",
            "release_dates_by_id": {},
            "error": "FRED release calendar requires release IDs",
        }
    key = fred_api_key(config)
    if not key:
        return {
            "status": "UNAVAILABLE",
            "release_dates_by_id": {},
            "error": "FRED release calendar requires an API key",
        }
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=120)
    end = today + timedelta(days=60)
    dates_by_id: dict[str, list[str]] = {}
    try:
        for release_id in ids:
            params = {
                "release_id": release_id,
                "api_key": key,
                "file_type": "json",
                "realtime_start": start.isoformat(),
                "realtime_end": end.isoformat(),
                "include_release_dates_with_no_data": "true",
                "sort_order": "asc",
            }
            request = urllib.request.Request(
                f"{_FRED_RELEASE_DATES_URL}?{urlencode(params)}",
                headers={"User-Agent": "hermes-escape-top/1.0 (research; read-only)"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            values = sorted(
                {
                    str(row.get("date") or "")[:10]
                    for row in payload.get("release_dates") or []
                    if str(row.get("release_id") or release_id) == release_id
                    and _iso_date(str(row.get("date") or "")) is not None
                }
            )
            if not values:
                raise ValueError(f"FRED release {release_id} returned no dated calendar rows")
            dates_by_id[release_id] = values
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "release_dates_by_id": {},
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    return {"status": "VERIFIED", "release_dates_by_id": dates_by_id}


@dataclass(frozen=True)
class FredPercentileAdapter:
    series_id: str
    field: str
    window: int = 252
    min_periods: int = 60
    start: str = "1990-01-01"
    end: str | None = None
    config: dict[str, Any] | None = None
    fetch_frame: FetchFredFrame = fetch_fred_series_frame
    publisher_release_ids: tuple[str, ...] = ()
    fetch_release_calendar: FetchReleaseCalendar = fetch_fred_release_calendar

    def fetch_raw(self) -> dict[str, Any]:
        frame = self.fetch_frame(
            self.series_id,
            start=self.start,
            end=self.end,
            config=self.config,
        )
        if frame is None or frame.empty:
            raw = {
                "metadata": _fred_metadata(self.series_id),
                "rows": [],
                "source_url": _FRED_API_URL,
                "provenance": source_provenance("fred_api"),
            }
            raw["publisher_evidence"] = _fred_publisher_evidence(
                self.publisher_release_ids,
                self.fetch_release_calendar(self.publisher_release_ids, self.config),
                raw["rows"],
            )
            return raw
        out = frame.copy()
        for column in ("date", "publish_date"):
            if column in out.columns:
                out[column] = pd.to_datetime(out[column], errors="coerce").dt.date.astype(str)
        metadata = _fred_metadata(self.series_id)
        metadata.update(dict(frame.attrs.get("fred_metadata") or {}))
        raw = {
            "metadata": metadata,
            "rows": out.to_dict("records"),
            "source_url": metadata.get("source_url") or _FRED_API_URL,
            "provenance": source_provenance("fred_api"),
        }
        raw["publisher_evidence"] = _fred_publisher_evidence(
            self.publisher_release_ids,
            self.fetch_release_calendar(self.publisher_release_ids, self.config),
            raw["rows"],
        )
        return raw

    def parse(self, raw: dict[str, Any] | list[dict[str, Any]]) -> pd.DataFrame:
        rows = raw.get("rows") if isinstance(raw, dict) else raw
        frame = pd.DataFrame(rows or [])
        if frame.empty:
            return pd.DataFrame(columns=["date", "publish_date", self.field, f"{self.field}_pctl"])
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["publish_date"] = pd.to_datetime(frame["publish_date"], errors="coerce")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = frame.dropna(subset=["date", "publish_date", "value"]).sort_values("date")
        frame = frame.set_index("date")[["value", "publish_date"]]
        frame[f"{self.field}_pctl"] = (
            frame["value"].rolling(self.window, min_periods=self.min_periods).apply(_last_percentile, raw=False)
        )
        out = frame.reset_index().rename(columns={"value": self.field})
        return out[["date", "publish_date", self.field, f"{self.field}_pctl"]]


def fred_percentile_spec(
    *,
    source_id: str,
    target_path: Path,
    field: str,
    semantic_validator: Callable[[pd.DataFrame], str | None] | None = None,
) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id=source_id,
        target_path=target_path,
        required_columns=("date", "publish_date", field, f"{field}_pctl"),
        semantic_validator=semantic_validator,
        pit_rule="observation_date_plus_one_day",
        source_url=_FRED_API_URL,
    )


@dataclass(frozen=True)
class FredBoardH10PercentileAdapter(FredPercentileAdapter):
    seed_path: Path | None = None
    witness_url: str = "https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm"
    fetch_text: FetchText = lambda url: _fetch_text(url)

    def fetch_raw(self) -> dict[str, Any]:
        raw = super().fetch_raw()
        witness = parse_federal_reserve_h10_broad(self.fetch_text(self.witness_url))
        raw.update(
            {
                "source": "fred_api_with_fed_board_h10_witness",
                "provenance": source_provenance(
                    "fred_api_with_fed_board_h10_witness"
                ),
                "witness_source_url": self.witness_url,
                "board_h10_witness": witness,
            }
        )
        return raw

    def parse(self, raw: dict[str, Any] | list[dict[str, Any]]) -> pd.DataFrame:
        frame = super().parse(raw)
        if isinstance(raw, dict):
            frame.attrs["board_h10_witness"] = dict(raw.get("board_h10_witness") or {})
        if self.seed_path is not None:
            frame = _reconcile_federal_reserve_h10_history(
                self.seed_path,
                frame,
                window=self.window,
                min_periods=self.min_periods,
            )
        return frame


def parse_federal_reserve_h10_broad(html: str) -> dict[str, Any]:
    parser = _H10TableParser()
    parser.feed(html or "")
    release_match = re.search(
        r"Release Date:\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s*"
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        parser.text,
        flags=re.IGNORECASE,
    )
    if release_match is None:
        raise ValueError("Federal Reserve H.10 release date not found")
    release_date = datetime.strptime(release_match.group(1), "%B %d, %Y").date().isoformat()
    rows: list[dict[str, Any]] = []
    for raw_date, raw_value in parser.rows:
        try:
            day = datetime.strptime(raw_date.strip(), "%d-%b-%y").date().isoformat()
            value = float(raw_value.strip())
        except ValueError:
            continue
        rows.append({"date": day, "value": value})
    rows.sort(key=lambda row: str(row["date"]))
    if not rows:
        raise ValueError("Federal Reserve H.10 broad dollar rows not found")
    return {"release_date": release_date, "rows": rows}


def validate_federal_reserve_h10_witness(frame: pd.DataFrame) -> str | None:
    revision = frame.attrs.get("history_revision")
    if isinstance(revision, dict) and revision.get("status") == "BLOCKED":
        reason = str(revision.get("reason") or "").strip()
        if reason:
            return reason
    quarantined_dates = {
        str(value)
        for value in (
            revision.get("changed_dates")
            if isinstance(revision, dict)
            else []
        )
    }
    witness = dict(frame.attrs.get("board_h10_witness") or {})
    rows = pd.DataFrame(witness.get("rows") or [])
    if rows.empty or not {"date", "value"}.issubset(rows.columns):
        return "Federal Reserve H.10 witness unavailable"
    primary = frame[["date", "dollar_broad"]].copy()
    primary["date"] = pd.to_datetime(primary["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    primary["dollar_broad"] = pd.to_numeric(primary["dollar_broad"], errors="coerce")
    rows["date"] = pd.to_datetime(rows["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    primary = primary.dropna().drop_duplicates("date", keep="last")
    rows = rows.dropna().drop_duplicates("date", keep="last")
    if primary.empty or rows.empty:
        return "Federal Reserve H.10 witness unavailable"
    primary_latest = str(primary.iloc[-1]["date"])
    witness_latest = str(rows.iloc[-1]["date"])
    if primary_latest != witness_latest:
        return (
            "Federal Reserve H.10 witness latest date mismatch: "
            f"FRED={primary_latest} H10={witness_latest}"
        )
    comparison = primary.tail(5).merge(rows, on="date", how="inner")
    if comparison.empty:
        return "Federal Reserve H.10 witness has no overlapping observations"
    for row in comparison.itertuples(index=False):
        if str(row.date) in quarantined_dates:
            continue
        if not _same_four_decimal_value(row.dollar_broad, row.value):
            return (
                f"Federal Reserve H.10 witness mismatch {row.date}: "
                f"FRED={float(row.dollar_broad):.4f} H10={float(row.value):.4f}"
            )
    return None


def _reconcile_federal_reserve_h10_history(
    target_path: Path,
    frame: pd.DataFrame,
    *,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    incoming = frame.copy()
    incoming.attrs = dict(frame.attrs)
    evidence: dict[str, Any] = {
        "schema_version": "hermes-dollar-history-revision-v1",
        "policy": "PRESERVE_CERTIFIED_FRED_APPEND_EXACT_H10_TAIL",
        "status": "NONE",
        "reason": None,
        "changed_dates": [],
        "changed_cells": [],
        "appended_dates": [],
        "canonical_rows_preserved": False,
    }
    if not target_path.exists():
        return _with_fred_revision_evidence(incoming, evidence)
    try:
        existing = pd.read_csv(target_path)
    except (OSError, pd.errors.ParserError) as exc:
        evidence.update(
            status="BLOCKED",
            reason=f"history continuity: existing Dollar canonical cannot be read: {exc}",
        )
        return _with_fred_revision_evidence(incoming, evidence)
    required = {"date", "dollar_broad"}
    if not required.issubset(existing.columns) or not required.issubset(incoming.columns):
        evidence.update(
            status="BLOCKED",
            reason="history continuity: Dollar canonical or incoming frame is missing date/dollar_broad",
        )
        return _with_fred_revision_evidence(incoming, evidence)

    existing = existing.copy()
    incoming = incoming.copy()
    incoming.attrs = dict(frame.attrs)
    existing["_day"] = pd.to_datetime(existing["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    incoming["_day"] = pd.to_datetime(incoming["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if existing["_day"].isna().any() or incoming["_day"].isna().any():
        evidence.update(
            status="BLOCKED",
            reason="history continuity: Dollar canonical or incoming frame has unparseable dates",
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
    if existing["_day"].duplicated().any() or incoming["_day"].duplicated().any():
        evidence.update(
            status="BLOCKED",
            reason="history continuity: Dollar canonical or incoming frame has duplicate dates",
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    existing_days = set(existing["_day"])
    incoming_days = set(incoming["_day"])
    missing = sorted(existing_days - incoming_days)
    if missing:
        evidence.update(
            status="BLOCKED",
            reason=f"history continuity: missing certified FRED dates ({', '.join(missing[:5])})",
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    latest_existing = max(existing_days)
    historical_additions = sorted(
        day for day in incoming_days - existing_days if day <= latest_existing
    )
    if historical_additions:
        evidence.update(
            status="BLOCKED",
            reason=(
                "history continuity: unreviewed historical FRED additions "
                f"({', '.join(historical_additions[:5])})"
            ),
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    common = existing[["_day", "dollar_broad"]].merge(
        incoming[["_day", "dollar_broad"]],
        on="_day",
        suffixes=("_canonical", "_incoming"),
    )
    canonical_values = pd.to_numeric(common["dollar_broad_canonical"], errors="coerce")
    incoming_values = pd.to_numeric(common["dollar_broad_incoming"], errors="coerce")
    primary_mismatch = canonical_values.isna() != incoming_values.isna()
    primary_mismatch |= (canonical_values - incoming_values).abs().fillna(0.0) > 1e-9
    primary_changes = common.loc[
        primary_mismatch,
        ["_day", "dollar_broad_canonical", "dollar_broad_incoming"],
    ]

    witness = pd.DataFrame(
        (incoming.attrs.get("board_h10_witness") or {}).get("rows") or []
    )
    if witness.empty or not {"date", "value"}.issubset(witness.columns):
        evidence.update(
            status="BLOCKED",
            reason="Federal Reserve H.10 witness unavailable",
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
    witness["_day"] = pd.to_datetime(witness["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    witness["value"] = pd.to_numeric(witness["value"], errors="coerce")
    witness = witness.dropna(subset=["_day", "value"]).drop_duplicates("_day", keep="last")
    if witness.empty:
        evidence.update(status="BLOCKED", reason="Federal Reserve H.10 witness unavailable")
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
    witness_by_day = witness.set_index("_day")["value"]

    witnessed_overlap = incoming[["_day", "dollar_broad"]].merge(
        witness[["_day", "value"]],
        on="_day",
        how="inner",
    )
    changed_cells: list[dict[str, Any]] = []
    for day, canonical_value, incoming_value in primary_changes.itertuples(
        index=False,
        name=None,
    ):
        day = str(day)
        witness_value = witness_by_day.get(day)
        revision_confirmed = witness_value is not None and _same_four_decimal_value(
            incoming_value,
            witness_value,
        )
        cell = {
            "date": day,
            "column": "dollar_broad",
            "canonical_fred": float(canonical_value),
            "incoming_fred": float(incoming_value),
            "board_h10": (
                float(witness_value) if witness_value is not None else None
            ),
            "revision_source": (
                "FRED_PRIMARY_CONFIRMED_BY_H10"
                if revision_confirmed
                else "FRED_PRIMARY_UNCONFIRMED"
            ),
        }
        changed_cells.append(cell)
        evidence["changed_cells"] = changed_cells
        evidence["changed_dates"] = sorted(
            {str(changed["date"]) for changed in changed_cells}
        )
        if day == latest_existing:
            evidence.update(
                status="BLOCKED",
                reason=f"history continuity: latest certified FRED row changed {day}",
            )
            return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
        if not revision_confirmed:
            evidence.update(
                status="BLOCKED",
                reason=f"FRED revision lacks exact H.10 confirmation {day}",
            )
            return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    for day, fred_value, witness_value in witnessed_overlap.itertuples(
        index=False,
        name=None,
    ):
        if _same_four_decimal_value(fred_value, witness_value):
            continue
        if str(day) < latest_existing:
            changed_cells.append(
                {
                    "date": str(day),
                    "column": "dollar_broad",
                    "certified_fred": float(fred_value),
                    "board_h10": float(witness_value),
                    "revision_source": "H10_WITNESS_ONLY",
                }
            )

    evidence["changed_cells"] = changed_cells
    evidence["changed_dates"] = sorted({str(cell["date"]) for cell in changed_cells})
    evidence["canonical_rows_preserved"] = True
    if changed_cells:
        evidence["status"] = "QUARANTINED"

    latest_incoming = max(incoming_days)
    latest_witness = str(witness["_day"].max())
    if latest_incoming != latest_witness:
        evidence.update(
            status="BLOCKED",
            reason=(
                "Federal Reserve H.10 witness latest date mismatch: "
                f"FRED={latest_incoming} H10={latest_witness}"
            ),
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    new_dates = sorted(incoming_days - existing_days)
    evidence["appended_dates"] = new_dates
    incoming_by_day = incoming.set_index("_day")
    for day in new_dates:
        if day not in witness_by_day:
            evidence.update(
                status="BLOCKED",
                reason=f"new tail witness missing {day}",
            )
            return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
        fred_value = float(incoming_by_day.loc[day, "dollar_broad"])
        witness_value = float(witness_by_day.loc[day])
        if not _same_four_decimal_value(fred_value, witness_value):
            evidence.update(
                status="BLOCKED",
                reason=(
                    f"new tail witness mismatch {day}: "
                    f"FRED={fred_value:.4f} H10={witness_value:.4f}"
                ),
            )
            return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    for day, fred_value, witness_value in witnessed_overlap.itertuples(
        index=False,
        name=None,
    ):
        if str(day) != latest_existing or _same_four_decimal_value(
            fred_value,
            witness_value,
        ):
            continue
        evidence.update(
            status="BLOCKED",
            reason=(
                f"latest certified witness mismatch {day}: "
                f"FRED={float(fred_value):.4f} H10={float(witness_value):.4f}"
            ),
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)

    columns = [column for column in frame.columns if column != "_day"]
    existing_rows = existing[[column for column in columns if column in existing.columns] + ["_day"]].copy()
    if set(columns) - set(existing_rows.columns):
        evidence.update(
            status="BLOCKED",
            reason="history continuity: Dollar canonical columns do not match incoming frame",
        )
        return _with_fred_revision_evidence(incoming.drop(columns="_day"), evidence)
    new_rows = incoming[~incoming["_day"].isin(existing_days)][columns + ["_day"]].copy()
    candidate = pd.concat([existing_rows, new_rows], ignore_index=True)
    candidate["date"] = candidate["_day"]
    candidate = candidate.drop(columns="_day").sort_values("date").reset_index(drop=True)
    percentile_column = "dollar_broad_pctl"
    if new_dates and percentile_column in candidate.columns:
        values = pd.to_numeric(candidate["dollar_broad"], errors="coerce")
        recomputed = values.rolling(window, min_periods=min_periods).apply(
            _last_percentile,
            raw=False,
        )
        new_mask = candidate["date"].isin(new_dates)
        candidate.loc[new_mask, percentile_column] = recomputed.loc[new_mask]
    candidate.attrs = dict(frame.attrs)
    return _with_fred_revision_evidence(candidate, evidence)


def _with_fred_revision_evidence(
    frame: pd.DataFrame,
    evidence: dict[str, Any],
) -> pd.DataFrame:
    stable = {
        "schema_version": evidence.get("schema_version"),
        "policy": evidence.get("policy"),
        "status": evidence.get("status"),
        "reason": evidence.get("reason"),
        "changed_dates": evidence.get("changed_dates"),
        "changed_cells": evidence.get("changed_cells"),
    }
    evidence["fingerprint"] = hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    frame.attrs["history_revision"] = evidence
    return frame


def _same_four_decimal_value(left: object, right: object) -> bool:
    quantum = Decimal("0.0001")
    try:
        return Decimal(str(left)).quantize(quantum) == Decimal(str(right)).quantize(quantum)
    except (InvalidOperation, ValueError):
        return False


class _H10TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.rows: list[tuple[str, str]] = []
        self._in_table = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "table" and "pubtables" in str(attrs_map.get("class") or "").split():
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._cells = []
        elif self._in_table and tag in {"th", "td"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.text_parts.append(value)
            if self._in_cell:
                self._cell_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if self._in_table and tag in {"th", "td"} and self._in_cell:
            self._cells.append(" ".join(self._cell_parts))
            self._in_cell = False
        elif self._in_table and tag == "tr":
            if len(self._cells) >= 2:
                self.rows.append((self._cells[0], self._cells[1]))
        elif tag == "table" and self._in_table:
            self._in_table = False


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hermes-escape-top/1.0 (research; read-only)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


@dataclass(frozen=True)
class FredNetLiquidityAdapter:
    start: str = "2015-01-01"
    end: str | None = None
    percentile_window: int = 252
    fetch_series: FetchFredSeries = fetch_fred_graph_csv
    fred_ids: dict[str, str] | None = None
    config: dict[str, Any] | None = None
    publisher_release_ids: tuple[str, ...] = ()
    fetch_release_calendar: FetchReleaseCalendar = fetch_fred_release_calendar

    def _ids(self) -> dict[str, str]:
        return dict(self.fred_ids or FredNetLiquiditySource.fred_ids)

    def fetch_raw(self) -> dict[str, Any]:
        raw: dict[str, list[dict[str, Any]]] = {}
        for name, series_id in self._ids().items():
            series = self.fetch_series(series_id, start=self.start, end=self.end)
            if series is None:
                raw[name] = []
                continue
            local = pd.Series(series).dropna().sort_index()
            rows = []
            for idx, value in local.items():
                rows.append({"date": pd.Timestamp(idx).date().isoformat(), "value": float(value)})
            raw[name] = rows
        payload = {
            "metadata": {
                "series_ids": self._ids(),
                "transport": "fredgraph_csv",
                "realtime_start": None,
                "realtime_end": None,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "pit_rule": "observation_date_plus_one_day",
            },
            "series": raw,
            "source_url": _FRED_GRAPH_URL,
            "provenance": source_provenance("fred_graph_csv"),
        }
        payload["publisher_evidence"] = _fred_publisher_evidence(
            self.publisher_release_ids,
            self.fetch_release_calendar(self.publisher_release_ids, self.config),
            raw,
        )
        return payload

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        series_rows = raw.get("series") if isinstance(raw.get("series"), dict) else raw
        series: dict[str, pd.Series] = {}
        for name in self._ids():
            frame = pd.DataFrame((series_rows or {}).get(name) or [])
            if frame.empty:
                series[name] = pd.Series(dtype="float64")
                continue
            dates = pd.to_datetime(frame["date"], errors="coerce")
            values = pd.to_numeric(frame["value"], errors="coerce")
            parsed = pd.Series(values.values, index=dates).dropna().sort_index()
            series[name] = parsed
        return fred_net_liquidity_frame(
            series["walcl"],
            series["wtregen"],
            series["rrp"],
            percentile_window=self.percentile_window,
        )


def fred_net_liquidity_spec(*, target_path: Path) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="fred_net_liquidity",
        target_path=target_path,
        required_columns=(
            "date",
            "publish_date",
            "walcl",
            "wtregen",
            "rrp",
            "net_liq",
            "net_liq_chg10",
            "net_liq_chg10_pctl",
        ),
        min_rows=60,
        pit_rule="observation_date_plus_one_day",
        source_url=_FRED_GRAPH_URL,
    )


_FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
_FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"


def _fred_publisher_evidence(
    release_ids: tuple[str, ...],
    calendar: dict[str, Any],
    content: Any,
) -> dict[str, Any]:
    ids = tuple(str(value) for value in release_ids if str(value).strip())
    dates_by_id = calendar.get("release_dates_by_id")
    if not isinstance(dates_by_id, dict):
        dates_by_id = {}
    normalized: dict[str, list[str]] = {}
    for release_id in ids:
        values = dates_by_id.get(release_id)
        if not isinstance(values, list):
            continue
        parsed = sorted(
            {
                day.isoformat()
                for value in values
                if (day := _iso_date(str(value))) is not None
            }
        )
        if parsed:
            normalized[release_id] = parsed
    verified = bool(ids) and set(normalized) == set(ids) and str(calendar.get("status")) == "VERIFIED"
    release_dates = sorted({day for values in normalized.values() for day in values})
    fingerprint_payload = {
        "release_dates_by_id": normalized,
        "content": content,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "calendar_status": "VERIFIED" if verified else "UNAVAILABLE",
        "release_id": f"FRED:{','.join(ids)}" if ids else None,
        "release_dates": release_dates if verified else [],
        "expected_release_dates": release_dates if verified else [],
        "content_fingerprint": fingerprint,
    }


def _iso_date(value: str):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _fred_metadata(series_id: str) -> dict[str, Any]:
    return {
        "series_id": series_id,
        "transport": "unknown",
        "realtime_start": None,
        "realtime_end": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "pit_rule": "observation_date_plus_one_day",
        "source_url": _FRED_API_URL,
    }
