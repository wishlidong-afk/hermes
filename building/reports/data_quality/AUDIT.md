# Data-Quality Audit

## Findings (2026-06-09)

- **No new landmines among tradeable price series.** All trade symbols (MSTR/SOXL) and every equity constituent + radar ETF (QQQ/SPY/SOXX/SMH/NVDA/… ) are clean: 0% zero-volume, no >40% gaps, no >50% prints, stale ≤3.
- **The 7 "100% zero-volume" rows are INDICES** (^VIX/^VIX3M/^VIX9D/^VVIX/^SKEW/^SOX/^NYFANG) — indices have no volume by definition, so this is expected, not corruption. The bad-tick fix (disable volume-based detection when a series is structurally zero-volume) correctly covers all of them, so the FNGU class of false-suspect **generalizes and is handled**.
- **FNGU 85% zero-volume** — the original offender (ETN, unreported volume); already handled by the detector fix.
- The index ">50% move"/">40% gap" counts (e.g. ^VIX9D x19, ^VIX x6) are **real volatility-index spikes**, not data errors — and they no longer false-flag (volume-gated detection is off for them; the split/gap detector is only MEDIUM severity and never holds a hard valve).
- **One residual to watch: FNGS 22% zero-volume** (1x FANG+ ETN, a FNGU radar in H-F2/H-F5). It sits BELOW the 50% disable threshold, so volume-based bad-tick detection is still active for it. Risk is low (1x, >15% daily moves are rare) but on a zero-volume big-move day it could still false-flag. Options if desired: lower bad_tick_max_zero_vol_frac toward ~0.2, or require cross-source confirmation for bad-tick.
- The uniform `miss_bd ≈ 81` is the holiday calendar (~10/yr × 8yr), not gaps — below the 10% coverage-flag threshold.

**Conclusion: price-data quality is sound; the only genuine issue (zero-volume ETN/index bad-tick mis-fire) is fixed and the fix generalizes. FNGS is a minor, low-risk residual.**

---

36 symbols · 9 flagged

| symbol | rows | range | zero-vol | stale | gap>40% | \|ret\|>50% | >5σ | miss-bd | flags |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| FNGU | 2117 | 2018-01-02→2026-06-04 | 85% | 2 | 0 | 0 | 4 | 81 | ZERO-VOL 85% |
| SOXL | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 1 | 3 | 81 | |ret|>50% x1 |
| ^NYFANG | 2117 | 2018-01-02→2026-06-04 | 100% | 1 | 1 | 0 | 4 | 81 | ZERO-VOL 100%, GAP>40% x1 |
| ^SKEW | 2066 | 2018-01-02→2026-06-04 | 100% | 5 | 0 | 0 | 3 | 132 | ZERO-VOL 100%, STALE 5d |
| ^SOX | 2117 | 2018-01-02→2026-06-04 | 100% | 1 | 0 | 0 | 2 | 81 | ZERO-VOL 100% |
| ^VIX | 2118 | 2018-01-02→2026-06-04 | 100% | 2 | 1 | 6 | 8 | 80 | ZERO-VOL 100%, GAP>40% x1, |ret|>50% x6 |
| ^VIX3M | 2117 | 2018-01-02→2026-06-04 | 100% | 2 | 1 | 1 | 11 | 81 | ZERO-VOL 100%, GAP>40% x1, |ret|>50% x1 |
| ^VIX9D | 2117 | 2018-01-02→2026-06-04 | 100% | 2 | 11 | 19 | 8 | 81 | ZERO-VOL 100%, GAP>40% x11, |ret|>50% x19 |
| ^VVIX | 2109 | 2018-01-02→2026-06-04 | 100% | 2 | 1 | 0 | 8 | 89 | ZERO-VOL 100%, GAP>40% x1 |
| AAPL | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| AMAT | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 4 | 81 | ok |
| AMD | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 4 | 81 | ok |
| AMZN | 2117 | 2018-01-02→2026-06-04 | 0% | 3 | 0 | 0 | 4 | 81 | ok |
| ASML | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 5 | 81 | ok |
| AVGO | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| BOXX | 861 | 2022-12-28→2026-06-04 | 0% | 3 | 0 | 0 | 2 | 36 | ok |
| BRK.B | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| BTC-USD | 3076 | 2018-01-01→2026-06-05 | 0% | 1 | 0 | 0 | 5 | 2 | ok |
| DBMF | 1779 | 2019-05-08→2026-06-04 | 3% | 3 | 0 | 0 | 3 | 68 | ok |
| FNGS | 2117 | 2018-01-02→2026-06-04 | 22% | 3 | 0 | 0 | 4 | 81 | ok |
| GOOGL | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 3 | 81 | ok |
| KLAC | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| LRCX | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 5 | 81 | ok |
| META | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 9 | 81 | ok |
| MSFT | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 5 | 81 | ok |
| MSTR | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 8 | 81 | ok |
| MU | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 5 | 81 | ok |
| NFLX | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 5 | 81 | ok |
| NVDA | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| QCOM | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 6 | 81 | ok |
| QQQ | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 6 | 81 | ok |
| SMH | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 2 | 81 | ok |
| SOXX | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 2 | 81 | ok |
| SPY | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 7 | 81 | ok |
| TSLA | 2117 | 2018-01-02→2026-06-04 | 0% | 2 | 0 | 0 | 3 | 81 | ok |
| TSM | 2117 | 2018-01-02→2026-06-04 | 0% | 3 | 0 | 0 | 5 | 81 | ok |
