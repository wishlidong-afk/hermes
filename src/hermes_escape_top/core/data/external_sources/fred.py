from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..macro import FredNetLiquiditySource, fetch_fred_graph_csv, fred_net_liquidity_frame
from ..risk_signals import _last_percentile, fetch_fred_series_frame
from .registry import ExternalSourceSpec


FetchFredFrame = Callable[..., pd.DataFrame]
FetchFredSeries = Callable[..., pd.Series]


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
) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id=source_id,
        target_path=target_path,
        required_columns=("date", "publish_date", field, f"{field}_pctl"),
        pit_rule="observation_date_plus_one_day",
        source_url=_FRED_API_URL,
    )


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
