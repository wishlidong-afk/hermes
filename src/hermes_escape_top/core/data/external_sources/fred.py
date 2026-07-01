from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..risk_signals import _last_percentile, fetch_fred_series_frame
from .registry import ExternalSourceSpec


FetchFredFrame = Callable[..., pd.DataFrame]


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

    def fetch_raw(self) -> list[dict[str, Any]]:
        frame = self.fetch_frame(
            self.series_id,
            start=self.start,
            end=self.end,
            config=self.config,
        )
        if frame is None or frame.empty:
            return []
        out = frame.copy()
        for column in ("date", "publish_date"):
            if column in out.columns:
                out[column] = pd.to_datetime(out[column], errors="coerce").dt.date.astype(str)
        return out.to_dict("records")

    def parse(self, raw: list[dict[str, Any]]) -> pd.DataFrame:
        frame = pd.DataFrame(raw)
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
    )
