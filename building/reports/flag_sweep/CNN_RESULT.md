# CNN Fear & Greed (A2) — Backtest Result

**Date**: 2026-06-09 · full window 2018-2026 · CNN-isolated (both runs use the
current deployed config — scored_missing_weight / suspect_guard / partial_eval on —
differing only in `data_cnn_fgi`). Data coverage full (2011 base → 2018+ complete).

| variant | CAGR | MaxDD | Sharpe | Sortino | final |
|---|---:|---:|---:|---:|---:|
| baseline (CNN off) | 15.84% | −14.04% | 1.140 | 1.491 | 342,506 |
| cnn_fgi (CNN on) | 15.80% | −14.04% | 1.151 | 1.509 | 341,660 |
| **Δ** | **−0.03pp** | **0.00** | **+0.011** | **+0.018** | −846 |

## Read

**Essentially neutral — within noise.** Marginally better risk-adjusted (Sharpe
+0.011, Sortino +0.018), a hair lower CAGR (−0.03pp), MaxDD unchanged. The factor
is correctly wired and full-coverage (fires at the 2021-11 top F&G 74.5/pctl 92.9,
silent at the COVID bottom F&G 5) — but its full-system marginal effect is ~nil.

**Why nil:** A-module is cap-saturated (cap=20, already filled by A1/A4/A7/A8 +
A10/A11/A15). A new 2-pt A2 sub-factor that is also collinear with the existing
sentiment/vol factors (VIX, AAII, breadth) barely moves a bucket that's already at
or near cap when it matters. Same structural ceiling the factor-exploration work
hit: on a 6yr window, adding more A-module factors ≈ noise.

## Recommendation

- **Don't flip `data_cnn_fgi` for performance** — the edge is indistinguishable
  from zero; not worth a PBO gate (the signal is smaller than fold-to-fold noise).
- It's **harmless to enable** (MaxDD flat, Sharpe a touch higher) and now correct +
  full-coverage, so it's a fine *live* sentiment input to keep available.
- The only way CNN (or any new A factor) becomes material is **F7**: raise/decouple
  the A-module cap so leading/sentiment factors aren't swallowed by the cap-20
  saturation. Until then, more A-module factors are a wash.
