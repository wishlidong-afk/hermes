# Phase II Full Backtest Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 125 / loaded 125
Live effect: `none`
Exact optimizer: `True`
Date filter: `{'start': '2022-01-03', 'end': '2022-07-01'}`

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
| Penalty | 0.7000 |
| Hit share | 0.00% |
| Avg gross | 1.0000 |
| Min gross | 1.0000 |
| Final value | $96,392.78 |
| CAGR | -7.01% |
| MaxDD | -6.73% |
| Sharpe | -1.0068 |
| DSR | -1.5919 |
| Turnover | 2.0904 |
| Fixed OOS below-median share | n/a |
| Mean OOS rank | n/a |
| R3 violations | 0 |

## Walk Forward / PBO

- Train-greedy PBO: `n/a`
- Note: n/a

## Scenario Grid

| Threshold | Penalty | Hit Share | Avg Gross | Final | CAGR | MaxDD | Sharpe | DSR | Fixed PBO | Mean Rank | Turnover | R3 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 110.0000 | 0.7000 | 0.00% | 1.0000 | $96,392.78 | -7.01% | -6.73% | -1.0068 | -1.5919 | n/a | n/a | 2.0904 | 0 |

## Notes

- Shadow-only replay; no live config, feature flag, account state, or signal journal is changed.
- Uses cached historical A/B/C/D score rows, then routes residual sleeve capital through the cached capital-routing decision for that day.
- Default scenario sizing uses the deterministic R3/confidence/risk-gross upper-bound projection; pass --exact-optimizer for slow SLSQP spot checks.
- The candidate is a review target only; Phase III scaler replacement remains locked until human dry-run gates pass.
