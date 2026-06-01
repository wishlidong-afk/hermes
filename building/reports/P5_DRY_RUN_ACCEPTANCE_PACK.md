# P5 Dry-run Acceptance Pack

**Date**: 2026-06-01
**Scope**: Phase II risk/correlation candidate review before Phase III scaler migration
**Live effect**: none. No feature flag is promoted here.

## Decision Summary

P5 is ready for a **shadow dry-run package**, not for live promotion.

The fixed candidate `corr_regime_extreme_pctl=110 / extreme_corr_penalty=0.70` passed the engineering checks needed to move into Phase III dry-run:

- full-window sensitivity has `errors=0` and `R3 violations=0`;
- fixed OOS below-median share is `0.3077`, while train-greedy PBO is `0.6154`;
- four exact optimizer spot-check windows match the fast projection within floating-point tolerance;
- live feature flags remain off.

## Source Artifacts

| Artifact | Purpose |
|---|---|
| `PhaseII_Shadow_Compare.md/json` | 252-day unified-pipeline shadow replay |
| `PhaseII_Corr_Sensitivity.md/json` | correlation threshold/penalty gross-scaler sensitivity |
| `PhaseII_Full_Backtest_Sensitivity.md/json` | 2018-2026 full-window sensitivity |
| `PhaseII_Full_Backtest_Sensitivity_Exact_2020H1.md/json` | exact optimizer stress-window spot-check |
| `PhaseII_Full_Backtest_Sensitivity_Exact_2022H1.md/json` | exact optimizer pressure-window spot-check |
| `PhaseII_Full_Backtest_Sensitivity_Exact_2024H1.md/json` | exact optimizer bull-window spot-check |
| `PhaseII_Full_Backtest_Sensitivity_Exact_2026YTD.md/json` | exact optimizer recent-window spot-check |

## Candidate Versus Baseline

| Metric | Old full-proxy baseline | P5 candidate 110/0.70 |
|---|---:|---:|
| Final value | $403,631.36 | $401,635.03 |
| CAGR | 18.13% | 18.06% |
| MaxDD | -27.60% | -22.47% |
| Sharpe | 0.8818 | 1.0115 |
| Sortino | 1.1155 | 1.3141 |
| Turnover | 326.6825 | 339.9802 |
| R3 violations | n/a | 0 |

Interpretation: candidate returns are effectively flat versus baseline, while drawdown and Sharpe improve. Turnover rises moderately and must be watched in dry-run.

## Walk-forward Governance

| Check | Result | Gate |
|---|---:|---|
| Fixed OOS below-median share | 0.3077 | PASS (<0.50) |
| Mean OOS rank | 8.7692 / 21 | PASS |
| Train-greedy PBO | 0.6154 | WARNING |

Interpretation: fixed candidate behavior is acceptable; greedy per-window parameter selection remains overfit and must not be used.

## Exact Optimizer Spot-check

| Window | Rows | Errors | R3 | Exact vs fast |
|---|---:|---:|---:|---|
| 2020-01-03 → 2020-07-02 | 126 | 0 | 0 | float-level match |
| 2022-01-03 → 2022-07-01 | 125 | 0 | 0 | exact match |
| 2024-01-03 → 2024-07-03 | 126 | 0 | 0 | float-level match |
| 2026-01-05 → 2026-05-29 | 101 | 0 | 0 | exact match |

Interpretation: the fast `R3 × confidence × risk_gross` projection used by the full-window scan is representative for these stress/bull/recent windows.

## Human Gate Checklist

| Gate | Status | Notes |
|---|---|---|
| `features.use_risk_engine` live promotion | BLOCKED | human approval required |
| `features.use_sizing_optimizer` live promotion | BLOCKED | human approval required |
| R3 invariant | PASS | all P5 reports show 0 violations |
| Exact spot-check | PASS | four windows checked |
| Dry-run output parity | TODO | compare daily old vs new target weights |
| Turnover review | TODO | candidate turnover higher than baseline |
| Data confidence | TODO | P3 soft data still incomplete |

## Next Build Step

Create a Phase III dry-run comparator that emits, for each replay day:

1. old target weights and routed legs;
2. P5 candidate target weights and routed legs;
3. per-symbol delta, turnover delta, and risk binding reason;
4. daily gate verdict: `PASS`, `WARN`, or `BLOCK`.

No live flag may be changed by this pack.
