"""⑤ MSTR hard-valve frequency + forward-return diagnostic.

Runs the REAL evaluate_hard_valves over 2018–2026 and reports, per H-M* valve:
  - active-day count / % of days  (state valves like H-M1 persist while below MA200)
  - distinct episodes (new trigger after a non-trigger day)
  - median MSTR forward 20D return at episode starts (real crash << 0 ; false alarm ~>= 0)

Goal: decide whether any valve fires so often / so weakly that forcing 100% EXIT
costs more (cash drag / whipsaw) than it saves. Read-only; writes a markdown report.

Run: PYTHONPATH=src python scripts/diagnose_mstr_hard_valves.py
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from statistics import median

import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.base import Field, SymbolSnapshot
from hermes_escape_top.core.data.store import LocalStore
from hermes_escape_top.core.features.indicators import indicator_frame
from hermes_escape_top.core.scoring.hard_valves import evaluate_hard_valves

MSTR_FIELDS = ["close", "ma200", "ema10", "ema20", "ema50", "chandelier_exit",
               "drawdown_60d_high_pct", "return_1d", "return_2d"]
FWD = 20


def _row_snapshot(symbol: str, row, d: date, cols) -> SymbolSnapshot:
    fields = {}
    for col in cols:
        src = "Close" if col == "close" else col
        val = row.get(src)
        fields[col] = Field(col, float(val) if pd.notna(val) else None, "diag", d)
    return SymbolSnapshot(symbol, d, fields)


def main() -> None:
    cfg = load_config()
    store = LocalStore(cfg)
    mstr = indicator_frame(store.load_history("MSTR"))
    btc = indicator_frame(store.load_history("BTC-USD"))
    mstr = mstr[mstr.index >= pd.Timestamp("2018-01-01")]
    close = mstr["Close"].astype(float).reset_index(drop=True)

    triggers: dict[str, list[int]] = {}   # id -> list of positional day indices active
    n_days = 0
    for pos, (ts, row) in enumerate(mstr.iterrows()):
        if pd.isna(row.get("ma200")):
            continue
        n_days += 1
        d = ts.date()
        snaps = {"MSTR": _row_snapshot("MSTR", row, d, MSTR_FIELDS)}
        btc_row = btc.loc[btc.index <= ts]
        if not btc_row.empty:
            snaps["BTC-USD"] = _row_snapshot("BTC-USD", btc_row.iloc[-1], d, ["close", "ma50"])
        res = evaluate_hard_valves("MSTR", snaps, histories={"MSTR": mstr, "BTC-USD": btc})
        for vid in res.ids:
            triggers.setdefault(vid, []).append(pos)

    def fwd_ret(pos: int):
        if pos + FWD < len(close) and close.iloc[pos] > 0:
            return close.iloc[pos + FWD] / close.iloc[pos] - 1.0
        return None

    lines = [
        "# MSTR Hard-Valve Frequency & Forward-Return Diagnostic",
        "",
        f"Window: {mstr.index.min().date()} → {mstr.index.max().date()}  ·  warmed days: {n_days}",
        f"Forward horizon: {FWD} trading days  ·  (H-M5 score-valve excluded: needs full scoring)",
        "",
        "| Valve | active days | % days | episodes | median fwd20 | worst fwd20 | crash-hit (fwd20<-20%) | reading |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for vid in sorted(triggers):
        days = triggers[vid]
        episodes = [p for i, p in enumerate(days) if i == 0 or days[i - 1] != p - 1]
        ep_rets = [r for r in (fwd_ret(p) for p in episodes) if r is not None]
        med = median(ep_rets) if ep_rets else float("nan")
        worst = min(ep_rets) if ep_rets else float("nan")
        crash_hit = (100.0 * sum(1 for r in ep_rets if r <= -0.20) / len(ep_rets)) if ep_rets else float("nan")
        pct = 100.0 * len(days) / max(1, n_days)
        # Tail-aware: a valve earns its instant-100% if it catches real left-tail
        # damage often enough, regardless of a positive median (insurance, not alpha).
        if crash_hit >= 30.0 or worst <= -0.35:
            reading = "tail insurance — keep"
        elif med >= 0.05 and crash_hit < 15.0:
            reading = "fires into bounces — buffer candidate"
        else:
            reading = "mixed"
        lines.append(
            f"| {vid} | {len(days)} | {pct:.1f}% | {len(episodes)} | {med:+.1%} | {worst:+.1%} | {crash_hit:.0f}% | {reading} |"
        )

    lines += [
        "",
        "## Reading guide",
        "- **State valves** (H-M1 close≤MA200, H-M6 chandelier) persist for many days → high % is expected, not over-trading; what matters is the *episode* count and its forward edge.",
        "- **Event valves** (H-M2 −15%/EMA10, H-M3 2d−22%, H-M4 BTC<MA50+EMA20) are discrete; high episode count with weak/positive median fwd20 = candidate for a 'first 85% then confirm' buffer rather than instant 100%.",
        "- median fwd20 **<< 0** ⇒ the valve catches real damage (keep instant 100%). median fwd20 **≥ ~0** ⇒ it often fires into noise/bounces (whipsaw + cash drag).",
    ]
    out = Path(__file__).resolve().parents[1] / "review" / "HARD_VALVE_FREQUENCY_MSTR.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
