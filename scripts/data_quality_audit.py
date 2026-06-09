"""Data-quality audit across all symbols' OHLCV history.

Motivation: the F3 diagnostic found FNGU is 84.7% zero-volume, which silently
mis-fired the bad-tick detector on real crash days. Bad data corrupts signals
invisibly. This sweeps every symbol for the same class of issues and ranks them.

Checks per symbol: zero/NaN volume %, zero/NaN close %, max stale (consecutive
identical closes), split-suspect overnight gaps (>40%), return outliers (>5σ and
>50% raw), business-day coverage gaps. Writes building/reports/data_quality/AUDIT.md.

Usage: PYTHONPATH=src python3 scripts/data_quality_audit.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from hermes_escape_top.config import load_config
from hermes_escape_top.core.data.store import LocalStore

OUT = Path("building/reports/data_quality/AUDIT.md")


def universe(cfg) -> list[str]:
    syms: set[str] = set(cfg.get("market_symbols", []))
    syms.update(s for s in cfg.get("symbols", {}))
    for r in cfg.get("radars", {}).values():
        syms.update(r)
    for c in cfg.get("component_proxies", {}).values():
        syms.update(c)
    routing = cfg.get("routing", {})
    for d in ("defcon1", "defcon2", "defcon3"):
        for v in (routing.get(d, {}) or {}).values():
            if isinstance(v, str):
                syms.add(v)
    syms.update(["BTC-USD"])
    return sorted(syms)


def max_stale(closes: np.ndarray) -> int:
    best = run = 1
    for i in range(1, len(closes)):
        run = run + 1 if closes[i] == closes[i - 1] else 1
        best = max(best, run)
    return best if len(closes) else 0


def audit_symbol(sym: str, df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"symbol": sym, "rows": 0, "status": "MISSING"}
    close = pd.to_numeric(df.get("Close"), errors="coerce")
    vol = pd.to_numeric(df.get("Volume"), errors="coerce") if "Volume" in df.columns else pd.Series([np.nan] * n)
    ret = close.pct_change()
    open_ = pd.to_numeric(df.get("Open"), errors="coerce") if "Open" in df.columns else close
    gap = (open_ - close.shift(1)).abs() / close.shift(1).replace(0, np.nan)
    sigma = ret.std()
    z = (ret - ret.mean()).abs() / sigma if sigma and sigma > 0 else ret * 0
    # business-day coverage gap (approx; ignores holidays)
    bdays = pd.bdate_range(df.index.min(), df.index.max())
    missing_bdays = len(bdays) - len(df.index.intersection(bdays))
    zero_vol = float((vol == 0).mean()) if vol.notna().any() else float("nan")
    flags = []
    if not np.isnan(zero_vol) and zero_vol > 0.5:
        flags.append(f"ZERO-VOL {zero_vol:.0%}")
    if (close <= 0).sum() or close.isna().sum():
        flags.append(f"BAD-CLOSE {int((close <= 0).sum() + close.isna().sum())}")
    stale = max_stale(close.values)
    if stale >= 4:
        flags.append(f"STALE {stale}d")
    nsplit = int((gap > 0.40).sum())
    if nsplit:
        flags.append(f"GAP>40% x{nsplit}")
    nbig = int((ret.abs() > 0.50).sum())
    if nbig:
        flags.append(f"|ret|>50% x{nbig}")
    if missing_bdays > 0.10 * len(bdays):
        flags.append(f"COVERAGE-{missing_bdays}bd")
    return {
        "symbol": sym, "rows": n, "start": str(df.index.min().date()), "end": str(df.index.max().date()),
        "zero_vol": zero_vol, "stale": stale, "gap40": nsplit, "ret50": nbig, "out5sig": int((z > 5).sum()),
        "miss_bd": missing_bdays, "flags": ", ".join(flags) or "ok",
    }


def main() -> None:
    cfg = load_config()
    store = LocalStore(cfg)
    rows = [audit_symbol(s, store.load_history(s)) for s in universe(cfg)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    flagged = [r for r in rows if r.get("flags", "ok") not in ("ok",) or r.get("status") == "MISSING"]
    lines = ["# Data-Quality Audit\n", f"{len(rows)} symbols · {len(flagged)} flagged\n"]
    lines.append("| symbol | rows | range | zero-vol | stale | gap>40% | \\|ret\\|>50% | >5σ | miss-bd | flags |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---|")
    for r in sorted(rows, key=lambda x: (x.get("flags", "ok") == "ok", x["symbol"])):
        if r.get("status") == "MISSING":
            lines.append(f"| {r['symbol']} | 0 | — | — | — | — | — | — | — | **MISSING** |")
            continue
        zv = "—" if np.isnan(r["zero_vol"]) else f"{r['zero_vol']:.0%}"
        lines.append(
            f"| {r['symbol']} | {r['rows']} | {r['start']}→{r['end']} | {zv} | {r['stale']} | "
            f"{r['gap40']} | {r['ret50']} | {r['out5sig']} | {r['miss_bd']} | {r['flags']} |"
        )
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
