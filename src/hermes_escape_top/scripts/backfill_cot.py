#!/usr/bin/env python3
"""CFTC COT NQ futures backfill (A20 data source).

Downloads the CFTC Traders in Financial Futures (TFF) disaggregated report
via the CFTC public reporting Socrata API, filters for Nasdaq-100 (NQ)
futures, and computes:

  combined_net_oi_pct = (asset_mgr_net + levered_funds_net) / open_interest

where:
  asset_mgr_net     = Asset Manager Longs - Asset Manager Shorts
  levered_funds_net = Lev Money Longs - Lev Money Shorts

This ratio (net combined positioning as fraction of OI) is used by
CotPercentileSource → A20 factor in the scoring engine.

CFTC publishes weekly (Friday) with a 3-day lag (Tuesday snapshot).

Data source:
  CFTC public reporting Socrata API (TFF disaggregated):
  https://publicreporting.cftc.gov/resource/gpe5-46if.json
  (SSL verification bypassed — macOS Python doesn't include CFTC root CA)

Usage:
  python3 -m hermes_escape_top.scripts.backfill_cot [--dry-run]
  python3 -m hermes_escape_top.scripts.backfill_cot --start-year 2020
"""
from __future__ import annotations

import argparse
import json
import shutil
import ssl
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

HERMES_ROOT = Path(__file__).resolve().parents[1]
SOFT_HISTORY = HERMES_ROOT / "data" / "soft_history"
OUT_CSV = SOFT_HISTORY / "cot_nq.csv"

USER_AGENT = "hermes-escape-top/1.0 (research; read-only)"

_API_BASE = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
_API_LIMIT = 50000  # Socrata max rows per request; NQ history ~1000 rows total


def _ssl_ctx() -> ssl.SSLContext:
    """Create an SSL context that skips cert verification.

    CFTC's TLS chain uses a US Government root CA not bundled with Python's
    certifi on macOS.  The endpoint itself is a US government domain so
    downgrading verification is acceptable here.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get_json(url: str, timeout: int = 60) -> Optional[List[Dict]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"  [warn] HTTP {exc.code} for {url[:80]}")
        return None
    except Exception as exc:
        print(f"  [warn] GET {url[:80]}: {exc}")
        return None


def _fetch_all(start_year: int = 2006) -> pd.DataFrame:
    """Fetch all NQ TFF rows from the CFTC Socrata API since start_year."""
    start_iso = f"{start_year}-01-01T00:00:00.000"
    where = (
        f"market_and_exchange_names like '%NASDAQ%' "
        f"AND report_date_as_yyyy_mm_dd >= '{start_iso}'"
    )

    all_rows: List[Dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "$limit": _API_LIMIT,
            "$offset": offset,
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd ASC",
        })
        url = f"{_API_BASE}?{params}"
        print(f"  Fetching API offset={offset}…")
        batch = _get_json(url)
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < _API_LIMIT:
            break
        offset += _API_LIMIT

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    return _extract_nq_api(df)


def _extract_nq_api(df: pd.DataFrame) -> pd.DataFrame:
    """Map Socrata field names to our internal column names."""
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], errors="coerce")
    out["open_interest"] = pd.to_numeric(df["open_interest_all"], errors="coerce")
    out["asset_mgr_long"] = pd.to_numeric(df["asset_mgr_positions_long"], errors="coerce")
    out["asset_mgr_short"] = pd.to_numeric(df["asset_mgr_positions_short"], errors="coerce")
    out["lev_long"] = pd.to_numeric(df["lev_money_positions_long"], errors="coerce")
    out["lev_short"] = pd.to_numeric(df["lev_money_positions_short"], errors="coerce")
    out = out.dropna(subset=["date", "open_interest"]).reset_index(drop=True)
    # Multiple NQ contract codes can appear on the same Tuesday; keep the
    # row with the largest open interest (most representative).
    out = (out.sort_values(["date", "open_interest"], ascending=[True, False])
              .drop_duplicates(subset=["date"])
              .reset_index(drop=True))
    return out


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


def run(dry_run: bool = False, start_year: int = 2006) -> Dict[str, Any]:
    print("CFTC COT NQ backfill starting…")
    raw = _fetch_all(start_year=start_year)
    if raw.empty:
        return {"error": "no NQ rows fetched from CFTC API", "rows": 0}

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
