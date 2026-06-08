"""F3 diagnostic: which dates did the suspect-valve-guard HOLD a hard valve?

For each trade symbol: sanitize the full history once → suspect dates; then on
each suspect date in the backtest window, check whether a hard valve would have
fired (suspect=False). Those are the days the guard downgraded a 100% EXIT to
pending. Prints each with the valve ids + the next few closes (to judge whether
holding was right — i.e. the bar was bad data, not a real crash).
"""
from __future__ import annotations

import pandas as pd

from hermes_escape_top.config import load_config, trade_symbols
from hermes_escape_top.core.backtest.snapshot import build_snapshot
from hermes_escape_top.core.data.sanitize import sanitize_ohlcv
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves

START, END = "2018-01-01", "2026-05-29"


def main() -> None:
    cfg = load_config()
    cfg.setdefault("runtime", {})["offline_replay_mode"] = True
    store = LocalStore(cfg)
    sanitize_cfg = cfg.get("sanitize", {})
    held_total = 0
    for symbol in trade_symbols(cfg):
        hist = store.load_history(symbol)
        if hist.empty:
            continue
        df = hist.rename(columns={c: str(c).lower() for c in hist.columns})
        res = sanitize_ohlcv(df, sanitize_cfg)
        suspect = [d for d in res.suspect_dates if START <= str(d)[:10] <= END]
        print(f"\n=== {symbol}: {len(suspect)} suspect bar(s) in window ===")
        for d in suspect:
            ds = str(d)[:10]
            # anomalies on that date for context
            kinds = ",".join(sorted({a.kind for a in res.anomalies if str(a.date)[:10] == ds and a.severity == "HIGH"}))
            snaps = build_snapshot(ds, store=store, cfg=cfg)
            hv = evaluate_hard_valves(symbol, snaps, suspect=False)
            if not hv.ids:
                print(f"  {ds}: suspect ({kinds}) but no hard valve would fire — no-op")
                continue
            held_total += 1
            # next 5 closes after the held date
            after = hist.loc[hist.index > pd.Timestamp(ds), "Close"].head(5)
            fwd = ", ".join(f"{v:.2f}" for v in after.values)
            close_d = hist.loc[hist.index <= pd.Timestamp(ds), "Close"]
            cd = close_d.iloc[-1] if len(close_d) else float("nan")
            print(f"  {ds}: HELD {','.join(hv.ids)} [{kinds}] close={cd:.2f} next5=[{fwd}]")
    print(f"\nTOTAL valve-days held pending: {held_total}")


if __name__ == "__main__":
    main()
