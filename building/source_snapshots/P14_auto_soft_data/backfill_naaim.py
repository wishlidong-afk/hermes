"""Automatic NAAIM Exposure Index backfill (N1-T05).

Fetches the weekly NAAIM Exposure Index directly from naaim.org's public xlsx.
The URL is date-stamped; we scrape the page to find the latest link.

History: weekly since 2006-07. Replaces the QQQ-derived proxy with real survey data.
Real data quality_penalty = 0 (direct from source, published weekly Wednesday).

Usage:
  python3 -m hermes_escape_top.scripts.backfill_naaim [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import json
import re
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

HERMES_ROOT = Path(__file__).resolve().parents[1]
SOFT_HISTORY = HERMES_ROOT / "data" / "soft_history"
OUT_CSV = SOFT_HISTORY / "naaim_exposure.csv"

NAAIM_INDEX_URL = "https://www.naaim.org/programs/naaim-exposure-index/"
USER_AGENT = "hermes-escape-top/1.0 (research; read-only)"

# Fallback direct URL pattern (date in URL — discover dynamically)
_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?naaim\.org/wp-content/uploads/[^"\']+\.xlsx?',
    re.IGNORECASE,
)


def _get(url: str, timeout: int = 20) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as exc:
        print(f"  [warn] {url[:80]}: {exc}")
        return None


def _discover_xlsx_url() -> Optional[str]:
    """Scrape NAAIM index page to find the current xlsx download URL."""
    html = _get(NAAIM_INDEX_URL)
    if html is None:
        return None
    text = html.decode("utf-8", errors="replace")
    matches = _URL_PATTERN.findall(text)
    if not matches:
        return None
    # Prefer 'USE_Data' (since-inception) over smaller files
    for m in matches:
        if "USE_Data" in m or "since-Inception" in m.replace(" ", "-"):
            return m
    return matches[0]


def _parse_xlsx(raw: bytes) -> pd.DataFrame:
    """Parse NAAIM xlsx → normalised weekly DataFrame."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except ImportError:
        # Fallback: pandas xlrd/openpyxl
        df_raw = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        rows = [tuple(df_raw.columns)] + [tuple(r) for r in df_raw.itertuples(index=False, name=None)]

    if not rows:
        return pd.DataFrame()

    # Find column indices
    header = [str(c).strip().lower() if c else "" for c in rows[0]]
    date_col = next((i for i, h in enumerate(header) if "date" in h), 0)
    # "NAAIM Number" is the consensus exposure; Mean/Average is also acceptable
    naaim_col = next(
        (i for i, h in enumerate(header) if "naaim number" in h),
        next((i for i, h in enumerate(header) if "mean" in h or "average" in h), 1),
    )

    records = []
    for row in rows[1:]:
        try:
            dt = row[date_col]
            if dt is None:
                continue
            if hasattr(dt, "date"):
                d = dt.date()
            else:
                d = date.fromisoformat(str(dt)[:10])
            val = float(row[naaim_col]) if row[naaim_col] is not None else None
            if val is not None and -200 <= val <= 200:
                records.append({"date": d, "naaim_exposure": round(val, 2)})
        except (ValueError, TypeError):
            continue

    df = pd.DataFrame(records).drop_duplicates("date").sort_values("date").reset_index(drop=True)
    return df


def _add_pit_and_percentile(df: pd.DataFrame) -> pd.DataFrame:
    """Add publish_date (Wednesday survey → published Wednesday same day),
    rolling percentile, and is_proxy=False flag."""
    # NAAIM publishes same day as survey (Wednesday); PIT = same day
    df["publish_date"] = df["date"]
    df["naaim_pctl"] = (
        df["naaim_exposure"]
        .rolling(252, min_periods=20)
        .rank(pct=True)
        .mul(100)
        .round(2)
    )
    df["is_proxy"] = False
    return df[["date", "publish_date", "naaim_exposure", "naaim_pctl", "is_proxy"]]


def run(dry_run: bool = False) -> Dict[str, Any]:
    SOFT_HISTORY.mkdir(parents=True, exist_ok=True)

    print("Discovering NAAIM xlsx URL from naaim.org ...")
    xlsx_url = _discover_xlsx_url()
    if xlsx_url is None:
        return {"error": "could not discover xlsx URL from naaim.org", "rows": 0}
    print(f"  Found: {xlsx_url}")

    print("Downloading xlsx ...")
    raw = _get(xlsx_url, timeout=30)
    if raw is None:
        return {"error": "download failed", "url": xlsx_url, "rows": 0}
    print(f"  Downloaded {len(raw):,} bytes")

    print("Parsing ...")
    df = _parse_xlsx(raw)
    if df.empty:
        return {"error": "parsed empty DataFrame", "url": xlsx_url, "rows": 0}
    print(f"  Parsed {len(df)} rows, date range: {df.date.min()} → {df.date.max()}")

    if dry_run:
        return {
            "dry_run": True, "rows": len(df),
            "date_range": [str(df.date.min()), str(df.date.max())],
            "url": xlsx_url,
        }

    df = _add_pit_and_percentile(df)
    df["date"] = df["date"].astype(str)
    df["publish_date"] = df["publish_date"].astype(str)
    df.to_csv(OUT_CSV, index=False)

    return {
        "out_csv": str(OUT_CSV),
        "rows": len(df),
        "date_range": [str(df.date.min()), str(df.date.max())],
        "url": xlsx_url,
        "is_proxy": False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    result = run(dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
