# Cost Robustness and Turnover Attribution

Evidence role: `SENSITIVITY_OF_RECORDED_BASELINE`
Authorization: `NO_CONFIG_FLIP`

## Cost Curve

| Extra slippage | CAGR | MaxDD | Sharpe | Final value | Extra cost |
|---:|---:|---:|---:|---:|---:|
| 0.0000 bps | 15.46% | -20.83% | 1.0578 | $340,054.44 | $0.00 |
| 5.0000 bps | 13.86% | -21.97% | 0.9620 | $301,892.43 | $19,395.96 |
| 10.0000 bps | 12.28% | -23.09% | 0.8662 | $268,005.42 | $36,159.86 |
| 25.0000 bps | 7.66% | -26.36% | 0.5783 | $187,474.90 | $73,723.49 |
| 50.0000 bps | 0.38% | -34.06% | 0.0995 | $103,282.51 | $107,464.77 |

## Turnover by Leg

Total turnover: `237.9273`; reconciled: `True`

| Leg | Turnover | Share |
|---|---:|---:|
| BOXX | 51.8249 | 21.78% |
| SOXL | 38.5142 | 16.19% |
| DBMF | 36.0635 | 15.16% |
| FNGU | 31.4166 | 13.20% |
| BRK.B | 28.2598 | 11.88% |
| IAU | 24.0423 | 10.10% |
| MSTR | 18.0130 | 7.57% |
| QQQ | 5.7837 | 2.43% |
| SOXX | 2.8069 | 1.18% |
| BTC-USD | 1.2024 | 0.51% |

## Turnover by Mechanism

| Mechanism | Turnover | Share |
|---|---:|---:|
| ROUTE_SET_CHANGE | 166.5886 | 70.02% |
| WEIGHT_REBALANCE | 70.3387 | 29.56% |
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
