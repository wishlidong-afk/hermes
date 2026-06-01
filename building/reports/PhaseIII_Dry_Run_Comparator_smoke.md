# Phase III Dry-run Comparator

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 5 / loaded 5
Date filter: `{'start': None, 'end': None, 'days': 5}`
Candidate: threshold `110.0000`, penalty `0.7000`
Live effect: `none`

## Human Gate Summary

| Gate | Count |
|---|---:|
| PASS | 3 |
| WARN | 2 |
| BLOCK | 0 |

| Metric | Value |
|---|---:|
| R3 violations | 0 |
| Max abs symbol delta | 0.0529 |
| Avg max abs symbol delta | 0.0492 |
| Max abs route leg delta | 0.0835 |
| Avg abs turnover delta | 0.0216 |
| Max abs turnover delta | 0.0592 |
| Avg old turnover | 0.2335 |
| Avg new turnover | 0.2509 |

## Risk Regime Counts

| Field | Counts |
|---|---|
| Binding | `{'VOL': 5}` |
| Corr regime | `{'ELEVATED': 5}` |

## Latest Daily Rows

| Date | Gate | Gross | Binding | Max Symbol Δ | Turnover Old/New/Δ | Top Target Deltas | Reasons |
|---|---|---:|---|---:|---:|---|---|
| 2026-05-22 | PASS | 0.7436 | VOL | 0.0489 | 1.0000/1.0000/0.0000 | FNGU:-0.0489, SOXL:-0.0050 | within dry-run tolerance |
| 2026-05-26 | WARN | 0.5873 | VOL | 0.0529 | 0.0937/0.1529/0.0592 | FNGU:-0.0529, SOXL:-0.0306 | scenario gross=0.5873 |
| 2026-05-27 | WARN | 0.6325 | VOL | 0.0512 | 0.0211/0.0442/0.0231 | FNGU:-0.0512, SOXL:-0.0207 | scenario gross=0.6325 |
| 2026-05-28 | PASS | 0.6828 | VOL | 0.0479 | 0.0341/0.0493/0.0152 | FNGU:-0.0479, SOXL:-0.0165 | within dry-run tolerance |
| 2026-05-29 | PASS | 0.6909 | VOL | 0.0449 | 0.0186/0.0079/-0.0107 | FNGU:-0.0449, SOXL:-0.0234 | within dry-run tolerance |

## Largest Difference Days

| Date | Gate | Max Symbol Δ | Turnover Δ | Top Target Deltas | Reasons |
|---|---|---:|---:|---|---|
| 2026-05-26 | WARN | 0.0529 | 0.0592 | FNGU:-0.0529, SOXL:-0.0306 | scenario gross=0.5873 |
| 2026-05-27 | WARN | 0.0512 | 0.0231 | FNGU:-0.0512, SOXL:-0.0207 | scenario gross=0.6325 |
| 2026-05-22 | PASS | 0.0489 | 0.0000 | FNGU:-0.0489, SOXL:-0.0050 | within dry-run tolerance |
| 2026-05-28 | PASS | 0.0479 | 0.0152 | FNGU:-0.0479, SOXL:-0.0165 | within dry-run tolerance |
| 2026-05-29 | PASS | 0.0449 | -0.0107 | FNGU:-0.0449, SOXL:-0.0234 | within dry-run tolerance |

## Notes

- Read-only dry run; no live config, feature flag, account state, or signal journal is changed.
- Old route weights come from cached backtest rows; new route weights use the Phase II review candidate and cached routing decision.
- BLOCK means invariant failure; WARN means human review required before any scaler migration; PASS is informational only.
- The candidate remains shadow-only until daily comparator, turnover review, and human gate all pass.
