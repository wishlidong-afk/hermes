# Execution Timing Sensitivity

Status: **STALE** pending a current-code/current-live-config rebuild.

Evidence status: **CURRENT_EXECUTION_EVIDENCE**
Source provenance: `CURRENT_SOURCE`
Headline scenario: `next_open`
Legacy parity: `MATCH`
Live effect: `none`

## Open-Price Coverage

- Total rows: `21410`
- Observed: `19228` (89.81%)
- Modeled synthetic/proxy: `2182`
- Missing: `0`

| Leg | Observed | Modeled | Missing |
|---|---:|---:|---:|
| BOXX | 2140 | 1 | 0 |
| BRK.B | 2141 | 0 | 0 |
| BTC-USD | 2141 | 0 | 0 |
| DBMF | 1753 | 388 | 0 |
| FNGU | 348 | 1793 | 0 |
| IAU | 2141 | 0 | 0 |
| MSTR | 2141 | 0 | 0 |
| QQQ | 2141 | 0 | 0 |
| SOXL | 2141 | 0 | 0 |
| SOXX | 2141 | 0 | 0 |

## Scenarios

| Scenario | Role | Timing | Extra slip | Final | CAGR | MaxDD | Sharpe | Turnover | Base cost | Extra slip cost |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy_close | HISTORICAL_THEORETICAL_UPPER_BOUND | legacy_close | 0.0000 bps | $382,473.48 | 17.13% | -16.76% | 1.1350 | 235.7354 | $46,030.55 | $0.00 |
| next_open | PRIMARY_REALISTIC | next_open | 0.0000 bps | $350,116.13 | 15.90% | -19.07% | 1.0695 | 235.7203 | $41,875.02 | $0.00 |
| next_close | ONE_TRADING_DAY_DELAY | next_close | 0.0000 bps | $395,936.73 | 17.59% | -16.80% | 1.1642 | 235.7203 | $46,015.22 | $0.00 |
| next_open_stress | STRESS | next_open | 25.0000 bps | $194,090.70 | 8.12% | -24.78% | 0.6008 | 235.7203 | $29,751.56 | $74,378.90 |

## Provenance

- Mismatches: `none`
- Source artifact: `/Users/liweishi/Documents/github/hermes/building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- Source SHA256: `0e62bfee884ca8c3d1524bf47b7648e791fde31e4f10f103d408848220d5847a`

## Notes

- legacy_close is retained only as the historical/theoretical upper-bound convention.
- next_open assigns signal-close-to-next-open gaps to the old holdings and executes the new target at the next open.
- next_close delays each close-generated target until the following close.
- Synthetic flat OHLC rows use an explicitly labeled log-midpoint open; observed and modeled coverage must be reviewed before headline use.
