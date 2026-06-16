# MSTR Hard-Valve Frequency & Forward-Return Diagnostic

Window: 2018-01-02 → 2026-06-04  ·  warmed days: 1918
Forward horizon: 20 trading days  ·  (H-M5 score-valve excluded: needs full scoring)

| Valve | active days | % days | episodes | median fwd20 | worst fwd20 | crash-hit (fwd20<-20%) | reading |
|---|---:|---:|---:|---:|---:|---:|---|
| H-M1 | 723 | 37.7% | 23 | +6.4% | -24.8% | 9% | fires into bounces — buffer candidate |
| H-M2 | 11 | 0.6% | 10 | +18.4% | -8.7% | 0% | fires into bounces — buffer candidate |
| H-M3 | 9 | 0.5% | 4 | +3.8% | -8.7% | 0% | mixed |
| H-M4 | 631 | 32.9% | 74 | +4.7% | -54.8% | 16% | tail insurance — keep |
| H-M6 | 308 | 16.1% | 63 | -3.5% | -48.6% | 18% | tail insurance — keep |

## Reading guide
- **State valves** (H-M1 close≤MA200, H-M6 chandelier) persist for many days → high % is expected, not over-trading; what matters is the *episode* count and its forward edge.
- **Event valves** (H-M2 −15%/EMA10, H-M3 2d−22%, H-M4 BTC<MA50+EMA20) are discrete; high episode count with weak/positive median fwd20 = candidate for a 'first 85% then confirm' buffer rather than instant 100%.
- median fwd20 **<< 0** ⇒ the valve catches real damage (keep instant 100%). median fwd20 **≥ ~0** ⇒ it often fires into noise/bounces (whipsaw + cash drag).
