# Execution Timing Sensitivity

Evidence status: **CURRENT_EXECUTION_EVIDENCE**
Source provenance: `CURRENT_SOURCE`
Headline scenario: `next_open`
Legacy parity: `MATCH`
Live effect: `none`

## Open-Price Coverage

- Total rows: `21480`
- Observed: `19297` (89.84%)
- Modeled synthetic/proxy: `2182`
- Missing: `1`
- Execution-required rows: `10053`
- Execution-required missing: `0`

| Leg | Observed | Modeled | Missing |
|---|---:|---:|---:|
| BOXX | 2147 | 1 | 0 |
| BRK.B | 2148 | 0 | 0 |
| BTC-USD | 2147 | 0 | 1 |
| DBMF | 1760 | 388 | 0 |
| FNGU | 355 | 1793 | 0 |
| IAU | 2148 | 0 | 0 |
| MSTR | 2148 | 0 | 0 |
| QQQ | 2148 | 0 | 0 |
| SOXL | 2148 | 0 | 0 |
| SOXX | 2148 | 0 | 0 |

## Scenarios

| Scenario | Role | Timing | Extra slip | Final | CAGR | MaxDD | Sharpe | Turnover | Base cost | Extra slip cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy_close | HISTORICAL_THEORETICAL_UPPER_BOUND | legacy_close | 0.0000 bps | $367,569.99 | 16.52% | -18.83% | 1.1161 | 238.2941 | $45,219.31 | $0.00 |
| next_open | PRIMARY_REALISTIC | next_open | 0.0000 bps | $342,742.36 | 15.56% | -20.83% | 1.0636 | 238.0632 | $41,708.47 | $0.00 |
| next_close | ONE_TRADING_DAY_DELAY | next_close | 0.0000 bps | $372,483.35 | 16.69% | -16.05% | 1.1279 | 238.0632 | $45,328.17 | $0.00 |
| next_open_stress | STRESS | next_open | 25.0000 bps | $188,892.56 | 7.75% | -26.36% | 0.5840 | 238.0632 | $29,514.92 | $73,787.29 |

## Provenance

- Mismatches: `none`
- Source artifact: `building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz`
- Source SHA256: `84ba67caee68c090a15b48821aa49cdfdfff45dc882cea811681a8446dd2ed3e`

## Notes

- legacy_close is retained only as the historical/theoretical upper-bound convention.
- next_open assigns signal-close-to-next-open gaps to the old holdings and executes the new target at the next open.
- next_close delays each close-generated target until the following close.
- Synthetic flat OHLC rows use an explicitly labeled log-midpoint open; observed and modeled coverage must be reviewed before headline use.
