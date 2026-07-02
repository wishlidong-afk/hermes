from __future__ import annotations

import base64
import hashlib
import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import pandas as pd

from ..risk_signals import _last_percentile
from .registry import ExternalSourceSpec


NAAIM_INDEX_URL = "https://www.naaim.org/programs/naaim-exposure-index/"
USER_AGENT = "hermes-escape-top/1.0 (research; read-only)"
_XLSX_HREF_RE = re.compile(r"""href=["']([^"']+\.xlsx?[^"']*)["']""", re.IGNORECASE)


FetchText = Callable[[str], str]
FetchBytes = Callable[[str], bytes]


def discover_naaim_xlsx_url(html: str, base_url: str = NAAIM_INDEX_URL) -> str | None:
    urls = [urljoin(base_url, unescape(match)) for match in _XLSX_HREF_RE.findall(html or "")]
    if not urls:
        return None
    for url in urls:
        normalized = url.lower().replace("_", "-")
        if "use-data" in normalized or "since-inception" in normalized:
            return url
    return urls[0]


@dataclass(frozen=True)
class NaaimExposureAdapter:
    index_url: str = NAAIM_INDEX_URL
    percentile_window: int = 252
    min_periods: int = 20
    fetch_text: FetchText = lambda url: _fetch_text(url)
    fetch_bytes: FetchBytes = lambda url: _fetch_bytes(url)

    def fetch_raw(self) -> dict[str, Any]:
        html = self.fetch_text(self.index_url)
        xlsx_url = discover_naaim_xlsx_url(html, self.index_url)
        if not xlsx_url:
            raise ValueError(
                "could not discover NAAIM xlsx URL; download the official workbook "
                "and run refresh_external --source naaim_exposure --import-file PATH"
            )
        xlsx = self.fetch_bytes(xlsx_url)
        if not xlsx:
            raise ValueError("downloaded empty NAAIM xlsx")
        return {
            "index_url": self.index_url,
            "xlsx_url": xlsx_url,
            "xlsx_base64": base64.b64encode(xlsx).decode("ascii"),
        }

    def parse(self, raw: dict[str, Any]) -> pd.DataFrame:
        xlsx = base64.b64decode(str((raw or {}).get("xlsx_base64") or ""))
        rows = _xlsx_rows(xlsx)
        records = _naaim_records(rows)
        return _records_frame(records, self.percentile_window, self.min_periods)


@dataclass(frozen=True)
class NaaimExposureImportAdapter:
    import_path: Path
    percentile_window: int = 252
    min_periods: int = 20

    def fetch_raw(self) -> dict[str, Any]:
        path = Path(self.import_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        content = path.read_bytes()
        if not content:
            raise ValueError(f"NAAIM import file is empty: {path}")
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
        file_name = str((raw or {}).get("file_name") or "naaim")
        rows = _naaim_import_rows(content, file_name)
        records = _naaim_records(rows)
        if not records:
            raise ValueError("NAAIM import file contained no usable exposure rows")
        return _records_frame(records, self.percentile_window, self.min_periods)


def naaim_exposure_spec(*, target_path: Path, min_rows: int = 60) -> ExternalSourceSpec:
    return ExternalSourceSpec(
        source_id="naaim_exposure",
        target_path=target_path,
        required_columns=("date", "publish_date", "naaim_exposure", "naaim_pctl", "is_proxy"),
        min_rows=min_rows,
    )


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def _xlsx_rows(raw: bytes) -> list[list[Any]]:
    try:
        import openpyxl  # type: ignore

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        return [list(row) for row in wb.active.iter_rows(values_only=True)]
    except ImportError:
        return _xlsx_rows_stdlib(raw)


def _naaim_import_rows(raw: bytes, file_name: str) -> list[list[Any]]:
    if file_name.lower().endswith((".csv", ".txt")):
        frame = pd.read_csv(io.BytesIO(raw))
        return [list(frame.columns)] + frame.astype(object).where(pd.notna(frame), None).values.tolist()
    return _xlsx_rows(raw)


def _records_frame(records: list[dict[str, Any]], percentile_window: int, min_periods: int) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["date", "publish_date", "naaim_exposure", "naaim_pctl", "is_proxy"])
    frame = pd.DataFrame(records).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    frame["publish_date"] = frame["date"].map(lambda value: value + timedelta(days=1))
    frame["naaim_pctl"] = (
        frame["naaim_exposure"]
        .rolling(percentile_window, min_periods=min_periods)
        .apply(_last_percentile, raw=False)
        .round(2)
    )
    frame["is_proxy"] = False
    frame["date"] = frame["date"].astype(str)
    frame["publish_date"] = frame["publish_date"].astype(str)
    return frame[["date", "publish_date", "naaim_exposure", "naaim_pctl", "is_proxy"]]


def _xlsx_rows_stdlib(raw: bytes) -> list[list[Any]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared = _shared_strings(zf, ns)
        sheet = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
    rows: list[list[Any]] = []
    for row in sheet.findall(".//m:sheetData/m:row", ns):
        values: list[Any] = []
        for cell in row.findall("m:c", ns):
            ref = cell.attrib.get("r", "")
            col = _xlsx_col_index(ref)
            while len(values) < col:
                values.append(None)
            values.append(_cell_value(cell, shared, ns))
        rows.append(values)
    return rows


def _shared_strings(zf: zipfile.ZipFile, ns: dict[str, str]) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for item in root.findall("m:si", ns):
        out.append("".join(node.text or "" for node in item.findall(".//m:t", ns)))
    return out


def _cell_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> Any:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", ns))
    value = cell.find("m:v", ns)
    if value is None or value.text is None:
        return None
    if cell_type == "s":
        idx = int(value.text)
        return shared[idx] if 0 <= idx < len(shared) else ""
    try:
        return float(value.text)
    except ValueError:
        return value.text


def _xlsx_col_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - 64)
    return max(idx - 1, 0)


def _naaim_records(rows: list[list[Any]]) -> list[dict[str, Any]]:
    header_idx = _header_index(rows)
    if header_idx is None:
        return []
    header = [str(value or "").strip().lower() for value in rows[header_idx]]
    date_col = next((idx for idx, value in enumerate(header) if "date" in value), 0)
    naaim_col = next(
        (idx for idx, value in enumerate(header) if "naaim number" in value),
        next((idx for idx, value in enumerate(header) if "naaim" in value), 1),
    )
    records = []
    for row in rows[header_idx + 1:]:
        if max(date_col, naaim_col) >= len(row):
            continue
        parsed_date = _parse_date(row[date_col])
        exposure = _parse_float(row[naaim_col])
        if parsed_date is None or exposure is None or not -200 <= exposure <= 200:
            continue
        records.append({"date": parsed_date, "naaim_exposure": round(exposure, 2)})
    return records


def _header_index(rows: list[list[Any]]) -> int | None:
    for idx, row in enumerate(rows[:20]):
        values = [str(value or "").strip().lower() for value in row]
        if any("date" in value for value in values) and any("naaim" in value for value in values):
            return idx
    return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, (int, float)) and 20_000 <= float(value) <= 80_000:
        return date(1899, 12, 30) + timedelta(days=int(float(value)))
    parsed = pd.to_datetime(str(value)[:10], errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _parse_float(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None
