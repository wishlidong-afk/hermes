# MSTR On-Chain Offline Lab — 2026-06-11

Scope: T16 offline research only. This report does not change production scoring, config, routing, or gates.

## Data Boundary

- Window: `2018-01-01` to `2026-05-29`
- Coin Metrics rows: 3071 raw; 2113 aligned MSTR trading days
- Raw Coin Metrics date range: `2018-01-01` to `2026-05-29`
- PIT alignment: Coin Metrics date + 1 calendar day, then forward-filled to MSTR trading days
- Approved fields: `CapMVRVCur, FlowInExUSD, FlowOutExUSD, SplyExUSD, PriceUSD, CapMrktCurUSD, SplyCur`
- Not implemented because current community probes returned 403/unsupported: `CapRealUSD, SOPR, SOPRSth155d, SOPRLth155d, MCRC, RCTC, RevAllTimeUSD`

## D-Module Structure Decision

MSTR D already reaches the 20-point cap: D1 5 + D2 3 + D3 4 + D4 4 + D_M3 BTC proxy 4. Any on-chain survivor must replace or split the existing 4-point `D_M3_BTC_VOLATILITY_PROXY` budget; it must not expand the D cap and must not add another independent 4-point block. Preferred T19 design, if any candidate survives: `D_M3_BTC_RISK_COMPOSITE` remains max 4, with price-volatility stress and on-chain stress blended inside that same budget.

## Labeled Tops

Labels are offline outcomes: MSTR near a 20-trading-day peak followed by at least a 30% drawdown within 60 trading days, deduplicated by 45 trading days.

`2020-02-05`, `2021-02-09`, `2021-11-08`, `2022-03-29`, `2022-08-12`, `2023-02-15`, `2023-07-13`, `2024-01-02`, `2024-03-27`, `2024-07-22`, `2024-11-20`, `2025-07-16`, `2025-10-06`, `2026-01-14`

## Candidate Screen

| Candidate | Threshold | Hit rate vs tops | Median lead | Precision | Fire rate | Episodes | Max abs corr | Top correlated existing factor | Survivor? |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `CM_MVRV_HEAT` | 95.0 | 35.7% | 70.0d | 57.9% | 11.9% | 19 | 0.777 | `D:D4_RADAR_CONFIRMATION` | NO |
| `CM_EXCHANGE_INFLOW_PRESSURE` | 2.0 | 71.4% | 70.0d | 40.0% | 4.1% | 35 | 0.086 | `B:B4_CBOE_OPTIONS_STRESS` | YES |
| `CM_EXCHANGE_NETFLOW_PRESSURE` | 2.0 | 78.6% | 64.0d | 45.2% | 2.9% | 31 | 0.058 | `C:C8_DISTRIBUTION_PRESSURE` | YES |
| `CM_EXCHANGE_SUPPLY_HEAT` | 95.0 | 35.7% | 84.0d | 39.3% | 19.3% | 28 | 0.255 | `D:D_M3_BTC_VOLATILITY_PROXY` | NO |
| `CM_COMPOSITE_ONCHAIN_HEAT` | 90.0 | 21.4% | 61.0d | 60.0% | 1.8% | 10 | 0.404 | `D:D2_ASSET_MA220_BREAK` | NO |

## Lead-Time Detail

- `CM_MVRV_HEAT`: 2020-02-05:miss, 2021-02-09:90, 2021-11-08:miss, 2022-03-29:miss, 2022-08-12:miss, 2023-02-15:miss, 2023-07-13:70, 2024-01-02:70, 2024-03-27:85, 2024-07-22:miss, 2024-11-20:8, 2025-07-16:miss, 2025-10-06:miss, 2026-01-14:miss
- `CM_EXCHANGE_INFLOW_PRESSURE`: 2020-02-05:miss, 2021-02-09:74, 2021-11-08:miss, 2022-03-29:63, 2022-08-12:59, 2023-02-15:miss, 2023-07-13:31, 2024-01-02:70, 2024-03-27:77, 2024-07-22:5, 2024-11-20:70, 2025-07-16:miss, 2025-10-06:82, 2026-01-14:70
- `CM_EXCHANGE_NETFLOW_PRESSURE`: 2020-02-05:64, 2021-02-09:74, 2021-11-08:73, 2022-03-29:miss, 2022-08-12:59, 2023-02-15:miss, 2023-07-13:miss, 2024-01-02:60, 2024-03-27:77, 2024-07-22:61, 2024-11-20:14, 2025-07-16:1, 2025-10-06:83, 2026-01-14:70
- `CM_EXCHANGE_SUPPLY_HEAT`: 2020-02-05:90, 2021-02-09:miss, 2021-11-08:84, 2022-03-29:miss, 2022-08-12:miss, 2023-02-15:miss, 2023-07-13:miss, 2024-01-02:miss, 2024-03-27:71, 2024-07-22:77, 2024-11-20:85, 2025-07-16:miss, 2025-10-06:miss, 2026-01-14:miss
- `CM_COMPOSITE_ONCHAIN_HEAT`: 2020-02-05:miss, 2021-02-09:miss, 2021-11-08:miss, 2022-03-29:miss, 2022-08-12:miss, 2023-02-15:miss, 2023-07-13:miss, 2024-01-02:47, 2024-03-27:77, 2024-07-22:61, 2024-11-20:miss, 2025-07-16:miss, 2025-10-06:miss, 2026-01-14:miss

## Offline Conclusion

Offline survivors for T19 queue: `CM_EXCHANGE_INFLOW_PRESSURE`, `CM_EXCHANGE_NETFLOW_PRESSURE`. These are research candidates only; each still gets exactly one in-system gate after A confirms the backtest window is free.

## Config Keys For Agent A

- If a future survivor is approved for shadow wiring: `features.data_onchain_mstr=false` (default OFF; comment: Coin Metrics/approved on-chain MSTR lab feed, PIT shifted one day, no live scoring until gate passes).
