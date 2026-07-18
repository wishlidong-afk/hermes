from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd


@dataclass(frozen=True)
class ExternalSourceSpec:
    source_id: str
    target_path: Path
    date_column: str = "date"
    required_columns: Sequence[str] = ("date",)
    min_rows: int = 1
    semantic_validator: Callable[[pd.DataFrame], str | None] | None = None
    pit_rule: str | None = None
    source_url: str | None = None
    allow_duplicate_dates: bool = False
    allow_validated_same_date_promotion: bool = False

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        object.__setattr__(self, "target_path", Path(self.target_path))
        if self.min_rows < 0:
            raise ValueError("min_rows must be non-negative")
        if self.allow_validated_same_date_promotion and self.semantic_validator is None:
            raise ValueError("same-date promotion requires a semantic validator")


def validate_normalized_frame(spec: ExternalSourceSpec, frame: pd.DataFrame) -> str | None:
    missing = [column for column in spec.required_columns if column not in frame.columns]
    if missing:
        return "missing required columns: " + ", ".join(missing)
    if len(frame) < spec.min_rows:
        return f"expected at least {spec.min_rows} rows, got {len(frame)}"
    if spec.date_column not in frame.columns:
        return f"missing date column: {spec.date_column}"
    dates = pd.to_datetime(frame[spec.date_column], errors="coerce")
    if dates.isna().any():
        return f"unparseable dates in {spec.date_column}"
    if not spec.allow_duplicate_dates and dates.duplicated().any():
        return f"duplicate dates in {spec.date_column}"
    if not dates.is_monotonic_increasing:
        return f"dates are not monotonic increasing in {spec.date_column}"
    if spec.semantic_validator is not None:
        try:
            return spec.semantic_validator(frame)
        except Exception as exc:
            return f"semantic validation failed: {exc}"
    return None


def latest_frame_date(spec: ExternalSourceSpec, frame: pd.DataFrame) -> str | None:
    if frame.empty or spec.date_column not in frame.columns:
        return None
    dates = pd.to_datetime(frame[spec.date_column], errors="coerce").dropna()
    if dates.empty:
        return None
    return dates.max().date().isoformat()
