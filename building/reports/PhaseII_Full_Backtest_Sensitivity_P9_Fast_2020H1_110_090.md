# Phase II Full Backtest Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 126 / loaded 126
Live effect: `none`
Exact optimizer: `False`
Date filter: `{'start': '2020-01-03', 'end': '2020-07-02'}`

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
| Hit share | 26.19% |
| Avg gross | 0.9599 |
| Min gross | 0.6989 |
| Final value | $114,315.01 |
| CAGR | 31.22% |
| MaxDD | -10.66% |
| Sharpe | 1.2823 |
| DSR | 1.0701 |
| Turnover | 13.1918 |
| Fixed OOS below-median share | n/a |
| Mean OOS rank | n/a |
| R3 violations | 0 |

## Walk Forward / PBO

- Train-greedy PBO: `n/a`
- Note: n/a

## Scenario Grid

| Threshold | Penalty | Hit Share | Avg Gross | Final | CAGR | MaxDD | Sharpe | DSR | Fixed PBO | Mean Rank | Turnover | R3 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 110.0000 | 0.9000 | 26.19% | 0.9599 | $114,315.01 | 31.22% | -10.66% | 1.2823 | 1.0701 | n/a | n/a | 13.1918 | 0 |

## Notes

- Shadow-only replay; no live config, feature flag, account state, or signal journal is changed.
- Uses cached historical A/B/C/D score rows, then routes residual sleeve capital through the cached capital-routing decision for that day.
- Default scenario sizing uses the deterministic R3/confidence/risk-gross upper-bound projection; pass --exact-optimizer for slow SLSQP spot checks.
- The candidate is a review target only; Phase III scaler replacement remains locked until human dry-run gates pass.
