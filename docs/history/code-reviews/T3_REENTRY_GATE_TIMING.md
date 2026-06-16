# ① T3 Reentry-Gate Timing Diagnostic (QQQ 2018–2026)

Days analysed: 1865  ·  off_low_pct=10%

| metric | value |
|---|---:|
| % days strict gate (252D-high) met | 14.9% |
| % days relaxed gate (MA200 reclaim) met | 49.5% |
| % days relaxed-met-but-strict-not (T3 parked under strict) | **35.7%** |
| relaxed-reclaim episodes | 48 |
| median days T3 parked after relaxed clears | **32** |
| mean days parked | 61 |
| max days parked | 371 |
| median QQQ return over the parked gap (forgone on the 40% tranche) | **+3.7%** |
| mean QQQ return over gap | +3.3% |

## Reading
- The strict gate parks the final 40% tranche an extra **32 trading-day median** 
  (~1.5 months) past the point a trend reclaim is confirmed.
- Over that window QQQ moved a median **+3.7%** — that is the upside the 40%
  tranche forgoes under the strict gate, **only if you actually tranche back in by 3-3-4**.
- Caveat: this is an upper-bound ceiling (counts all relaxed-not-strict days, not only
  in-reentry days), and positive median forgone return is the bull-case; the bear-case is
  the relaxed gate redeploys into a failed bounce. A reentry-aware backtest would net these.
