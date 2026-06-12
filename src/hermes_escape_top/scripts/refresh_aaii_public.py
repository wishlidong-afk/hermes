#!/usr/bin/env python3
"""Weekly AAII sentiment from the PUBLIC past-results page (no login).

aaii.com blocks the member XLS server-side, but sent_results renders the
recent weeks as plain HTML (Reported Date / Bullish / Neutral / Bearish).
Validations before any write: the three shares must sum to ~100%, each in
(0,100), and dates must extend the cache monotonically. Thursday convention:
csv date = reported date + 1 day (matches the existing series). Percentiles
recomputed with the parser's rolling(156, min 52) definition. Any failure
reports and keeps the cache; the member-session XLS path stays the fallback
for deep history.

Usage: python3 -m hermes_escape_top.scripts.refresh_aaii_public [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

URL = "https://www.aaii.com/sentimentsurvey/sent_results"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/126.0 Safari/537.36")}
OUT = Path(__file__).resolve().parents[1] / "data" / "soft_history" / "aaii_sentiment.csv"
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
ROW_RE = re.compile(
    r"<td[^>]*class=\"tableTxt\"[^>]*>([A-Z][a-z]{2}) (\d{1,2})</td>\s*"
    r"<td[^>]*>([0-9.]+)%\s*</td>\s*<td[^>]*>([0-9.]+)%</td>\s*<td[^>]*>([0-9.]+)%\s*</td>",
    re.S)


def fetch() -> str:
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rows(body: str, today: date | None = None) -> list[dict]:
    """Rows newest-first as rendered; infer year from 'today' rolling back."""
    today = today or date.today()
    out = []
    year = today.year
    prev: date | None = None
    for mon, day_s, bull, neutral, bear in ROW_RE.findall(body):
        reported = date(year, MONTHS[mon], int(day_s))
        if reported > today:                      # Dec rows seen in January
            year -= 1
            reported = date(year, MONTHS[mon], int(day_s))
        if prev is not None and reported >= prev:  # rolled past a year boundary
            year -= 1
            reported = date(year, MONTHS[mon], int(day_s))
        prev = reported
        out.append({"reported": reported, "bull": float(bull) / 100.0,
                    "neutral": float(neutral) / 100.0, "bear": float(bear) / 100.0})
    return out


def validate(row: dict) -> str | None:
    total = row["bull"] + row["neutral"] + row["bear"]
    if not 0.97 <= total <= 1.03:
        return f"shares sum {total:.3f} not ~1.0"
    for key in ("bull", "neutral", "bear"):
        if not 0.0 < row[key] < 1.0:
            return f"{key} {row[key]} out of range"
    return None


def append(rows: list[dict], dry_run: bool = False) -> int:
    frame = pd.read_csv(OUT, parse_dates=["date"])
    last = frame["date"].max().date()
    new = []
    for row in sorted(rows, key=lambda r: r["reported"]):
        csv_date = row["reported"] + timedelta(days=1)   # Thursday convention
        if csv_date <= last:
            continue
        reason = validate(row)
        if reason:
            print(f"{row['reported']} REJECTED: {reason}")
            continue
        new.append({"date": pd.Timestamp(csv_date), "publish_date": csv_date.isoformat(),
                    "aaii_bull": round(row["bull"], 3), "aaii_bear": round(row["bear"], 3),
                    "aaii_bull_bear_spread": round(row["bull"] - row["bear"], 3)})
    if not new:
        print(f"no new rows (cache through {last})")
        return 0
    frame = pd.concat([frame, pd.DataFrame(new)], ignore_index=True)
    frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    def _last_pctl(window: pd.Series) -> float:
        return float((window <= window.iloc[-1]).mean() * 100.0)

    frame["aaii_bull_pctl"] = frame["aaii_bull"].rolling(156, min_periods=52).apply(_last_pctl, raw=False)
    frame["aaii_spread_pctl"] = frame["aaii_bull_bear_spread"].rolling(156, min_periods=52).apply(_last_pctl, raw=False)
    if dry_run:
        print(f"DRY RUN — would append {len(new)} rows: {[str(r['date'].date()) for r in new]}")
        return 0
    frame.to_csv(OUT, index=False)
    for r in new:
        print(f"appended {r['date'].date()} bull={r['aaii_bull']} bear={r['aaii_bear']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        rows = parse_rows(fetch())
        if not rows:
            raise ValueError("no sentiment rows parsed — page structure changed or login wall")
    except Exception as exc:
        print(f"AAII PUBLIC PROBE FAILED (cache untouched): {exc!r}")
        print("fallback: member-session XLS via browser profile (see runbook)")
        return 1
    return append(rows, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
