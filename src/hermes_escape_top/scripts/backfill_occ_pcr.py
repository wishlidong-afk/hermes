#!/usr/bin/env python3
"""Backfill weekly equity put/call ratios from OCC (T18).

CBOE's PCR endpoints are bot-blocked (403); OCC's weekly volume report is
open and covers ~2 years of history. Weekly granularity (week-ending
Friday), real cleared volume — replaces nothing by itself: accumulates
data/soft_history/occ_equity_pcr.csv for a future flag-gated source.

pcr_cust (customer accounts only) excludes market-maker hedging flow and is
the cleaner sentiment measure; pcr_total is the all-account ratio.

Usage:
  python3 -m hermes_escape_top.scripts.backfill_occ_pcr [--weeks 110] [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

URL = ("https://marketdata.theocc.com/weekly-volume-reports"
       "?reportDate={d}&reportType=options&reportClass=equity&format=csv")
OUT = Path(__file__).resolve().parents[1] / "data" / "soft_history" / "occ_equity_pcr.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
FIELDS = ["date", "calls_total", "puts_total", "pcr_total",
          "calls_cust", "puts_cust", "pcr_cust"]


def _num(text: str) -> int:
    return int(text.replace(",", "").strip() or 0)


def fetch_week(friday: date) -> dict | None:
    req = urllib.request.Request(URL.format(d=friday.strftime("%Y%m%d")), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if "TOTAL CALLS" not in body:
        return None
    section = None
    vals: dict[str, int] = {}
    for row in csv.reader(io.StringIO(body)):
        if not row:
            continue
        label = row[0].strip()
        if label in ("CALLS", "PUTS", "COMBINED"):
            section = label
        # The report repeats these labels in later sub-sections (e.g. FLEX);
        # only the FIRST occurrence (main Equity Options table) counts.
        elif label == "TOTAL CALLS":
            vals.setdefault("calls_total", _num(row[1]))
        elif label == "TOTAL PUTS":
            vals.setdefault("puts_total", _num(row[1]))
        elif label == "CUST (ALL)" and section in ("CALLS", "PUTS"):
            vals.setdefault(f"{'calls' if section == 'CALLS' else 'puts'}_cust", _num(row[1]))
    if "calls_total" not in vals or "puts_total" not in vals or not vals["calls_total"]:
        return None
    rec = {"date": friday.isoformat(), **vals}
    rec["pcr_total"] = round(vals["puts_total"] / vals["calls_total"], 4)
    if vals.get("calls_cust"):
        rec["pcr_cust"] = round(vals.get("puts_cust", 0) / vals["calls_cust"], 4)
    return rec


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--weeks", type=int, default=110)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    existing: dict[str, dict] = {}
    if OUT.exists():
        with OUT.open() as fh:
            existing = {r["date"]: r for r in csv.DictReader(fh)}

    today = date.today()
    friday = today - timedelta(days=(today.weekday() - 4) % 7)
    fetched = errors = 0
    for i in range(args.weeks):
        d = friday - timedelta(weeks=i)
        if d.isoformat() in existing:
            continue
        try:
            rec = fetch_week(d)
        except Exception as exc:
            print(f"{d} ERROR {exc!r}")
            errors += 1
            continue
        if rec:
            existing[rec["date"]] = {k: str(rec.get(k, "")) for k in FIELDS}
            fetched += 1
            print(f"{d} pcr_total={rec['pcr_total']} pcr_cust={rec.get('pcr_cust')}")
        else:
            print(f"{d} no data")
        time.sleep(0.4)

    if not args.dry_run and fetched:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for k in sorted(existing):
                w.writerow(existing[k])
    print(f"done: +{fetched} rows, {errors} errors, total {len(existing)} -> {OUT}")
    # The current week's report doesn't exist until Friday's close is
    # published; one failing week is normal, not an error condition.
    return 0 if errors <= max(1, args.weeks // 4) else 1


if __name__ == "__main__":
    sys.exit(main())
