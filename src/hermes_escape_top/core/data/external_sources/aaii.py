from __future__ import annotations

import base64
import hashlib
import io
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
            raise ValueError(
                "AAII public endpoint blocked; download the official sentiment.xls in a browser "
                "and run refresh_external --source aaii_sentiment --import-file PATH"
            )
        if not html:
            raise ValueError("AAII public endpoint returned empty response")
        return {
            "url": self.url,
            "source": "public_html",
            "file_name": "sent_results.html",
            "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "html": html,
        }

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


@dataclass(frozen=True)
class AaiiSentimentImportAdapter:
    seed_path: Path
    import_path: Path
    percentile_window: int = 156
    min_periods: int = 52

    def fetch_raw(self) -> dict[str, Any]:
        path = Path(self.import_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        content = path.read_bytes()
        if not content:
            raise ValueError(f"AAII import file is empty: {path}")
        return {
            "source": "manual_official_file",
            "file_name": path.name,
            "file_size": len(content),
            "file_mtime": path.stat().st_mtime,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "content_base64": base64.b64encode(content).decode("ascii"),
        }

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        content = base64.b64decode(str((raw or {}).get("content_base64") or ""))
        file_name = str((raw or {}).get("file_name") or "sentiment")
        imported = _parse_aaii_import_content(content, file_name)
        if imported.empty:
            raise ValueError("AAII import file contained no usable sentiment rows")
        seed = _read_seed(Path(self.seed_path))
        out = pd.concat([seed, imported], ignore_index=True)
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


def _parse_aaii_import_content(content: bytes, file_name: str) -> pd.DataFrame:
    raw = _read_aaii_import_table(content, file_name)
    date_col = _column(raw, "reported", "date")
    publish_col = _column(raw, "publishdate", "publish_date")
    bull_col = _column(raw, "aaiibull", "bullish", "bull", "percentbullish", "unnamed1")
    bear_col = _column(raw, "aaiibear", "bearish", "bear", "percentbearish", "unnamed3")
    spread_col = _column(raw, "aaiibullbearspread", "bullbear", "bullbearspread", "spread")
    if date_col is None or bull_col is None or bear_col is None:
        raise ValueError("AAII import file missing required columns: Reported/Bullish/Bearish")

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw[date_col], errors="coerce", format="mixed")
    if publish_col is not None:
        out["publish_date"] = pd.to_datetime(raw[publish_col], errors="coerce", format="mixed")
    else:
        out["publish_date"] = out["date"]
    out["aaii_bull"] = raw[bull_col].map(_share_value)
    out["aaii_bear"] = raw[bear_col].map(_share_value)
    if spread_col is not None:
        out["aaii_bull_bear_spread"] = raw[spread_col].map(_share_value)
    else:
        out["aaii_bull_bear_spread"] = out["aaii_bull"] - out["aaii_bear"]
    out = out.dropna(subset=["date", "publish_date", "aaii_bull", "aaii_bear", "aaii_bull_bear_spread"])
    out = out[
        out["aaii_bull"].between(0.0, 1.0)
        & out["aaii_bear"].between(0.0, 1.0)
        & out["aaii_bull_bear_spread"].between(-1.0, 1.0)
    ]
    if out.empty:
        return pd.DataFrame(columns=_COLUMNS)
    out["date"] = out["date"].dt.date.astype(str)
    out["publish_date"] = out["publish_date"].dt.date.astype(str)
    return out[["date", "publish_date", "aaii_bull", "aaii_bear", "aaii_bull_bear_spread"]]


def _read_aaii_import_table(content: bytes, file_name: str) -> pd.DataFrame:
    lower = file_name.lower()
    if lower.endswith((".csv", ".txt")):
        return pd.read_csv(io.BytesIO(content))
    try:
        return pd.read_excel(io.BytesIO(content), sheet_name="SENTIMENT", header=2)
    except Exception as exc:
        raise ValueError(
            "AAII import could not be read as Excel; install an Excel engine in the runtime "
            "or save the official AAII sentiment sheet as CSV and rerun --import-file"
        ) from exc


def _column(frame: pd.DataFrame, *aliases: str) -> str | None:
    wanted = {_column_key(alias) for alias in aliases}
    for column in frame.columns:
        if _column_key(str(column)) in wanted:
            return str(column)
    return None


def _column_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _share_value(value: Any) -> float | None:
    parsed = _float_value(value)
    if parsed is None:
        return None
    if abs(parsed) > 2.0:
        parsed = parsed / 100.0
    return round(parsed, 6)


def _float_value(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


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
