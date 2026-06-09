"""① T3 reentry-gate timing diagnostic (read-only).

The full backtest can't see ① — run_full re-enters by score decay and never runs
the 3-3-4 tranche gates. This measures the gate timing directly on QQQ 2018–2026:

  strict  = market_252d_high  (current: close >= prior 252-day high)
  relaxed = ma200_reclaim     (close > MA200 AND >= off_low_pct off the 60D low)

For each "relaxed reclaim" event it finds how many days until the strict gate
would finally clear, and the QQQ return over that gap — i.e. the upside the final
40% tranche forgoes (sitting in cash) under the strict gate, IF you tranche back
in by the 3-3-4 advice. (If you re-enter by score like the backtest, ① is moot.)

Run: PYTHONPATH=src python scripts/diagnose_t3_reentry_gate.py
"""
from __future__ import annotations

from pathlib import Path
from statistics import median, mean

import numpy as np
import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.features.indicators import indicator_frame

OFF_LOW_PCT = 0.10


def main() -> None:
    cfg = load_config()
    store = LocalStore(cfg)
    qqq = indicator_frame(store.load_history("QQQ"))
    qqq = qqq[qqq.index >= pd.Timestamp("2018-01-01")].copy()
    close = qqq["Close"].astype(float)
    ma200 = qqq["ma200"].astype(float)

    prior_252_high = close.shift(1).rolling(252).max()
    low_60 = close.rolling(60).min()
    gate_strict = (close >= prior_252_high)
    gate_relaxed = (close > ma200) & ((close / low_60 - 1.0) >= OFF_LOW_PCT)
    valid = prior_252_high.notna() & ma200.notna() & low_60.notna()
    gate_strict, gate_relaxed = gate_strict[valid], gate_relaxed[valid]
    c = close[valid]
    n = len(c)

    # Relaxed-reclaim events: relaxed True today, False yesterday.
    relaxed_arr = gate_relaxed.values
    strict_arr = gate_strict.values
    events = [i for i in range(1, n) if relaxed_arr[i] and not relaxed_arr[i - 1]]

    gaps, fwd_rets = [], []
    for i in events:
        j = i
        while j < n and not strict_arr[j]:
            j += 1
        gap = j - i  # trading days parked under strict gate after relaxed cleared
        if gap <= 0:
            continue
        end = min(j, n - 1)
        gaps.append(gap)
        fwd_rets.append(float(c.iloc[end] / c.iloc[i] - 1.0))

    pct_strict = 100.0 * float(strict_arr.mean())
    pct_relaxed = 100.0 * float(relaxed_arr.mean())
    only_relaxed = 100.0 * float((relaxed_arr & ~strict_arr).mean())

    lines = [
        "# ① T3 Reentry-Gate Timing Diagnostic (QQQ 2018–2026)",
        "",
        f"Days analysed: {n}  ·  off_low_pct={OFF_LOW_PCT:.0%}",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| % days strict gate (252D-high) met | {pct_strict:.1f}% |",
        f"| % days relaxed gate (MA200 reclaim) met | {pct_relaxed:.1f}% |",
        f"| % days relaxed-met-but-strict-not (T3 parked under strict) | **{only_relaxed:.1f}%** |",
        f"| relaxed-reclaim episodes | {len(gaps)} |",
        f"| median days T3 parked after relaxed clears | **{median(gaps):.0f}** |",
        f"| mean days parked | {mean(gaps):.0f} |",
        f"| max days parked | {max(gaps)} |",
        f"| median QQQ return over the parked gap (forgone on the 40% tranche) | **{median(fwd_rets):+.1%}** |",
        f"| mean QQQ return over gap | {mean(fwd_rets):+.1%} |",
        "",
        "## Reading",
        "- The strict gate parks the final 40% tranche an extra **{:.0f} trading-day median** ".format(median(gaps)),
        "  (~{:.1f} months) past the point a trend reclaim is confirmed.".format(median(gaps) / 21.0),
        f"- Over that window QQQ moved a median **{median(fwd_rets):+.1%}** — that is the upside the 40%",
        "  tranche forgoes under the strict gate, **only if you actually tranche back in by 3-3-4**.",
        "- Caveat: this is an upper-bound ceiling (counts all relaxed-not-strict days, not only",
        "  in-reentry days), and positive median forgone return is the bull-case; the bear-case is",
        "  the relaxed gate redeploys into a failed bounce. A reentry-aware backtest would net these.",
    ]
    out = Path(__file__).resolve().parents[1] / "review" / "T3_REENTRY_GATE_TIMING.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
