# Execution Timing Sensitivity

Evidence status: **CURRENT_EXECUTION_EVIDENCE**
Source provenance: `CURRENT_SOURCE`
Headline scenario: `next_open`
Legacy parity: `MATCH`
Live effect: `none`

## Open-Price Coverage

- Total rows: `21430`
- Observed: `19247` (89.81%)
- Modeled synthetic/proxy: `2182`
- Missing: `1`
- Execution-required rows: `10033`
- Execution-required missing: `0`

| Leg | Observed | Modeled | Missing |
|---|---:|---:|---:|
| BOXX | 2142 | 1 | 0 |
| BRK.B | 2143 | 0 | 0 |
| BTC-USD | 2142 | 0 | 1 |
| DBMF | 1755 | 388 | 0 |
| FNGU | 350 | 1793 | 0 |
| IAU | 2143 | 0 | 0 |
| MSTR | 2143 | 0 | 0 |
| QQQ | 2143 | 0 | 0 |
| SOXL | 2143 | 0 | 0 |
| SOXX | 2143 | 0 | 0 |

## Scenarios

| Scenario | Role | Timing | Extra slip | Final | CAGR | MaxDD | Sharpe | Turnover | Base cost | Extra slip cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy_close | HISTORICAL_THEORETICAL_UPPER_BOUND | legacy_close | 0.0000 bps | $368,898.96 | 16.61% | -18.83% | 1.1206 | 237.6399 | $44,979.34 | $0.00 |
| next_open | PRIMARY_REALISTIC | next_open | 0.0000 bps | $342,336.84 | 15.58% | -20.83% | 1.0641 | 237.5348 | $41,528.26 | $0.00 |
| next_close | ONE_TRADING_DAY_DELAY | next_close | 0.0000 bps | $371,937.00 | 16.71% | -16.05% | 1.1283 | 237.5348 | $45,131.95 | $0.00 |
| next_open_stress | STRESS | next_open | 25.0000 bps | $188,918.54 | 7.77% | -26.36% | 0.5849 | 237.5348 | $29,415.52 | $73,538.79 |

## Provenance

- Mismatches: `none`
- Source artifact: `/Users/liweishi/Documents/github/hermes/building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- Source SHA256: `bbe1358690e1d08a5809b5b5d5a638f25b3b2c1fccb2bb9b883eb2a5eac8bb62`

## Notes

- legacy_close is retained only as the historical/theoretical upper-bound convention.
- next_open assigns signal-close-to-next-open gaps to the old holdings and executes the new target at the next open.
- next_close delays each close-generated target until the following close.
- Synthetic flat OHLC rows use an explicitly labeled log-midpoint open; observed and modeled coverage must be reviewed before headline use.
