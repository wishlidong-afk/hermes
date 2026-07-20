# Cost Robustness and Turnover Attribution

Evidence role: `SENSITIVITY_OF_RECORDED_BASELINE`
Authorization: `NO_CONFIG_FLIP`

## Cost Curve

| Extra slippage | CAGR | MaxDD | Sharpe | Final value | Extra cost |
|---:|---:|---:|---:|---:|---:|
| 0.0000 bps | 15.58% | -20.83% | 1.0641 | $342,336.84 | $0.00 |
| 5.0000 bps | 13.97% | -21.97% | 0.9685 | $303,978.35 | $19,336.50 |
| 10.0000 bps | 12.39% | -23.09% | 0.8726 | $269,910.17 | $36,054.29 |
| 25.0000 bps | 7.77% | -26.36% | 0.5849 | $188,918.54 | $73,538.79 |
| 50.0000 bps | 0.48% | -34.06% | 0.1065 | $104,180.07 | $107,261.13 |

## Turnover by Leg

Total turnover: `237.5348`; reconciled: `True`

| Leg | Turnover | Share |
|---|---:|---:|
| BOXX | 51.7197 | 21.77% |
| SOXL | 38.5142 | 16.21% |
| DBMF | 35.9861 | 15.15% |
| FNGU | 31.2582 | 13.16% |
| BRK.B | 28.2598 | 11.90% |
| IAU | 23.9908 | 10.10% |
| MSTR | 18.0130 | 7.58% |
| QQQ | 5.7837 | 2.43% |
| SOXX | 2.8069 | 1.18% |
| BTC-USD | 1.2024 | 0.51% |

## Turnover by Mechanism

| Mechanism | Turnover | Share |
|---|---:|---:|
| ROUTE_SET_CHANGE | 166.5886 | 70.13% |
| WEIGHT_REBALANCE | 69.9462 | 29.45% |
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
