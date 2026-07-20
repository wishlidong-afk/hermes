from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any, Callable
import urllib.request

import pandas as pd

from ..macro import FredNetLiquiditySource, fetch_fred_graph_csv, fred_net_liquidity_frame
from ..risk_signals import _last_percentile, fetch_fred_series_frame
from .registry import ExternalSourceSpec


FetchFredFrame = Callable[..., pd.DataFrame]
FetchFredSeries = Callable[..., pd.Series]
FetchText = Callable[[str], str]


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

    def fetch_raw(self) -> dict[str, Any]:
        frame = self.fetch_frame(
            self.series_id,
            start=self.start,
            end=self.end,
            config=self.config,
        )
        if frame is None or frame.empty:
            return {
                "metadata": _fred_metadata(self.series_id),
                "rows": [],
                "source_url": _FRED_API_URL,
            }
        out = frame.copy()
        for column in ("date", "publish_date"):
            if column in out.columns:
                out[column] = pd.to_datetime(out[column], errors="coerce").dt.date.astype(str)
        metadata = _fred_metadata(self.series_id)
        metadata.update(dict(frame.attrs.get("fred_metadata") or {}))
        return {
            "metadata": metadata,
            "rows": out.to_dict("records"),
            "source_url": metadata.get("source_url") or _FRED_API_URL,
        }

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
    witness_url: str = "https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm"
    fetch_text: FetchText = lambda url: _fetch_text(url)

    def fetch_raw(self) -> dict[str, Any]:
        raw = super().fetch_raw()
        witness = parse_federal_reserve_h10_broad(self.fetch_text(self.witness_url))
        raw.update(
            {
                "source": "fred_api_with_fed_board_h10_witness",
                "witness_source_url": self.witness_url,
                "board_h10_witness": witness,
            }
        )
        return raw

    def parse(self, raw: dict[str, Any] | list[dict[str, Any]]) -> pd.DataFrame:
        frame = super().parse(raw)
        if isinstance(raw, dict):
            frame.attrs["board_h10_witness"] = dict(raw.get("board_h10_witness") or {})
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
        if abs(float(row.dollar_broad) - float(row.value)) > 0.0001:
            return (
                f"Federal Reserve H.10 witness mismatch {row.date}: "
                f"FRED={float(row.dollar_broad):.4f} H10={float(row.value):.4f}"
            )
    return None


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
        return {
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
        }

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
