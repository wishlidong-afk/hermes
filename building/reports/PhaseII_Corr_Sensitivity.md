# Phase II Corr Sensitivity

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/PhaseII_Shadow_Compare.json`
Rows evaluated: 252
Live effect: `none`

## Review Candidate

| Field | Value |
|---|---:|
| Threshold | 110.0000 |
| Penalty | 0.7000 |
| Hit share | 40.48% |
| Avg gross | 0.8273 |
| Min gross | 0.5770 |

## Scenario Grid

| Threshold | Penalty | Hit Share | Avg Gross | Min Gross | P10 Gross | P50 Gross | Avg Gross Delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 92.0000 | 0.7000 | 78.57% | 0.7229 | 0.4111 | 0.5796 | 0.7000 | -0.2771 |
| 92.0000 | 0.8000 | 78.57% | 0.7975 | 0.4699 | 0.6524 | 0.8000 | -0.2025 |
| 92.0000 | 0.9000 | 78.57% | 0.8722 | 0.5286 | 0.7328 | 0.9000 | -0.1278 |
| 100.0000 | 0.7000 | 59.13% | 0.7770 | 0.4111 | 0.6091 | 0.7000 | -0.2230 |
| 100.0000 | 0.8000 | 59.13% | 0.8336 | 0.4699 | 0.6858 | 0.8000 | -0.1664 |
| 100.0000 | 0.9000 | 59.13% | 0.8902 | 0.5286 | 0.7395 | 0.9000 | -0.1098 |
| 110.0000 | 0.7000 | 40.48% | 0.8273 | 0.5770 | 0.6740 | 0.7604 | -0.1727 |
| 110.0000 | 0.8000 | 40.48% | 0.8671 | 0.5770 | 0.7307 | 0.8000 | -0.1329 |
| 110.0000 | 0.9000 | 40.48% | 0.9069 | 0.5770 | 0.7604 | 0.9000 | -0.0931 |
| 120.0000 | 0.7000 | 28.97% | 0.8609 | 0.5770 | 0.6858 | 0.9335 | -0.1391 |
| 120.0000 | 0.8000 | 28.97% | 0.8895 | 0.5770 | 0.7436 | 0.9335 | -0.1105 |
| 120.0000 | 0.9000 | 28.97% | 0.9182 | 0.5770 | 0.7715 | 0.9335 | -0.0818 |
| 130.0000 | 0.7000 | 19.84% | 0.8876 | 0.5770 | 0.7000 | 1.0000 | -0.1124 |
| 130.0000 | 0.8000 | 19.84% | 0.9073 | 0.5770 | 0.7596 | 1.0000 | -0.0927 |
| 130.0000 | 0.9000 | 19.84% | 0.9271 | 0.5770 | 0.7823 | 1.0000 | -0.0729 |
| 140.0000 | 0.7000 | 12.70% | 0.9088 | 0.5770 | 0.7000 | 1.0000 | -0.0912 |
| 140.0000 | 0.8000 | 12.70% | 0.9215 | 0.5770 | 0.7604 | 1.0000 | -0.0785 |
| 140.0000 | 0.9000 | 12.70% | 0.9341 | 0.5770 | 0.8051 | 1.0000 | -0.0659 |
| 150.0000 | 0.7000 | 10.32% | 0.9158 | 0.5770 | 0.7000 | 1.0000 | -0.0842 |
| 150.0000 | 0.8000 | 10.32% | 0.9261 | 0.5770 | 0.8000 | 1.0000 | -0.0739 |
| 150.0000 | 0.9000 | 10.32% | 0.9365 | 0.5770 | 0.8051 | 1.0000 | -0.0635 |

## Interpretation

- Current base 92/0.70 is intentionally defensive but hit-rate is high in the 252-day replay.
- A higher threshold delays the EXTREME_CORR penalty until downside correlation is clearly above ordinary correlation.
- A higher penalty keeps the signal but reduces forced gross shrinkage.
- Do not promote any scenario to live until it passes full backtest, walk-forward, and Phase III migration gates.

## Notes

- Reprices only the correlation-regime penalty layer from the shadow artifact.
- Does not change production/live config.
- Candidate is a review target, not an automatic parameter change.
