"""Backfill script for CBOE Equity PCR and NAAIM Exposure data (N1-T03, N1-T05).

Usage:
  python3 -m hermes_escape_top.scripts.backfill_pcr_naaim [--source cboe|manual] [--as-of YYYY-MM-DD]

Data sources:
  CBOE PCR: https://www.cboe.com/tradable_products/vix/vix_historical_data/ (manual download)
            or https://cdn.cboe.com/data/us/options/market_statistics/historical_data/
  NAAIM:    https://www.naaim.org/programs/naaim-exposure-index/ (manual download)

If auto-fetch fails, place raw CSV at the paths shown below and re-run with --source manual.
"""
from __future__ import annotations

import argparse
import ssl
import sys
from pathlib import Path

import pandas as pd

HERMES_ROOT = Path(__file__).resolve().parents[1]
SOFT_HISTORY = HERMES_ROOT / "data" / "soft_history"


def _ssl_ctx() -> ssl.SSLContext:
    """Create a verified SSL context, preferring certifi when installed."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


# ── CBOE Equity PCR ─────────────────────────────────────────────────────────

def backfill_pcr(raw_csv: Path | None = None) -> Path:
    """Parse CBOE equity PCR CSV and write normalised cache."""
    out = SOFT_HISTORY / "cboe_equity_pcr.csv"
    SOFT_HISTORY.mkdir(parents=True, exist_ok=True)

    if raw_csv and raw_csv.exists():
        frame = _parse_cboe_pcr_csv(raw_csv)
    else:
        frame = _try_fetch_cboe_pcr()

    if frame is None or frame.empty:
        if out.exists():
            print(f"PCR: no new data obtained. Keeping existing cache at {out}")
            return out
        print("PCR: no data obtained. Initialising empty skeleton.")
        frame = pd.DataFrame(columns=["date", "publish_date", "equity_pcr", "equity_pcr_pctl"])
    else:
        frame = _add_pctl(frame, "equity_pcr", "equity_pcr_pctl")

    frame.to_csv(out, index=False)
    print(f"PCR: wrote {len(frame)} rows to {out}")
    return out


def _parse_cboe_pcr_csv(path: Path) -> pd.DataFrame:
    """Parse CBOE-format CSV (Date, Call, Put, Total, ...) or simple (date,equity_pcr)."""
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
    # CBOE format has 'date' and either 'equity_only_put/call_ratio' or columns we map
    date_col = next((c for c in raw.columns if "date" in c), None)
    if date_col is None:
        raise ValueError(f"No date column in {path.name}")
    raw["date"] = pd.to_datetime(raw[date_col], errors="coerce")
    raw = raw.dropna(subset=["date"])

    # Try to find equity PCR column
    pcr_col = next(
        (c for c in raw.columns if "equity" in c and ("put" in c or "pcr" in c or "ratio" in c)),
        next((c for c in raw.columns if "put_call" in c or "p/c" in c or c in ("equity_pcr", "pcr")), None),
    )
    if pcr_col is None:
        raise ValueError(f"Cannot find equity PCR column in {path.name}. Columns: {list(raw.columns)}")
    raw["equity_pcr"] = pd.to_numeric(raw[pcr_col], errors="coerce")
    raw = raw.dropna(subset=["equity_pcr"]).sort_values("date")
    raw["publish_date"] = raw["date"]  # CBOE publishes same day
    return raw[["date", "publish_date", "equity_pcr"]].copy()


def _try_fetch_cboe_pcr() -> pd.DataFrame | None:
    import urllib.request, tempfile
    ctx = _ssl_ctx()
    urls = [
        "https://cdn.cboe.com/data/us/options/market_statistics/historical_data/options_eod_put_call_ratios.csv",
        "https://www.cboe.com/publish/scheduledtask/mktdata/datahouse/equitypc.csv",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
                content = r.read().decode("utf-8", errors="ignore")
            tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            tmp.write(content)
            tmp.flush()
            frame = _parse_cboe_pcr_csv(Path(tmp.name))
            print(f"PCR: fetched {len(frame)} rows from {url}")
            return frame
        except Exception as e:
            print(f"PCR fetch {url}: {e}")
    return None


# ── NAAIM Exposure ───────────────────────────────────────────────────────────

def backfill_naaim(raw_csv: Path | None = None) -> Path:
    """Parse NAAIM exposure CSV and write normalised cache."""
    out = SOFT_HISTORY / "naaim_exposure.csv"
    SOFT_HISTORY.mkdir(parents=True, exist_ok=True)

    if raw_csv and raw_csv.exists():
        frame = _parse_naaim_csv(raw_csv)
    else:
        frame = _try_fetch_naaim()

    if frame is None or frame.empty:
        print("NAAIM: no data obtained. Initialising empty skeleton.")
        frame = pd.DataFrame(columns=["date", "publish_date", "naaim_exposure", "naaim_pctl"])
    else:
        frame = _add_pctl(frame, "naaim_exposure", "naaim_pctl", window=156)

    frame.to_csv(out, index=False)
    print(f"NAAIM: wrote {len(frame)} rows to {out}")
    return out


def _parse_naaim_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
    date_col = next((c for c in raw.columns if "date" in c or "week" in c), None)
    if date_col is None:
        raise ValueError(f"No date column in {path.name}")
    raw["date"] = pd.to_datetime(raw[date_col], errors="coerce")
    raw = raw.dropna(subset=["date"])
    exp_col = next(
        (c for c in raw.columns if "exposure" in c or "naaim" in c and "exposure" in c),
        next((c for c in raw.columns if c not in {date_col, "date"}), None),
    )
    if exp_col is None:
        raise ValueError(f"Cannot find exposure column in {path.name}")
    raw["naaim_exposure"] = pd.to_numeric(raw[exp_col], errors="coerce")
    raw = raw.dropna(subset=["naaim_exposure"]).sort_values("date")
    # NAAIM publishes Wednesday; value available Thursday
    raw["publish_date"] = raw["date"] + pd.Timedelta(days=1)
    return raw[["date", "publish_date", "naaim_exposure"]].copy()


def _try_fetch_naaim() -> pd.DataFrame | None:
    import urllib.request, io
    ctx = _ssl_ctx()
    # Stooq provides NAAIM data but requires an API key obtained interactively.
    # Try the public NAAIM site with a different approach.
    urls = [
        "https://naaim.org/wp-content/uploads/NAAIM_Exposure_Index_Weekly_Data.csv",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
                buf = io.StringIO(r.read().decode("utf-8", errors="ignore"))
            frame = _parse_naaim_csv_from_buffer(buf)
            print(f"NAAIM: fetched {len(frame)} rows from {url}")
            return frame
        except Exception as e:
            print(f"NAAIM fetch {url}: {e}")
    return None


def _parse_naaim_csv_from_buffer(buf) -> pd.DataFrame:
    raw = pd.read_csv(buf)
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
    raw["date"] = pd.to_datetime(raw.iloc[:, 0], errors="coerce")
    raw = raw.dropna(subset=["date"])
    raw["naaim_exposure"] = pd.to_numeric(raw.iloc[:, 1], errors="coerce")
    raw = raw.dropna(subset=["naaim_exposure"]).sort_values("date")
    raw["publish_date"] = raw["date"] + pd.Timedelta(days=1)
    return raw[["date", "publish_date", "naaim_exposure"]]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _add_pctl(frame: pd.DataFrame, value_col: str, pctl_col: str, window: int = 252) -> pd.DataFrame:
    frame = frame.copy().sort_values("date").reset_index(drop=True)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["publish_date"] = pd.to_datetime(frame["publish_date"])

    def _last_pctl(s):
        if len(s) < 2:
            return None
        return float((s[:-1] <= s.iloc[-1]).mean() * 100)

    frame[pctl_col] = frame[value_col].rolling(window, min_periods=max(4, window // 10)).apply(_last_pctl, raw=False)
    frame["date"] = frame["date"].dt.strftime("%Y-%m-%d")
    frame["publish_date"] = frame["publish_date"].dt.strftime("%Y-%m-%d")
    return frame


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli():
    parser = argparse.ArgumentParser(description="Backfill CBOE PCR and NAAIM data")
    parser.add_argument("--pcr-raw", type=Path, help="Path to raw CBOE PCR CSV (optional)")
    parser.add_argument("--naaim-raw", type=Path, help="Path to raw NAAIM CSV (optional)")
    parser.add_argument("--skip-pcr", action="store_true")
    parser.add_argument("--skip-naaim", action="store_true")
    args = parser.parse_args()

    if not args.skip_pcr:
        backfill_pcr(args.pcr_raw)
    if not args.skip_naaim:
        backfill_naaim(args.naaim_raw)
    print("Done.")


if __name__ == "__main__":
    _cli()
