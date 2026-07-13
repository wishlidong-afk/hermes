"""Automatic BTC microstructure backfill — REAL funding / basis / DVOL (N1-T07/T08/T09).

ONLINE script (separate from offline daily scoring). Fetches real data from free,
publicly-accessible exchange APIs, writes versioned CSV that the offline
`CryptoFundingSource` adapter reads.

Data sources (failover, E30 pattern):
  - DVOL (BTC volatility index): Deribit  https://www.deribit.com/api/v2  (real since 2021-03)
  - Funding (8h perpetual):      Deribit BTC-PERPETUAL  →  OKX BTC-USD-SWAP (failover)
  - Basis (annualised):          derived from real funding (perp funding ≈ basis carry)

Geo note: Binance/Bybit are geo-blocked from this environment; Deribit + OKX work.

Idempotent: only fetches dates newer than the last cached real row.
Pre-2021 span keeps the momentum proxy (is_proxy=True); 2021+ uses real (is_proxy=False).

Usage:
  python3 -m hermes_escape_top.scripts.backfill_crypto_micro [--full] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HERMES_ROOT = Path(__file__).resolve().parents[1]
SOFT_HISTORY = HERMES_ROOT / "data" / "soft_history"
OUT_CSV = SOFT_HISTORY / "btc_funding_basis.csv"

DERIBIT = "https://www.deribit.com/api/v2/public"
OKX = "https://www.okx.com/api/v5/public"
DVOL_LAUNCH_MS = 1616544000000  # 2021-03-24, Deribit DVOL inception
USER_AGENT = "hermes-escape-top/1.0 (research; read-only)"


# ---------------------------------------------------------------------------
# HTTP helper (stdlib only, no requests dependency)
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        print(f"  [warn] fetch failed {url[:80]}...: {exc}")
        return None


# ---------------------------------------------------------------------------
# Deribit DVOL (BTC volatility index)
# ---------------------------------------------------------------------------

def fetch_deribit_dvol(start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch daily BTC DVOL. Deribit caps each call; paginate by ~6-month chunks."""
    rows: List[Tuple[int, float]] = []
    chunk = 180 * 86400 * 1000  # ~6 months
    cur = start_ms
    while cur < end_ms:
        chunk_end = min(cur + chunk, end_ms)
        url = (f"{DERIBIT}/get_volatility_index_data?currency=BTC"
               f"&start_timestamp={cur}&end_timestamp={chunk_end}&resolution=86400")
        data = _get_json(url)
        if data and data.get("result", {}).get("data"):
            for entry in data["result"]["data"]:
                # [timestamp, open, high, low, close]
                rows.append((int(entry[0]), float(entry[4])))
        cur = chunk_end
        time.sleep(0.2)  # be polite
    if not rows:
        return pd.DataFrame(columns=["date", "btc_dvol"])
    df = pd.DataFrame(rows, columns=["ts", "btc_dvol"]).drop_duplicates("ts")
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    return df[["date", "btc_dvol"]].sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Deribit funding (8h perpetual) + index price for basis
# ---------------------------------------------------------------------------

def fetch_deribit_funding(start_ms: int, end_ms: int) -> pd.DataFrame:
    """Fetch 8h funding + index price, aggregate to daily."""
    rows: List[Dict[str, Any]] = []
    chunk = 28 * 86400 * 1000  # ~28 days per call (hourly data, ~672 rows)
    cur = start_ms
    while cur < end_ms:
        chunk_end = min(cur + chunk, end_ms)
        url = (f"{DERIBIT}/get_funding_rate_history?instrument_name=BTC-PERPETUAL"
               f"&start_timestamp={cur}&end_timestamp={chunk_end}")
        data = _get_json(url)
        if data and isinstance(data.get("result"), list):
            for entry in data["result"]:
                rows.append({
                    "ts": int(entry["timestamp"]),
                    "interest_8h": float(entry.get("interest_8h", 0.0) or 0.0),
                    "index_price": float(entry.get("index_price", 0.0) or 0.0),
                })
        cur = chunk_end
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame(columns=["date", "btc_funding_8h_avg", "btc_index_price"])
    df = pd.DataFrame(rows).drop_duplicates("ts")
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    daily = df.groupby("date").agg(
        btc_funding_8h_avg=("interest_8h", "mean"),
        btc_index_price=("index_price", "last"),
    ).reset_index()
    return daily


def fetch_okx_funding_recent() -> pd.DataFrame:
    """Failover: OKX funding history (only ~3 months retained). Daily aggregate."""
    rows: List[Dict[str, Any]] = []
    url = f"{OKX}/funding-rate-history?instId=BTC-USD-SWAP&limit=100"
    data = _get_json(url)
    if data and data.get("data"):
        for entry in data["data"]:
            rows.append({
                "ts": int(entry["fundingTime"]),
                "funding": float(entry.get("realizedRate") or entry.get("fundingRate") or 0.0),
            })
    if not rows:
        return pd.DataFrame(columns=["date", "btc_funding_8h_avg", "btc_index_price"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
    daily = df.groupby("date").agg(btc_funding_8h_avg=("funding", "mean")).reset_index()
    daily["btc_index_price"] = np.nan
    return daily


# ---------------------------------------------------------------------------
# Merge real + proxy, compute percentiles
# ---------------------------------------------------------------------------

def build_unified(real_funding: pd.DataFrame, real_dvol: pd.DataFrame,
                  existing_proxy: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Merge real exchange data over the momentum proxy; per-row is_proxy flag."""
    # Start from existing proxy (2018+) if present
    if existing_proxy is not None and not existing_proxy.empty:
        base = existing_proxy.copy()
        base["date"] = pd.to_datetime(base["date"]).dt.normalize()
        if "is_proxy" not in base:
            base["is_proxy"] = True
        elif base["is_proxy"].dtype != bool:
            base["is_proxy"] = base["is_proxy"].map(
                lambda value: str(value).strip().lower() not in {"false", "0", "no"}
            )
    else:
        base = pd.DataFrame(columns=["date", "btc_funding_8h_avg", "btc_basis_annual"])
        base["is_proxy"] = True

    base = base.set_index("date")

    # Overlay real funding (2021+)
    if not real_funding.empty:
        rf = real_funding.set_index("date")
        for dt, row in rf.iterrows():
            base.loc[dt, "btc_funding_8h_avg"] = row["btc_funding_8h_avg"]
            # annualised basis from real funding: 3 sessions/day × 365
            base.loc[dt, "btc_basis_annual"] = round(row["btc_funding_8h_avg"] * 3 * 365, 6)
            base.loc[dt, "is_proxy"] = False

    # Overlay real DVOL
    if not real_dvol.empty:
        rd = real_dvol.set_index("date")
        for dt, row in rd.iterrows():
            base.loc[dt, "btc_dvol"] = row["btc_dvol"]

    base = base.sort_index().reset_index()

    # Recompute rolling percentiles on the unified series
    base["btc_funding_pctl"] = base["btc_funding_8h_avg"].rolling(252, min_periods=20).rank(pct=True).mul(100).round(2)
    base["btc_basis_pctl"] = base["btc_basis_annual"].rolling(252, min_periods=20).rank(pct=True).mul(100).round(2)
    if "btc_dvol" in base.columns:
        base["btc_dvol_pctl"] = base["btc_dvol"].rolling(252, min_periods=20).rank(pct=True).mul(100).round(2)

    base["publish_date"] = base["date"]
    base["btc_funding_8h_avg"] = base["btc_funding_8h_avg"].round(6)
    base["btc_basis_annual"] = base["btc_basis_annual"].round(4)

    cols = ["date", "publish_date", "btc_funding_8h_avg", "btc_funding_pctl",
            "btc_basis_annual", "btc_basis_pctl", "is_proxy"]
    if "btc_dvol" in base.columns:
        cols += ["btc_dvol", "btc_dvol_pctl"]
    return base[cols]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(full: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    SOFT_HISTORY.mkdir(parents=True, exist_ok=True)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    existing = None
    last_real_date = None
    if OUT_CSV.exists():
        existing = pd.read_csv(OUT_CSV, parse_dates=["date"])
        if "is_proxy" in existing.columns:
            real_rows = existing[existing["is_proxy"] == False]
            if not real_rows.empty:
                last_real_date = real_rows["date"].max()

    if full or last_real_date is None:
        start_ms = DVOL_LAUNCH_MS
    else:
        start_ms = int(last_real_date.timestamp() * 1000) + 86400000

    print(f"Fetching real BTC micro from {datetime.fromtimestamp(start_ms/1000, timezone.utc).date()} ...")

    # DVOL
    print("  → Deribit DVOL ...")
    dvol = fetch_deribit_dvol(max(start_ms, DVOL_LAUNCH_MS), now_ms)
    print(f"    DVOL rows: {len(dvol)}")

    # Funding (Deribit primary)
    print("  → Deribit funding ...")
    funding = fetch_deribit_funding(start_ms, now_ms)
    source = "deribit"
    if funding.empty:
        print("  → Deribit funding empty; failover to OKX ...")
        funding = fetch_okx_funding_recent()
        source = "okx_failover"
    print(f"    funding rows: {len(funding)} (source={source})")

    if dry_run:
        return {"dry_run": True, "dvol_rows": len(dvol), "funding_rows": len(funding), "source": source}

    unified = build_unified(funding, dvol, existing)
    unified["is_proxy"] = unified["is_proxy"].fillna(True).astype(bool)
    real_count = int((unified["is_proxy"] == False).sum())
    unified.to_csv(OUT_CSV, index=False)

    return {
        "out_csv": str(OUT_CSV),
        "total_rows": len(unified),
        "real_rows": real_count,
        "proxy_rows": len(unified) - real_count,
        "funding_source": source,
        "dvol_rows": len(dvol),
        "date_range": [str(unified["date"].min().date()), str(unified["date"].max().date())],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="refetch all real history from DVOL launch")
    ap.add_argument("--dry-run", action="store_true", help="fetch counts only, no write")
    args = ap.parse_args()
    result = run(full=args.full, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
