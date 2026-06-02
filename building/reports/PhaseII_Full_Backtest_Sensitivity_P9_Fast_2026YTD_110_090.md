# Phase II Full Backtest Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 101 / loaded 101
Live effect: `none`
Exact optimizer: `False`
Date filter: `{'start': '2026-01-05', 'end': '2026-05-29'}`

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
| Hit share | 41.58% |
| Avg gross | 0.8923 |
| Min gross | 0.5873 |
| Final value | $134,000.54 |
| CAGR | 109.61% |
| MaxDD | -8.64% |
| Sharpe | 3.5696 |
| DSR | 3.4936 |
| Turnover | 26.2505 |
| Fixed OOS below-median share | n/a |
| Mean OOS rank | n/a |
| R3 violations | 0 |

## Walk Forward / PBO

- Train-greedy PBO: `n/a`
- Note: n/a

## Scenario Grid

| Threshold | Penalty | Hit Share | Avg Gross | Final | CAGR | MaxDD | Sharpe | DSR | Fixed PBO | Mean Rank | Turnover | R3 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 110.0000 | 0.9000 | 41.58% | 0.8923 | $134,000.54 | 109.61% | -8.64% | 3.5696 | 3.4936 | n/a | n/a | 26.2505 | 0 |

## Notes

- Shadow-only replay; no live config, feature flag, account state, or signal journal is changed.
- Uses cached historical A/B/C/D score rows, then routes residual sleeve capital through the cached capital-routing decision for that day.
- Default scenario sizing uses the deterministic R3/confidence/risk-gross upper-bound projection; pass --exact-optimizer for slow SLSQP spot checks.
- The candidate is a review target only; Phase III scaler replacement remains locked until human dry-run gates pass.
