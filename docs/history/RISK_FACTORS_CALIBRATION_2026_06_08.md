# Risk-Factor Calibration & Deployment — 2026-06-08

Enabled **A10 (10Y real rate, FRED DFII10)**, **A11 (broad dollar, FRED DTWEXBGS)**,
**A15 (defensive/cyclical rotation, XLP+XLU+XLV ÷ XLY+XLI+XLF)** in the escape-top
A-module, with recalibrated `DEFENSIVE_EXIT 65→70` (combo **E75_D70_R50**).

## Why these 3 (and not the other 5)

A standalone signal screen over 2018–2026 (forward-return edge + drawdown
precision/recall) showed most of the 8 candidate factors are weak or
counterproductive *as short-horizon sell signals*:

- **Kept:** A11 dollar (edge −1.7/−4.7/−8.6pp at 20/60/120d; fires before 88% of
  −10% drawdowns), A10 real-rate (−1.6/−4.2/−3.6pp; recall 64%), A15 defensive
  rotation (correct sign, modest).
- **Dropped (OFF):** A9 HY-OAS (+5.2pp — fires before bounces; also FRED only has
  2023+), A12 yield-curve (+, this window), A13 credit-ETF (+), A14 concentration
  (mixed), A16 financials (~0). These remain implemented and flag-gated OFF.

Standalone screens understate *in-system* value (these macro factors combine with
the C-module technicals), which the full backtest confirmed.

## Calibration (calibrate_next3_v2, walk-forward PBO over 2018–2026 full-proxy)

| Gate | Value | Pass |
|---|---|---|
| Deployment PBO (fixed combo) | 0.1538 | ✅ <0.5 |
| Train-greedy PBO (overfit diag) | 0.4615 | ✅ <0.5 (baseline was 0.6154) |
| Real-only rank percentile | 0.65 | ✅ above median |
| **next3_pass** | **true** | ✅ |

Chosen combo **E75_D70_R50** (only DEFENSIVE_EXIT moves, 65→70).

## Impact (same backtest pipeline, full window 2018–2026 incl. 2018/2020/2022)

| | Baseline (OFF) | 3-on calibrated |
|---|---|---|
| MaxDD | −27.6% | **−14.2%** |
| Sharpe | 0.88 | **1.11** |
| Sortino | 1.12 | **1.45** |
| CAGR | 18.1% | 15.3% |

Honest tradeoff: in a **pure bull** (real-only 2025-02→2026-05) the defense drags
return (CAGR 44.4%→25.8%) for a smaller DD gain (−10.4%→−7.5%). Over a **full
cycle that includes crashes**, the defense is a net win (≈half the drawdown, higher
Sharpe/Sortino) — which is the escape-top mandate.

## Deployment

- `config.json`: `data_real_rate=true`, `data_dollar=true`,
  `data_defensive_rotation=true`; `status_thresholds.DEFENSIVE_EXIT=70`; provenance
  in `_risk_calibration`. Applied to repo + `.hermes`.
- Other 5 risk factors remain implemented and flag-gated **OFF**.
- Live read-only/advisory only — never trades.

## Rollback

Set the 3 flags back to `false` and `DEFENSIVE_EXIT` to `65` in `config.json`
(instant revert to the prior calibrated system; code path then byte-identical to
pre-risk-factor state).
