# Flag Sweep — Full-Window Backtest (2018-01-02 → 2026-05-29)

**Generated**: 2026-06-09 · 2113 trading days · all variants share `manifest_id f1f455b0…` (identical data).
**Baseline** = deployed config (A10/A11/A15 on, all line-review flags OFF).
**Method**: `run_full_backtest` per variant, each in its own process. Top-line metrics only — this is a **screening pass, not the PBO/walk-forward gate**. Flipping any flag live still needs the walk-forward + PBO gate per the house rule.

## Results

| variant | CAGR | ΔCAGR | MaxDD | ΔMaxDD | Sharpe | Sortino | Calmar | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **baseline** | 15.39% | — | −14.04% | — | 1.116 | 1.459 | 1.096 | incumbent |
| scored_missing_weight (F5/F6) | 15.53% | +0.14 | −14.04% | 0.00 | 1.124 | 1.469 | 1.106 | ✅ mild + / correctness |
| partial_factor_eval (F4) | 15.39% | +0.00 | −14.04% | 0.00 | 1.116 | 1.459 | 1.096 | ⚪ no-op here / live robustness |
| suspect_valve_guard (F3) | 15.46% | +0.07 | **−13.30%** | **+0.74** | 1.119 | 1.464 | **1.162** | ✅ best MaxDD |
| decision_stabilizer (F1/F2) | **16.96%** | **+1.57** | −15.22% | **−1.18** | **1.175** | 1.543 | 1.114 | ⚠️ CAGR↑ but MaxDD↑ |
| f8_tightened (NAAIM/PCR) | 14.79% | −0.60 | −15.11% | −1.07 | 1.075 | 1.399 | 0.979 | ❌ worse everywhere |
| all_on | 17.04% | +1.65 | −14.64% | −0.60 | 1.171 | 1.541 | 1.164 | stabilizer-driven |
| _bench SPY_ | 13.14% | | −34.10% | | 0.736 | | 0.385 | |
| _bench QQQ_ | 20.15% | | −36.48% | | 0.891 | | 0.552 | |

## Read

- **F3 suspect-valve-guard — clean win.** MaxDD −14.04→−13.30 (+0.74pp), everything else flat-to-better, best single-flag Calmar (1.162). NOT a no-op as feared: there WERE suspect bars whose hard-valve EXIT, when held pending, avoided locking in a worse drawdown. Mechanism is conservative (only HIGH-severity sanitize anomalies). **Recommend flip** (after a glance at which dates it held, to confirm none was a real crash).
- **F5/F6 scored-missing-weight — mild positive + more correct.** Slightly higher CAGR/Sharpe, MaxDD unchanged. Removing permanent-placeholder inflation is the right semantics; effect is small because backtest missing-weight rarely crosses the blind-spot line. **Recommend flip** (will nudge the calibration baseline — ideally re-run NEXT-3).
- **F4 partial-factor-eval — no-op on this data** (constituents always present in the committed history), but it's a live-robustness fix and byte-identical when all components are present → **zero downside, recommend flip** for the live missing-component case.
- **F1/F2 decision-stabilizer — genuine trade-off.** Big CAGR (+1.57pp) and Sharpe/Sortino gains, but MaxDD WORSENS by 1.18pp (−14.04→−15.22). Delaying exits catches rebounds (↑return) but the one-close delay deepens true drawdowns — which cuts against a 逃顶 mandate. **Do NOT auto-flip**: needs PBO + a human risk-tradeoff call; consider a hysteresis-only variant (no confirmation delay) to keep the anti-chatter without the deeper DD.
- **F8 tightening — reject.** NAAIM pctl→85 + PCR pctl→12 is worse on every metric (CAGR −0.60, MaxDD −1.07, Sharpe −0.041). Confirms the prior finding: NAAIM's standalone forward-edge improvement does NOT survive in-system. **Keep defaults.**
- **all_on** is dominated by the stabilizer (CAGR/Sharpe up, MaxDD up) with F8's drag dragging it; not a recommended config as-is.

## Recommendation

| flag | screen | recommendation |
|---|---|---|
| `use_suspect_valve_guard` (F3) | MaxDD↓, all flat-to-+ | **flip after PBO** — best risk reduction, on-mandate |
| `use_scored_missing_weight` (F5/F6) | mild +, correctness | **flip after PBO** — re-baseline calibration |
| `use_partial_factor_eval` (F4) | neutral, robustness | **flip** — zero backtest downside, live-safety |
| `use_decision_stabilizer` (F1/F2) | CAGR↑ / MaxDD↑ | **hold** — human risk call + PBO; try hysteresis-only |
| F8 naaim/pcr tighten | worse all | **reject** — keep defaults |

Caveat: full-sample point estimates. Before any live flip, run the walk-forward + PBO gate (calibrate_next3_v2 pattern) on F3 + F5/F6 (and the hysteresis-only stabilizer variant if pursued).
