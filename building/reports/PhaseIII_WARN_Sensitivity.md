# Phase III WARN Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 252 / loaded 252
Scenario count: 24
Thresholds: `[100.0, 110.0, 120.0, 130.0, 140.0, 150.0]`
Penalties: `[0.7, 0.8, 0.9, 1.0]`
Live effect: `none`

## Review Candidates

| Pick | Threshold | Penalty | Score | WARN Share | Extreme Share | WARN 10d Δ | Max Turnover Δ | Readiness |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| current_110_070 | 110.0000 | 0.7000 | 0.3888 | 49.21% | 40.48% | -0.29% | 0.4022 | REVIEW_REQUIRED |
| balanced_lowest_score | 110.0000 | 0.9000 | 0.1340 | 48.81% | 40.48% | -0.13% | 0.2886 | REVIEW_READY |
| lowest_warn_10d_drag_with_penalty | 110.0000 | 0.9000 | 0.1340 | 48.81% | 40.48% | -0.13% | 0.2886 | REVIEW_READY |
| lowest_warn_10d_drag | 100.0000 | 1.0000 | 0.4517 | 64.68% | 59.13% | -0.05% | 0.2751 | NO_PENALTY_REVIEW |
| lowest_warn_share | 150.0000 | 1.0000 | 0.6113 | 20.63% | 10.32% | -0.12% | 0.2751 | NO_PENALTY_REVIEW |

## Scenario Grid

| Threshold | Penalty | Score | Readiness | WARN | EXTREME_CORR | WARN 1d Δ | WARN 5d Δ | WARN 10d Δ | Max Turnover Δ | R3 | BLOCK |
|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 110.0000 | 0.9000 | 0.1340 | REVIEW_READY | 48.81% | 40.48% | 0.00% | 0.01% | -0.13% | 0.2886 | 0 | 0 |
| 120.0000 | 0.9000 | 0.1677 | REVIEW_READY | 38.49% | 28.97% | -0.01% | -0.02% | -0.17% | 0.2751 | 0 | 0 |
| 110.0000 | 0.8000 | 0.2562 | REVIEW_REQUIRED | 48.81% | 40.48% | -0.00% | -0.02% | -0.21% | 0.3454 | 0 | 0 |
| 120.0000 | 0.8000 | 0.2634 | REVIEW_READY | 38.49% | 28.97% | -0.03% | -0.07% | -0.26% | 0.2751 | 0 | 0 |
| 100.0000 | 0.9000 | 0.2705 | REVIEW_REQUIRED | 65.08% | 59.13% | -0.02% | -0.04% | -0.15% | 0.3243 | 0 | 0 |
| 130.0000 | 0.9000 | 0.2851 | TOO_RELAXED_REVIEW | 30.16% | 19.84% | -0.00% | -0.02% | -0.28% | 0.2751 | 0 | 0 |
| 140.0000 | 0.9000 | 0.3080 | TOO_RELAXED_REVIEW | 23.41% | 12.70% | 0.01% | 0.05% | -0.16% | 0.2751 | 0 | 0 |
| 150.0000 | 0.9000 | 0.3534 | TOO_RELAXED_REVIEW | 21.03% | 10.32% | 0.01% | 0.07% | -0.16% | 0.2751 | 0 | 0 |
| 110.0000 | 1.0000 | 0.3572 | NO_PENALTY_REVIEW | 48.81% | 40.48% | 0.01% | 0.04% | -0.06% | 0.2751 | 0 | 0 |
| 140.0000 | 0.8000 | 0.3622 | TOO_RELAXED_REVIEW | 24.21% | 12.70% | -0.00% | 0.00% | -0.22% | 0.2751 | 0 | 0 |
| 120.0000 | 1.0000 | 0.3719 | NO_PENALTY_REVIEW | 38.49% | 28.97% | 0.00% | 0.04% | -0.07% | 0.2751 | 0 | 0 |
| 100.0000 | 0.8000 | 0.3853 | REVIEW_REQUIRED | 65.08% | 59.13% | -0.03% | -0.09% | -0.24% | 0.3454 | 0 | 0 |
| 110.0000 | 0.7000 | 0.3888 | REVIEW_REQUIRED | 49.21% | 40.48% | -0.00% | -0.05% | -0.29% | 0.4022 | 0 | 0 |
| 150.0000 | 0.8000 | 0.3905 | TOO_RELAXED_REVIEW | 21.83% | 10.32% | 0.01% | 0.04% | -0.20% | 0.2751 | 0 | 0 |
| 130.0000 | 1.0000 | 0.4183 | NO_PENALTY_REVIEW | 29.76% | 19.84% | 0.01% | 0.06% | -0.12% | 0.2751 | 0 | 0 |
| 140.0000 | 0.7000 | 0.4210 | REVIEW_REQUIRED | 24.21% | 12.70% | -0.01% | -0.04% | -0.27% | 0.3012 | 0 | 0 |
| 120.0000 | 0.7000 | 0.4247 | REVIEW_REQUIRED | 38.89% | 28.97% | -0.04% | -0.12% | -0.35% | 0.3753 | 0 | 0 |
| 150.0000 | 0.7000 | 0.4345 | REVIEW_REQUIRED | 21.83% | 10.32% | 0.02% | 0.01% | -0.24% | 0.3012 | 0 | 0 |
| 100.0000 | 1.0000 | 0.4517 | NO_PENALTY_REVIEW | 64.68% | 59.13% | -0.01% | 0.01% | -0.05% | 0.2751 | 0 | 0 |
| 130.0000 | 0.8000 | 0.5007 | REVIEW_REQUIRED | 30.95% | 19.84% | -0.01% | -0.09% | -0.44% | 0.3610 | 0 | 0 |
| 100.0000 | 0.7000 | 0.5399 | REVIEW_REQUIRED | 65.48% | 59.13% | -0.03% | -0.13% | -0.33% | 0.4022 | 0 | 0 |
| 140.0000 | 1.0000 | 0.5503 | NO_PENALTY_REVIEW | 23.02% | 12.70% | 0.01% | 0.09% | -0.10% | 0.2751 | 0 | 0 |
| 150.0000 | 1.0000 | 0.6113 | NO_PENALTY_REVIEW | 20.63% | 10.32% | 0.01% | 0.10% | -0.12% | 0.2751 | 0 | 0 |
| 130.0000 | 0.7000 | 0.7752 | REVIEW_REQUIRED | 30.95% | 19.84% | -0.02% | -0.17% | -0.60% | 0.4714 | 0 | 0 |

## Notes

- Read-only sensitivity grid; no live config, feature flag, account state, signal journal, or order routing is changed.
- The score is a human-review ordering aid, not an optimizer and not a live approval.
- Scenarios should be checked against full-window backtest sensitivity before any scaler migration.
