# Execution Timing Sensitivity

Evidence status: **CURRENT_EXECUTION_EVIDENCE**
Source provenance: `CURRENT_SOURCE`
Headline scenario: `next_open`
Legacy parity: `MATCH`
Live effect: `none`

## Open-Price Coverage

- Total rows: `21460`
- Observed: `19278` (89.83%)
- Modeled synthetic/proxy: `2182`
- Missing: `0`
- Execution-required rows: `10045`
- Execution-required missing: `0`

| Leg | Observed | Modeled | Missing |
|---|---:|---:|---:|
| BOXX | 2145 | 1 | 0 |
| BRK.B | 2146 | 0 | 0 |
| BTC-USD | 2146 | 0 | 0 |
| DBMF | 1758 | 388 | 0 |
| FNGU | 353 | 1793 | 0 |
| IAU | 2146 | 0 | 0 |
| MSTR | 2146 | 0 | 0 |
| QQQ | 2146 | 0 | 0 |
| SOXL | 2146 | 0 | 0 |
| SOXX | 2146 | 0 | 0 |

## Scenarios

| Scenario | Role | Timing | Extra slip | Final | CAGR | MaxDD | Sharpe | Turnover | Base cost | Extra slip cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy_close | HISTORICAL_THEORETICAL_UPPER_BOUND | legacy_close | 0.0000 bps | $366,178.38 | 16.49% | -18.83% | 1.1136 | 238.0568 | $45,132.96 | $0.00 |
| next_open | PRIMARY_REALISTIC | next_open | 0.0000 bps | $340,054.44 | 15.46% | -20.83% | 1.0578 | 237.9273 | $41,662.18 | $0.00 |
| next_close | ONE_TRADING_DAY_DELAY | next_close | 0.0000 bps | $368,296.32 | 16.55% | -16.05% | 1.1193 | 237.9273 | $45,277.24 | $0.00 |
| next_open_stress | STRESS | next_open | 25.0000 bps | $187,474.90 | 7.66% | -26.36% | 0.5783 | 237.9273 | $29,489.39 | $73,723.49 |

## Provenance

- Mismatches: `none`
- Source artifact: `building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz`
- Source SHA256: `36183fceecae60fffc35d53a171d312d88e15520d45104c4b16e551565262a20`

## Notes

- legacy_close is retained only as the historical/theoretical upper-bound convention.
- next_open assigns signal-close-to-next-open gaps to the old holdings and executes the new target at the next open.
- next_close delays each close-generated target until the following close.
- Synthetic flat OHLC rows use an explicitly labeled log-midpoint open; observed and modeled coverage must be reviewed before headline use.
