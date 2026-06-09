"""Backfill CNN Fear & Greed history into soft_history/cnn_fear_greed.csv.

Source: whit3rabbit/fear-greed-data canonical combined file (CNN era 2021-02+
regenerated from the live CNN endpoint; 2011..2021-01 frozen archive). Covers
2011-01-03 → present, so it backfills the full 2018+ backtest window.

    https://github.com/whit3rabbit/fear-greed-data  →  fear-greed.csv

Usage:
    PYTHONPATH=src python3 -m hermes_escape_top.scripts.backfill_cnn_fgi [SOURCE] [OUT]

SOURCE may be the raw URL (default) or a local path to fear-greed.csv.
Writes columns: date, publish_date, cnn_fear_greed, cnn_fear_greed_pctl, is_proxy.
The F&G index is a close-of-day reading, so publish_date == date (no look-ahead
for a close-of-day decision). Percentile is a trailing 252-day rank.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RAW_URL = "https://raw.githubusercontent.com/whit3rabbit/fear-greed-data/main/fear-greed.csv"
PCTL_WINDOW = 252
PCTL_MIN = 60
# Pre-2021-02 rows are reconstructed from third-party archives (not the live CNN
# endpoint) → flag as proxy for quality accounting.
LIVE_CNN_FROM = "2021-02-01"


def build(source: str, out: Path) -> Path:
    raw = pd.read_csv(source)
    # Normalise column names (Date, Fear Greed[, Rating]).
    cols = {c.lower().strip(): c for c in raw.columns}
    dcol = cols.get("date")
    vcol = cols.get("fear greed") or cols.get("fear_greed") or cols.get("value")
    if dcol is None or vcol is None:
        raise SystemExit(f"unexpected columns: {list(raw.columns)}")
    df = pd.DataFrame({
        "date": pd.to_datetime(raw[dcol], errors="coerce"),
        "cnn_fear_greed": pd.to_numeric(raw[vcol], errors="coerce"),
    }).dropna(subset=["date", "cnn_fear_greed"]).sort_values("date").reset_index(drop=True)
    # Trailing percentile rank of the latest value (0..100).
    df["cnn_fear_greed_pctl"] = (
        df["cnn_fear_greed"]
        .rolling(PCTL_WINDOW, min_periods=PCTL_MIN)
        .apply(lambda w: float((w <= w.iloc[-1]).mean() * 100.0), raw=False)
        .round(2)
    )
    df["publish_date"] = df["date"]
    df["is_proxy"] = df["date"] < pd.Timestamp(LIVE_CNN_FROM)
    out.parent.mkdir(parents=True, exist_ok=True)
    df[["date", "publish_date", "cnn_fear_greed", "cnn_fear_greed_pctl", "is_proxy"]].to_csv(
        out, index=False, date_format="%Y-%m-%d"
    )
    print(f"wrote {len(df)} rows {df['date'].min().date()}..{df['date'].max().date()} → {out}")
    return out


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else RAW_URL
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("src/hermes_escape_top/data/soft_history/cnn_fear_greed.csv")
    build(source, out)


if __name__ == "__main__":
    main()
