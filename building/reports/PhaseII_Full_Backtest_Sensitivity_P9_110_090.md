# Phase II Full Backtest Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 2113 / loaded 2113
Live effect: `none`
Exact optimizer: `False`
Date filter: `{'start': None, 'end': None}`

## Baseline Old Backtest

| Metric | Value |
|---|---:|
| Final value | $403,631.36 |
| CAGR | 18.13% |
| MaxDD | -27.60% |
| Sharpe | 0.8818 |
| Sortino | 1.1155 |
| Turnover | 326.6825 |

## Review Candidate

| Field | Value |
|---|---:|
| Threshold | 110.0000 |
| Penalty | 0.9000 |
| Hit share | 39.71% |
| Avg gross | 0.9205 |
| Min gross | 0.4571 |
| Final value | $472,466.65 |
| CAGR | 20.37% |
| MaxDD | -24.32% |
| Sharpe | 1.0171 |
| DSR | 0.9307 |
| Turnover | 338.0594 |
| Fixed OOS below-median share | 1.0000 |
| Mean OOS rank | 1.0000 |
| R3 violations | 0 |

## Walk Forward / PBO

- Train-greedy PBO: `1.0000`
- Note: PBO is the share of folds where the train-best scenario lands below median OOS rank.

## Scenario Grid

| Threshold | Penalty | Hit Share | Avg Gross | Final | CAGR | MaxDD | Sharpe | DSR | Fixed PBO | Mean Rank | Turnover | R3 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 110.0000 | 0.9000 | 39.71% | 0.9205 | $472,466.65 | 20.37% | -24.32% | 1.0171 | 0.9307 | 1.0000 | 1.0000 | 338.0594 | 0 |

## Train-Greedy Fold Checks

| Train | Test | Train-Best | OOS Rank | Scenarios |
|---|---|---:|---:|---:|
| 2018-01-02→2019-12-03 | 2020-01-03→2020-07-02 | 110.0000/0.9000 | 1 | 1 |
| 2018-07-02→2020-06-04 | 2020-07-06→2020-12-31 | 110.0000/0.9000 | 1 | 1 |
| 2019-01-02→2020-12-02 | 2021-01-04→2021-07-02 | 110.0000/0.9000 | 1 | 1 |
| 2019-07-02→2021-06-04 | 2021-07-06→2022-01-03 | 110.0000/0.9000 | 1 | 1 |
| 2020-01-02→2021-12-02 | 2022-01-03→2022-07-01 | 110.0000/0.9000 | 1 | 1 |
| 2020-07-02→2022-06-02 | 2022-07-05→2023-01-03 | 110.0000/0.9000 | 1 | 1 |
| 2021-01-04→2022-12-01 | 2023-01-03→2023-07-03 | 110.0000/0.9000 | 1 | 1 |
| 2021-07-02→2023-06-01 | 2023-07-03→2024-01-03 | 110.0000/0.9000 | 1 | 1 |
| 2022-01-03→2023-12-01 | 2024-01-03→2024-07-03 | 110.0000/0.9000 | 1 | 1 |
| 2022-07-05→2024-06-03 | 2024-07-03→2025-01-03 | 110.0000/0.9000 | 1 | 1 |
| 2023-01-03→2024-12-03 | 2025-01-03→2025-07-03 | 110.0000/0.9000 | 1 | 1 |
| 2023-07-03→2025-06-03 | 2025-07-03→2026-01-02 | 110.0000/0.9000 | 1 | 1 |
| 2024-01-02→2025-12-03 | 2026-01-05→2026-05-29 | 110.0000/0.9000 | 1 | 1 |

## Notes

- Shadow-only replay; no live config, feature flag, account state, or signal journal is changed.
- Uses cached historical A/B/C/D score rows, then routes residual sleeve capital through the cached capital-routing decision for that day.
- Default scenario sizing uses the deterministic R3/confidence/risk-gross upper-bound projection; pass --exact-optimizer for slow SLSQP spot checks.
- The candidate is a review target only; Phase III scaler replacement remains locked until human dry-run gates pass.
