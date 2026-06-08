# Factor Autopsy + Next-Axis Roadmap — 2026-06-08

## 1. Autopsy of the "dead" (IC≈0) factors

The IC leaderboard's losers split into three causes — **not all are "missing data":**

| Factor | Real cause | Fix |
|---|---|---|
| **NAAIM** | **Mis-thresholded, not dead.** Real data (is_proxy=0), but the trigger (exposure≥70) fires **63% of days** (mean 67) → no discrimination → low IC. Tighten to **pctl≥90** and fwd-60d edge goes **−3.4 → −5.4pp** at ~9% fire-rate. | Re-threshold (no new data) — ride next calibration batch |
| **PCR** | **100% proxy** — the real CBOE equity-PCR endpoint is blocked, so it's a synthetic stand-in (collinear-ish with price). Weak edge (−2pp/60d). | Connect real CBOE PCR (manual download) |
| **CNN F&G, social, D-M4, D-M5** | Hard-coded `missing_only` **stubs** — never implemented. CNN/social are **forward-only → cannot backfill** per the first-class-data rule. | NEXT-4 only (forward-collected) |
| **valuation (B6)** | No valuation snapshot wired. | Wire a free forward-PE source |

**Methodological note:** IC structurally favors *coincident* factors (they're contemporaneous
with the move they "predict"). For a top-detector the right yardstick is event-based
(lead-time + precision/recall on labeled tops), not raw IC. Don't let the IC board pick factors.

## 2. Standalone signal screen of new candidates (2018–2026; negative edge = good sell signal)

| Factor | fire% | edge20d | edge60d | crash precision/recall (base 8%) | read |
|---|---:|---:|---:|---|---|
| A11 dollar (live) | 41 | −1.7 | −4.7 | 16% / 88% | strong |
| A10 real_rate (live) | 36 | −1.6 | −4.2 | 13% / 64% | good |
| **A18 MOVE** (new) | 30 | −0.7 | **−2.5** | 15% / 58% | good — bond vol leads VIX |
| A15 defensive (live) | 26 | −0.4 | −0.3 | 12% / 43% | weak but correct sign |
| **A17 NFCI** (new) | 22 | +0.6 | +2.0 | 13% / 38% | ambiguous (easy-money era) |
| A9 HY-OAS | 4 | +5.2 | +12 | 0% / 0% | counterproductive + 2023+ only |

**Caveat:** standalone understates *in-system* value (combine with C-module technicals);
A10/A11/A15 looked weak standalone yet halved drawdown in-system. So MOVE/NFCI verdicts are
provisional pending an in-system backtest + PBO (same gate as A10/A11/A15).

## 3. Built this round (flag-gated OFF, byte-identical proven)

- **A17_NFCI** — Chicago Fed NFCI (FRED, 1990+, pre-built financial-conditions composite).
- **A18_MOVE** — ICE BofA MOVE bond-vol (^MOVE via yfinance, 2018+), `LevelPercentileSource`.
- Other 5 of the original 8 (A9/A12/A13/A14/A16) remain OFF.

## 4. Roadmap (your axes, sequenced by ROI; backfillable = first-class for NEXT-2/3)

1. **Autopsy fixes** (cheapest): re-threshold NAAIM (done-analysis, pending deploy); decide PCR=proxy.
2. **Axis A** — NFCI + MOVE **built**; calibrate in-system next. (FRED OAS credit is a dead end:
   ICE BofA OAS series are license-capped to 2023+ on FRED — use HYG/LQD ETF ratios or NFCI's embedded credit.)
3. **Axis B leadership** — RSP/SPY (A14) + defensive/cyclical (A15) already built; the genuinely
   new half is **broad-market breadth** (%>200DMA, A/D line, McClellan, new-high−new-low) — needs a
   free PIT breadth source (the blocker).
4. **Axis D MSTR on-chain** (CoinMetrics free, backfillable) — highest-value NEW data, more work.
5. **Combination logic (arm-then-fire)** — the precision lever; little new data.

**Discipline:** incremental-IC (control for C10) not standalone; compress each axis to ONE composite
(not many raw columns) given sparse top events; walk-forward PBO before any live enable.
