from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

import pandas as pd

from ..risk_signals import _last_percentile
from .clock import shanghai_today
from .registry import ExternalSourceSpec


AAII_SENT_RESULTS_URL = "https://www.aaii.com/sentimentsurvey/sent_results"
AAII_INSIGHTS_FEED_URL = "https://insights.aaii.com/feed"
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
    now = today or shanghai_today()
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


def parse_aaii_insights_feed(xml: str) -> list[dict[str, Any]]:
    """Parse AAII's own Insights RSS as an official automation fallback."""
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError:
        return []
    rows: list[dict[str, Any]] = []
    namespace = {"content": "http://purl.org/rss/1.0/modules/content/"}
    for item in root.findall("./channel/item"):
        title = str(item.findtext("title") or "")
        if "aaii sentiment survey" not in title.lower():
            continue
        published = _rss_date(item.findtext("pubDate"))
        body = item.findtext("content:encoded", default="", namespaces=namespace)
        if published is None or not body:
            continue
        text = unescape(re.sub(r"<[^>]+>", " ", body))
        text = re.sub(r"\s+", " ", text).strip()
        marker = re.search(r"this week(?:'|’)?s sentiment survey results\s*:", text, re.IGNORECASE)
        if marker is None:
            continue
        result_text = re.split(r"historical averages\s*:", text[marker.end():], maxsplit=1, flags=re.IGNORECASE)[0]
        bull = _labeled_percent(result_text, "bullish")
        neutral = _labeled_percent(result_text, "neutral")
        bear = _labeled_percent(result_text, "bearish")
        if any(value is None for value in (bull, neutral, bear)):
            continue
        reported = _previous_weekday(published, weekday=2)
        row = {
            "reported": reported,
            "publish_date": published,
            "bull": bull,
            "neutral": neutral,
            "bear": bear,
        }
        if _valid_share_row(row):
            rows.append(row)
    rows.sort(key=lambda row: row["reported"], reverse=True)
    return rows


@dataclass(frozen=True)
class AaiiSentimentAdapter:
    seed_path: Path
    url: str = AAII_SENT_RESULTS_URL
    feed_url: str = AAII_INSIGHTS_FEED_URL
    percentile_window: int = 156
    min_periods: int = 52
    today: date | None = None
    fetch_text: FetchText = lambda url: _fetch_text(url)

    def fetch_raw(self) -> dict[str, Any]:
        primary_failure = ""
        public_rows: list[dict[str, Any]] = []
        try:
            html = self.fetch_text(self.url)
        except Exception as exc:
            html = ""
            primary_failure = f"fetch_error:{exc.__class__.__name__}"
        if html and not _looks_blocked(html):
            public_rows = parse_aaii_public_rows(html, today=self.today)
        if any(_valid_share_row(row) for row in public_rows):
            return {
                "url": self.url,
                "source": "public_html",
                "file_name": "sent_results.html",
                "content_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                "html": html,
            }
        if not primary_failure:
            if _looks_blocked(html):
                primary_failure = "blocked"
            elif public_rows:
                primary_failure = "invalid_rows"
            else:
                primary_failure = "empty_or_unparseable"

        try:
            feed = self.fetch_text(self.feed_url)
        except Exception as exc:
            feed = ""
            feed_failure = f"fetch_error:{exc.__class__.__name__}"
            feed_rows: list[dict[str, Any]] = []
        else:
            feed_rows = parse_aaii_insights_feed(feed)
            feed_failure = "empty_or_unparseable" if not feed_rows else ""
        if not feed_failure:
            return {
                "url": self.feed_url,
                "source": "official_insights_rss",
                "file_name": "aaii_insights_feed.xml",
                "content_sha256": hashlib.sha256(feed.encode("utf-8")).hexdigest(),
                "primary_failure": primary_failure,
                "artifact_published_as_of": max(row["publish_date"] for row in feed_rows).isoformat(),
                "rss": feed,
            }
        raise ValueError(
            f"AAII public endpoint {primary_failure}; official Insights RSS {feed_failure}; "
            "download the official sentiment.xls in a browser and run "
            "refresh_external --source aaii_sentiment --import-file PATH"
        )

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        if str((raw or {}).get("source") or "") == "official_insights_rss":
            rows = parse_aaii_insights_feed(str((raw or {}).get("rss") or ""))
        else:
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
    content_bytes: bytes | None = None
    percentile_window: int = 156
    min_periods: int = 52

    def fetch_raw(self) -> dict[str, Any]:
        path = Path(self.import_path).expanduser()
        if self.content_bytes is None:
            if not path.exists():
                raise FileNotFoundError(str(path))
            content = path.read_bytes()
            file_mtime = path.stat().st_mtime
        else:
            content = bytes(self.content_bytes)
            file_mtime = None
        if not content:
            raise ValueError(f"AAII import file is empty: {path}")
        return {
            "source": "manual_official_file",
            "file_name": path.name,
            "file_size": len(content),
            "file_mtime": file_mtime,
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
        imported_latest = _latest_frame_date(imported)
        seed_latest = _latest_frame_date(seed)
        if imported_latest is not None and seed_latest is not None and imported_latest < seed_latest:
            raise ValueError(
                "AAII import file is older than current AAII seed: "
                f"import latest {imported_latest.isoformat()}, seed latest {seed_latest.isoformat()}"
            )
        out = pd.concat([seed, imported], ignore_index=True)
        out = _normalize_frame(out, self.percentile_window, self.min_periods)
        return out[_COLUMNS]


def aaii_sentiment_spec(*, target_path: Path, min_rows: int = 52) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="aaii_sentiment",
        target_path=target_path,
        required_columns=tuple(_COLUMNS),
        min_rows=min_rows,
        semantic_validator=_validate_aaii,
        pit_rule="official_publish_date_or_reported_plus_one_day",
        source_url=AAII_SENT_RESULTS_URL,
    )


def _validate_aaii(frame: pd.DataFrame) -> str | None:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    publish_dates = pd.to_datetime(frame["publish_date"], errors="coerce")
    if dates.isna().any() or publish_dates.isna().any() or not dates.equals(publish_dates):
        return "AAII date/publish_date must be parseable and equal"

    bull = pd.to_numeric(frame["aaii_bull"], errors="coerce")
    bear = pd.to_numeric(frame["aaii_bear"], errors="coerce")
    spread = pd.to_numeric(frame["aaii_bull_bear_spread"], errors="coerce")
    if bull.isna().any() or bear.isna().any():
        return "AAII bull/bear share contains non-numeric values"
    if not bull.between(0.0, 1.0).all() or not bear.between(0.0, 1.0).all():
        return "AAII bull/bear share outside [0, 1]"
    if spread.isna().any() or not spread.between(-1.0, 1.0).all():
        return "AAII spread outside [-1, 1]"
    if ((spread - (bull - bear)).abs() > 0.002).any():
        return "AAII spread is inconsistent with bull minus bear"

    for column in ("aaii_bull_pctl", "aaii_spread_pctl"):
        raw = frame[column]
        values = pd.to_numeric(raw, errors="coerce")
        if (raw.notna() & values.isna()).any():
            return f"AAII percentile contains non-numeric values: {column}"
        non_null = values.dropna()
        if not non_null.between(0.0, 100.0).all():
            return f"AAII percentile outside [0, 100]: {column}"
    return None


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


def _rss_date(value: str | None) -> date | None:
    try:
        return parsedate_to_datetime(str(value or "")).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _previous_weekday(day: date, *, weekday: int) -> date:
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _labeled_percent(text: str, label: str) -> float | None:
    match = re.search(rf"\b{re.escape(label)}\s*:\s*([0-9]+(?:\.[0-9]+)?)%", text, re.IGNORECASE)
    if match is None:
        return None
    return round(float(match.group(1)) / 100.0, 3)


def _read_seed(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=_COLUMNS)
    return pd.read_csv(path)


def _latest_frame_date(frame: pd.DataFrame, column: str = "date") -> date | None:
    if frame.empty or column not in frame:
        return None
    values = pd.to_datetime(frame[column], errors="coerce", format="mixed").dropna()
    if values.empty:
        return None
    return values.max().date()


def _valid_share_row(row: dict[str, Any]) -> bool:
    values = [float(row.get(field, float("nan"))) for field in ("bull", "neutral", "bear")]
    if any(value != value or not 0.0 <= value <= 1.0 for value in values):
        return False
    return 0.97 <= sum(values) <= 1.03


def _normalized_record(row: dict[str, Any]) -> dict[str, Any]:
    publish_date = row.get("publish_date") or (row["reported"] + timedelta(days=1))
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
    except Exception:
        try:
            return _read_aaii_xls_with_helper(content, file_name)
        except Exception as helper_exc:
            raise ValueError(
                "AAII import could not be read as Excel; install an Excel engine in the runtime "
                "or save the official AAII sentiment sheet as CSV and rerun --import-file"
            ) from helper_exc


def _read_aaii_xls_with_helper(content: bytes, file_name: str) -> pd.DataFrame:
    helper = os.environ.get("HERMES_AAII_XLS_HELPER_PYTHON") or "/usr/bin/python3"
    if Path(helper).resolve() == Path(sys.executable).resolve():
        raise RuntimeError("AAII XLS helper is the current interpreter without an Excel engine")
    safe_name = Path(file_name or "sentiment.xls").name
    code = (
        "import pandas as pd, sys\n"
        "frame = pd.read_excel(sys.argv[1], sheet_name='SENTIMENT', header=2)\n"
        "frame.to_csv(sys.stdout, index=False)\n"
    )
    with tempfile.TemporaryDirectory(prefix="hermes-aaii-xls-") as tmp:
        path = Path(tmp) / safe_name
        path.write_bytes(content)
        completed = subprocess.run(
            [helper, "-c", code, str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
    if not completed.stdout.strip():
        raise ValueError("AAII XLS helper returned empty CSV")
    return pd.read_csv(io.StringIO(completed.stdout))


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
