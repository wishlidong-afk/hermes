# Cost Robustness and Turnover Attribution

Evidence role: `SENSITIVITY_OF_RECORDED_BASELINE`
Authorization: `NO_CONFIG_FLIP`

## Cost Curve

| Extra slippage | CAGR | MaxDD | Sharpe | Final value | Extra cost |
|---:|---:|---:|---:|---:|---:|
| 0.0000 bps | 15.56% | -20.83% | 1.0636 | $342,742.36 | $0.00 |
| 5.0000 bps | 13.95% | -21.97% | 0.9678 | $304,258.02 | $19,416.51 |
| 10.0000 bps | 12.37% | -23.09% | 0.8720 | $270,087.12 | $36,196.35 |
| 25.0000 bps | 7.75% | -26.36% | 0.5840 | $188,892.56 | $73,787.29 |
| 50.0000 bps | 0.46% | -34.06% | 0.1052 | $104,028.14 | $107,535.07 |

## Turnover by Leg

Total turnover: `238.0632`; reconciled: `True`

| Leg | Turnover | Share |
|---|---:|---:|
| BOXX | 51.8683 | 21.79% |
| SOXL | 38.5142 | 16.18% |
| DBMF | 36.1235 | 15.17% |
| FNGU | 31.4091 | 13.19% |
| BRK.B | 28.2598 | 11.87% |
| IAU | 24.0823 | 10.12% |
| MSTR | 18.0130 | 7.57% |
| QQQ | 5.7837 | 2.43% |
| SOXX | 2.8069 | 1.18% |
| BTC-USD | 1.2024 | 0.51% |

## Turnover by Mechanism

| Mechanism | Turnover | Share |
|---|---:|---:|
| ROUTE_SET_CHANGE | 166.7296 | 70.04% |
| WEIGHT_REBALANCE | 70.3336 | 29.54% |
| INITIAL_ALLOCATION | 1.0000 | 0.42% |

## Largest Route Transitions

| From | To | Mechanism | Count | Turnover |
|---|---|---|---:|---:|
| BOXX+DBMF+FNGU+IAU+MSTR+SOXL | BOXX+DBMF+FNGU+IAU+MSTR+SOXL | WEIGHT_REBALANCE | 191 | 28.6353 |
| BOXX+DBMF+FNGU+IAU+SOXL | BOXX+DBMF+FNGU+IAU+SOXL | WEIGHT_REBALANCE | 166 | 19.9845 |
| BOXX+FNGU+MSTR+SOXL | BOXX+DBMF+FNGU+IAU+MSTR+SOXL | ROUTE_SET_CHANGE | 21 | 8.2809 |
| BOXX+DBMF+FNGU+IAU+MSTR+SOXL | BOXX+BRK.B+FNGU+MSTR+QQQ+SOXL | ROUTE_SET_CHANGE | 10 | 7.8540 |
| BOXX+DBMF+FNGU+IAU+MSTR+SOXL | BOXX+FNGU+MSTR+SOXL | ROUTE_SET_CHANGE | 16 | 6.8660 |
| BOXX+FNGU+MSTR+SOXL | BOXX+FNGU+MSTR+SOXL | WEIGHT_REBALANCE | 124 | 6.3839 |
| BOXX+BRK.B+FNGU+MSTR+QQQ+SOXL | BOXX+DBMF+FNGU+IAU+MSTR+SOXL | ROUTE_SET_CHANGE | 8 | 6.0689 |
| BOXX+BRK.B+FNGU+MSTR | BOXX+DBMF+FNGU+IAU+MSTR | ROUTE_SET_CHANGE | 6 | 5.1755 |
| BOXX+DBMF+FNGU+IAU+MSTR+SOXL | BOXX+BRK.B+FNGU+MSTR+SOXL | ROUTE_SET_CHANGE | 9 | 5.1274 |
| BOXX+DBMF+FNGU+IAU+MSTR+SOXL | BOXX+DBMF+FNGU+IAU+SOXL | ROUTE_SET_CHANGE | 21 | 5.0876 |

## Notes

- All rows reuse the recorded baseline decisions and next-open execution prices.
- Extra slippage is charged on absolute turnover in addition to configured base costs.
- This report is sensitivity evidence only and does not authorize a config or feature change.
