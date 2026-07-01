from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..risk_signals import _last_percentile
from .registry import ExternalSourceSpec


AAII_SENT_RESULTS_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
FetchText = Callable[[str], str]

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_ROW_RE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
    r"([0-9]+(?:\.[0-9]+)?)%\s+([0-9]+(?:\.[0-9]+)?)%\s+([0-9]+(?:\.[0-9]+)?)%",
    re.IGNORECASE,
)
_COLUMNS = [
    "date",
    "publish_date",
    "aaii_bull",
    "aaii_bear",
    "aaii_bull_bear_spread",
    "aaii_bull_pctl",
    "aaii_spread_pctl",
]


def parse_aaii_public_rows(html: str, *, today: date | None = None) -> list[dict[str, Any]]:
    """Parse AAII's rendered recent-results table.

    The public page omits years in table rows, so years are inferred from the
    newest-first order and the current date.
    """
    now = today or date.today()
    text = unescape(re.sub(r"<[^>]+>", " ", html or ""))
    text = re.sub(r"\s+", " ", text).strip()
    year = now.year
    previous: date | None = None
    rows: list[dict[str, Any]] = []
    for match in _ROW_RE.finditer(text):
        month = _MONTHS[match.group(1).lower()[:3]]
        day = int(match.group(2))
        reported = date(year, month, day)
        if reported > now:
            year -= 1
            reported = date(year, month, day)
        if previous is not None and reported >= previous:
            year -= 1
            reported = date(year, month, day)
        previous = reported
        rows.append(
            {
                "reported": reported,
                "bull": round(float(match.group(3)) / 100.0, 3),
                "neutral": round(float(match.group(4)) / 100.0, 3),
                "bear": round(float(match.group(5)) / 100.0, 3),
            }
        )
    return rows


@dataclass(frozen=True)
class AaiiSentimentAdapter:
    seed_path: Path
    url: str = AAII_SENT_RESULTS_URL
    percentile_window: int = 156
    min_periods: int = 52
    today: date | None = None
    fetch_text: FetchText = lambda url: _fetch_text(url)

    def fetch_raw(self) -> dict[str, Any]:
        html = self.fetch_text(self.url)
        if _looks_blocked(html):
            raise ValueError("AAII public endpoint blocked; manual import required")
        if not html:
            raise ValueError("AAII public endpoint returned empty response")
        return {"url": self.url, "html": html}

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        rows = parse_aaii_public_rows(str((raw or {}).get("html") or ""), today=self.today)
        if not rows:
            raise ValueError("no AAII sentiment rows parsed; page structure changed or login wall")

        seed = _read_seed(Path(self.seed_path))
        new_rows = [_normalized_record(row) for row in rows if _valid_share_row(row)]
        if not new_rows:
            raise ValueError("AAII sentiment rows parsed but all values failed validation")

        out = pd.concat([seed, pd.DataFrame(new_rows)], ignore_index=True)
        out = _normalize_frame(out, self.percentile_window, self.min_periods)
        return out[_COLUMNS]


def aaii_sentiment_spec(*, target_path: Path, min_rows: int = 52) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="aaii_sentiment",
        target_path=target_path,
        required_columns=tuple(_COLUMNS),
        min_rows=min_rows,
    )


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8", errors="replace")


def _looks_blocked(html: str) -> bool:
    lower = (html or "").lower()
    return any(
        marker in lower
        for marker in (
            "pardon our interruption",
            "imperva",
            "incapsula",
            "reese84",
            "_incap_ses",
        )
    )


def _read_seed(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    return pd.read_csv(path)


def _valid_share_row(row: dict[str, Any]) -> bool:
    values = [float(row.get(field, float("nan"))) for field in ("bull", "neutral", "bear")]
    if any(value != value or not 0.0 <= value <= 1.0 for value in values):
        return False
    return 0.97 <= sum(values) <= 1.03


def _normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    publish_date = row["reported"] + timedelta(days=1)
    bull = round(float(row["bull"]), 3)
    bear = round(float(row["bear"]), 3)
    return {
        "date": publish_date,
        "publish_date": publish_date,
        "aaii_bull": bull,
        "aaii_bear": bear,
        "aaii_bull_bear_spread": round(bull - bear, 3),
    }


def _normalize_frame(frame: pd.DataFrame, window: int, min_periods: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_COLUMNS)
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["publish_date"] = pd.to_datetime(out["publish_date"], errors="coerce")
    for column in ("aaii_bull", "aaii_bear", "aaii_bull_bear_spread"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "publish_date", "aaii_bull", "aaii_bear", "aaii_bull_bear_spread"])
    out = out.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    out["aaii_bull_pctl"] = out["aaii_bull"].rolling(window, min_periods=min_periods).apply(_last_percentile, raw=False).round(2)
    out["aaii_spread_pctl"] = (
        out["aaii_bull_bear_spread"].rolling(window, min_periods=min_periods).apply(_last_percentile, raw=False).round(2)
    )
    out["date"] = out["date"].dt.date.astype(str)
    out["publish_date"] = out["publish_date"].dt.date.astype(str)
    return out
