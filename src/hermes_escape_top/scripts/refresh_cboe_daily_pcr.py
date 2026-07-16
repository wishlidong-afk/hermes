#!/usr/bin/env python3
"""Daily CBOE equity put/call ratio from the public daily-statistics page.

The CSV/S3 endpoints are bot-blocked, but the Next.js page embeds the day's
ratios and volumes as hydration JSON. We extract EQUITY PUT/CALL RATIO and
cross-validate it against EQUITY OPTIONS put/call volumes (the 2026-06-12
cross-wiring incident lesson: never append a number the source can't agree
with itself about). On any validation failure nothing is written — the run
reports and keeps the cache.

Continues the existing data/soft_history/cboe_equity_pcr.csv series (same
measure, new transport): source=CBOE_DAILY_HTML, is_proxy=false.

Usage: python3 -m hermes_escape_top.scripts.refresh_cboe_daily_pcr [--date YYYY-MM-DD] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

URL = "https://www.cboe.com/markets/us/options/market-statistics/daily/"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")}
OUT = Path(__file__).resolve().parents[1] / "data" / "soft_history" / "cboe_equity_pcr.csv"
CROSS_CHECK_TOL = 0.03   # |page ratio - put/call volumes| relative
RATIO_BOUNDS = (0.2, 2.0)
PCTL_WINDOW = 252


def fetch_page(target_date: str | None = None) -> str:
    url = URL + (f"?dt={target_date}" if target_date else "")
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_page(body: str) -> dict:
    """Extract selectedDate, the equity ratio, and equity option volumes."""
    flat = body.replace('\\"', '"')
    ratio_m = re.search(r'"EQUITY PUT/CALL RATIO","value":"([0-9.]+)"', flat)
    date_m = re.search(r'"selectedDate":"(202[0-9]-[01][0-9]-[0-3][0-9])"', flat)
    vol_m = re.search(r'"EQUITY OPTIONS":\[\{"name":"VOLUME","call":([0-9]+),"put":([0-9]+)', flat)
    if not (ratio_m and date_m and vol_m):
        raise ValueError("page structure changed: "
                         f"ratio={bool(ratio_m)} date={bool(date_m)} volumes={bool(vol_m)}")
    call_v, put_v = int(vol_m.group(1)), int(vol_m.group(2))
    return {"date": date_m.group(1), "ratio": float(ratio_m.group(1)),
            "call_volume": call_v, "put_volume": put_v}


def validate(rec: dict, existing_last_date: str | None) -> str | None:
    """Return a rejection reason, or None when the record is appendable."""
    lo, hi = RATIO_BOUNDS
    if not (lo <= rec["ratio"] <= hi):
        return f"ratio {rec['ratio']} outside bounds {RATIO_BOUNDS}"
    if rec["call_volume"] <= 0:
        return "zero call volume"
    implied = rec["put_volume"] / rec["call_volume"]
    if abs(implied - rec["ratio"]) / rec["ratio"] > CROSS_CHECK_TOL:
        return f"cross-check failed: page {rec['ratio']} vs volumes {implied:.4f}"
    if existing_last_date and rec["date"] <= existing_last_date:
        return f"date {rec['date']} not newer than cache {existing_last_date}"
    return None


def append(rec: dict, dry_run: bool = False) -> None:
    frame = pd.read_csv(OUT, parse_dates=["date"]) if OUT.exists() else \
        pd.DataFrame(columns=["date", "publish_date", "equity_pcr", "equity_pcr_pctl"])
    row = {"date": pd.Timestamp(rec["date"]), "publish_date": date.today().isoformat(),
           "equity_pcr": rec["ratio"], "source": "CBOE_DAILY_HTML", "is_proxy": False}
    frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    frame = _dedup_real_wins(frame)
    frame["equity_pcr_pctl"] = (
        frame["equity_pcr"].rolling(PCTL_WINDOW, min_periods=60)
        .apply(lambda w: float((w <= w.iloc[-1]).mean() * 100.0), raw=False)
    )
    if dry_run:
        print(f"DRY RUN — would append: {rec}")
        return
    _promote_frame(frame)
    print(f"appended {rec['date']} pcr={rec['ratio']} "
          f"(cross-check {rec['put_volume']}/{rec['call_volume']}) -> {OUT.name}")



def _dedup_real_wins(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per date, real (CBOE_DAILY_HTML) beating proxy.

    sort_values' default quicksort is NOT stable — sorting by date alone and
    keeping "last" picked proxy-vs-real arbitrarily (lost 248 of 498 fetched
    rows on the first 2024-2026 backfill). Rank realness explicitly instead.
    """
    src = frame["source"] if "source" in frame.columns else pd.Series("", index=frame.index)
    frame = frame.assign(_real=(src == "CBOE_DAILY_HTML").astype(int))
    frame = frame.sort_values(["date", "_real"], kind="stable")
    return frame.drop_duplicates(subset=["date"], keep="last").drop(columns=["_real"])


def backfill_range(start: str, end: str, sleep_s: float = 1.5) -> int:
    """Polite historical backfill: one process, one CSV write at the end.

    Replaces proxy rows date-by-date with real values (same validations per
    day except date-monotonicity, which doesn't apply when filling history).
    """
    import time
    days = pd.bdate_range(start, end)
    frame = pd.read_csv(OUT, parse_dates=["date"]) if OUT.exists() else pd.DataFrame(
        columns=["date", "publish_date", "equity_pcr", "equity_pcr_pctl"])
    have_real = set()
    if "source" in frame.columns:
        have_real = set(frame.loc[frame["source"] == "CBOE_DAILY_HTML", "date"].dt.strftime("%Y-%m-%d"))
    rows, fails = [], 0
    for day in days:
        d = day.strftime("%Y-%m-%d")
        if d in have_real:
            continue
        try:
            rec = parse_page(fetch_page(d))
        except Exception as exc:
            print(f"{d} FETCH FAIL: {exc!r}"); fails += 1
            time.sleep(sleep_s); continue
        reason = validate(rec, None)
        if reason:
            print(f"{d} REJECTED: {reason}"); fails += 1
        elif rec["date"] != d:
            print(f"{d} page returned {rec['date']} (holiday) — skip")
        else:
            rows.append({"date": pd.Timestamp(rec["date"]), "publish_date": date.today().isoformat(),
                         "equity_pcr": rec["ratio"], "source": "CBOE_DAILY_HTML", "is_proxy": False})
        time.sleep(sleep_s)
    if rows:
        frame = pd.concat([frame, pd.DataFrame(rows)], ignore_index=True)
        frame = _dedup_real_wins(frame)
        frame["equity_pcr_pctl"] = (
            frame["equity_pcr"].rolling(PCTL_WINDOW, min_periods=60)
            .apply(lambda w: float((w <= w.iloc[-1]).mean() * 100.0), raw=False)
        )
        _promote_frame(frame)
    print(f"backfill done: +{len(rows)} real rows, {fails} failures, total {len(frame)}")
    return 0 if fails < max(5, len(days) // 10) else 1


def _promote_frame(frame: pd.DataFrame) -> None:
    from hermes_escape_top.config import load_config, resolve_path
    from hermes_escape_top.core.data.external_sources import (
        PreparedFrameAdapter,
        cboe_pcr_spec,
        run_external_source_refresh,
    )

    config = load_config()
    target = resolve_path(config, "soft_history_dir") / "cboe_equity_pcr.csv"
    archive = resolve_path(config, "archive_dir")
    result = run_external_source_refresh(
        cboe_pcr_spec(target_path=target),
        PreparedFrameAdapter(frame, source_channel="legacy_cboe_history_backfill"),
        archive,
    )
    if result.status != "OK":
        raise RuntimeError(f"ExternalSourceRunner rejected CBOE PCR promotion: {result.error_message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="historical date (page ?dt=)")
    parser.add_argument("--backfill-start", default=None)
    parser.add_argument("--backfill-end", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.backfill_start and args.backfill_end:
        return backfill_range(args.backfill_start, args.backfill_end)
    try:
        rec = parse_page(fetch_page(args.date))
    except Exception as exc:
        print(f"REFRESH FAILED (cache untouched): {exc!r}")
        return 1
    last = None
    if OUT.exists():
        tail = pd.read_csv(OUT, usecols=["date"])
        if not tail.empty:
            last = str(tail["date"].max())[:10]
    reason = validate(rec, last)
    if reason:
        print(f"REJECTED (cache untouched): {reason}")
        return 1
    append(rec, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
