#!/usr/bin/env python3
"""CFTC COT NQ futures backfill (A20 data source).

Downloads the CFTC Traders in Financial Futures (TFF) disaggregated report,
filters for Nasdaq-100 (NQ) futures, and computes:

  combined_net_oi_pct = (asset_mgr_net + levered_funds_net) / open_interest

where:
  asset_mgr_net    = Asset Manager Longs - Asset Manager Shorts
  levered_funds_net = Lev Money Longs - Lev Money Shorts

This ratio (net combined positioning as fraction of OI) is used by
CotPercentileSource → A20 factor in the scoring engine.

CFTC publishes weekly (Friday) with a 3-day lag (Tuesday snapshot).

Data source:
  Historical (2006-2016): https://www.cftc.gov/sites/default/files/files/dea/newcot/c_fut_fin_combined_historical_2006_2016.zip
  Per-year (2017+):       https://www.cftc.gov/sites/default/files/files/dea/newcot/fut_fin_xls_{year}.zip

Usage:
  python3 -m hermes_escape_top.scripts.backfill_cot [--dry-run]
  python3 -m hermes_escape_top.scripts.backfill_cot --start-year 2020
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import urllib.request
import urllib.error
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

HERMES_ROOT = Path(__file__).resolve().parents[1]
SOFT_HISTORY = HERMES_ROOT / "data" / "soft_history"
OUT_CSV = SOFT_HISTORY / "cot_nq.csv"

USER_AGENT = "hermes-escape-top/1.0 (research; read-only)"

# CFTC TFF report download URLs
_HIST_URL = "https://www.cftc.gov/sites/default/files/files/dea/newcot/c_fut_fin_combined_historical_2006_2016.zip"
_YEAR_URL = "https://www.cftc.gov/sites/default/files/files/dea/newcot/fut_fin_xls_{year}.zip"

# NQ contract name substrings (CFTC names vary slightly across years)
_NQ_NAMES = [
    "NASDAQ-100",
    "NASDAQ 100",
    "E-MINI NASDAQ",
    "NASDAQ STOCK",
]

# Expected columns in the TFF report (case-insensitive prefix match)
_COL_MAP = {
    "open_interest": ["open interest"],
    "asset_mgr_long": ["asset mgr longs", "asset mgr. longs", "asset manager longs"],
    "asset_mgr_short": ["asset mgr shorts", "asset mgr. shorts", "asset manager shorts"],
    "lev_long": ["lev money longs", "leveraged funds longs", "leveraged money longs"],
    "lev_short": ["lev money shorts", "leveraged funds shorts", "leveraged money shorts"],
    "date": ["report date as of in form yymmdd", "as_of_date_in_form_yymmdd", "report date"],
    "market": ["market and exchange names", "market_and_exchange_names"],
}


def _get(url: str, timeout: int = 60) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except Exception as exc:
        print(f"  [warn] GET {url[:80]}: {exc}")
        return None


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _parse_zip(content: bytes) -> Optional[pd.DataFrame]:
    """Extract and parse the XLS/CSV from a CFTC TFF zip."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            for name in names:
                if name.lower().endswith((".xls", ".xlsx")):
                    data = zf.read(name)
                    try:
                        df = pd.read_excel(io.BytesIO(data), engine="xlrd" if name.lower().endswith(".xls") else "openpyxl")
                    except Exception:
                        df = pd.read_excel(io.BytesIO(data))
                    return df
                if name.lower().endswith(".csv") or name.lower().endswith(".txt"):
                    data = zf.read(name)
                    df = pd.read_csv(io.BytesIO(data), low_memory=False)
                    return df
    except Exception as exc:
        print(f"  [warn] zip parse failed: {exc}")
    return None


def _extract_nq(df: pd.DataFrame) -> pd.DataFrame:
    """Filter a raw TFF dataframe to NQ rows and extract our columns."""
    market_col = _find_col(df, _COL_MAP["market"])
    if market_col is None:
        return pd.DataFrame()
    mask = df[market_col].astype(str).str.upper().apply(
        lambda x: any(n in x for n in _NQ_NAMES)
    )
    rows = df[mask].copy()
    if rows.empty:
        return rows

    date_col = _find_col(rows, _COL_MAP["date"])
    oi_col = _find_col(rows, _COL_MAP["open_interest"])
    aml_col = _find_col(rows, _COL_MAP["asset_mgr_long"])
    ams_col = _find_col(rows, _COL_MAP["asset_mgr_short"])
    lll_col = _find_col(rows, _COL_MAP["lev_long"])
    lls_col = _find_col(rows, _COL_MAP["lev_short"])

    for required, col in [("date", date_col), ("open_interest", oi_col),
                           ("asset_mgr_long", aml_col), ("asset_mgr_short", ams_col),
                           ("lev_long", lll_col), ("lev_short", lls_col)]:
        if col is None:
            print(f"  [warn] missing column for {required}")
            return pd.DataFrame()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(rows[date_col], errors="coerce", format="%y%m%d").fillna(
        pd.to_datetime(rows[date_col], errors="coerce")
    )
    out["open_interest"] = pd.to_numeric(rows[oi_col].astype(str).str.replace(",", ""), errors="coerce")
    out["asset_mgr_long"] = pd.to_numeric(rows[aml_col].astype(str).str.replace(",", ""), errors="coerce")
    out["asset_mgr_short"] = pd.to_numeric(rows[ams_col].astype(str).str.replace(",", ""), errors="coerce")
    out["lev_long"] = pd.to_numeric(rows[lll_col].astype(str).str.replace(",", ""), errors="coerce")
    out["lev_short"] = pd.to_numeric(rows[lls_col].astype(str).str.replace(",", ""), errors="coerce")
    return out.dropna(subset=["date", "open_interest"]).reset_index(drop=True)


def _compute(df: pd.DataFrame) -> pd.DataFrame:
    """Compute net positions and combined_net_oi_pct."""
    df = df.copy()
    df["asset_mgr_net"] = df["asset_mgr_long"] - df["asset_mgr_short"]
    df["levered_net"] = df["lev_long"] - df["lev_short"]
    df["combined_net"] = df["asset_mgr_net"] + df["levered_net"]
    df["combined_net_oi_pct"] = df["combined_net"] / df["open_interest"]
    df = df.dropna(subset=["combined_net_oi_pct"])
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "asset_mgr_net", "levered_net", "combined_net",
               "open_interest", "combined_net_oi_pct"]]


def _fetch_all(start_year: int = 2006) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    current_year = date.today().year

    if start_year <= 2016:
        print("  Fetching historical 2006-2016…")
        content = _get(_HIST_URL)
        if content:
            raw = _parse_zip(content)
            if raw is not None:
                nq = _extract_nq(raw)
                if not nq.empty:
                    frames.append(nq)
                    print(f"    historical: {len(nq)} NQ rows")
                else:
                    print("    [warn] no NQ rows in historical file")
            else:
                print("    [warn] could not parse historical zip")
        else:
            print("    [warn] could not fetch historical zip")

    for year in range(max(start_year, 2017), current_year + 1):
        url = _YEAR_URL.format(year=year)
        print(f"  Fetching {year}…")
        content = _get(url)
        if content is None:
            print(f"    [{year}] not found (may not be published yet)")
            continue
        raw = _parse_zip(content)
        if raw is None:
            print(f"    [{year}] could not parse zip")
            continue
        nq = _extract_nq(raw)
        if nq.empty:
            print(f"    [{year}] no NQ rows")
            continue
        frames.append(nq)
        print(f"    [{year}] {len(nq)} NQ rows")

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return combined


def run(dry_run: bool = False, start_year: int = 2006) -> Dict[str, Any]:
    print("CFTC COT NQ backfill starting…")
    raw = _fetch_all(start_year=start_year)
    if raw.empty:
        return {"error": "no NQ rows fetched from CFTC", "rows": 0}

    df = _compute(raw)
    rows = len(df)
    if rows == 0:
        return {"error": "computation produced no valid rows", "rows": 0}

    date_range = f"{df['date'].min().date()} → {df['date'].max().date()}"
    print(f"  Total rows: {rows}, date range: {date_range}")

    if dry_run:
        print("  [dry-run] not writing CSV")
        return {"rows": rows, "date_range": date_range, "dry_run": True}

    SOFT_HISTORY.mkdir(parents=True, exist_ok=True)
    if OUT_CSV.exists():
        shutil.copyfile(OUT_CSV, OUT_CSV.with_suffix(".csv.bak"))
    df.to_csv(OUT_CSV, index=False)
    print(f"  Written: {OUT_CSV}")
    return {"rows": rows, "date_range": date_range, "path": str(OUT_CSV)}


def main() -> int:
    parser = argparse.ArgumentParser(description="CFTC COT NQ futures backfill")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start-year", type=int, default=2006,
                        help="First year to fetch (default: 2006 = full history)")
    args = parser.parse_args()
    result = run(dry_run=args.dry_run, start_year=args.start_year)
    print(json.dumps(result, default=str, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
