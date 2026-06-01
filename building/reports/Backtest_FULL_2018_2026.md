# Hermes Full Backtest Report — Full-proxy (2018-01 to 2026-05, contains proxy segment)

Data manifest: `8797a3a7daab2899d589b510fed9bde0eb1406ec5177801f773a7f24d8a97138`
Requested window: `2018-01-01` to `2026-05-29`
Effective window: `2018-01-02` to `2026-05-29`
Trading dates: `2113`

## Portfolio Metrics

| Metric | Value |
|---|---:|
| Final value | $403,631.36 |
| CAGR | 18.13% |
| Max drawdown | -27.60% |
| MaxDD start | `2021-11-08` |
| MaxDD end | `2023-05-12` |
| Sharpe | 0.8818 |
| Sortino | 1.1155 |
| Turnover | `326.682483` |

## Benchmarks

| Benchmark | Final | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|---:|
| SPY | $281,459.99 | 13.14% | -34.10% | 0.7361 |
| QQQ | $465,840.10 | 20.15% | -36.48% | 0.8906 |

## Signal Quality

| Symbol | Signals | Label rows | Hit rate | Avg fwd DD | Avg fwd ret |
|---|---:|---:|---:|---:|---:|
| FNGU | 1173 | 1173 | 55.41% | -15.62% | 5.72% |
| MSTR | 1449 | 1448 | 40.95% | -11.57% | 4.29% |
| SOXL | 1350 | 1350 | 56.67% | -16.13% | 6.64% |

## Walk Forward

Deflated Sharpe: `0.774092`

| Fold | Train | Test | Train N | Test N |
|---:|---|---|---:|---:|
| 1 | 2018-01-02 to 2019-12-03 | 2020-01-03 to 2020-07-02 | 484 | 126 |
| 2 | 2018-07-02 to 2020-06-04 | 2020-07-06 to 2020-12-31 | 485 | 126 |
| 3 | 2019-01-02 to 2020-12-02 | 2021-01-04 to 2021-07-02 | 485 | 126 |
| 4 | 2019-07-02 to 2021-06-04 | 2021-07-06 to 2022-01-03 | 486 | 127 |
| 5 | 2020-01-02 to 2021-12-02 | 2022-01-03 to 2022-07-01 | 485 | 125 |
| 6 | 2020-07-02 to 2022-06-02 | 2022-07-05 to 2023-01-03 | 484 | 127 |
| 7 | 2021-01-04 to 2022-12-01 | 2023-01-03 to 2023-07-03 | 483 | 125 |
| 8 | 2021-07-02 to 2023-06-01 | 2023-07-03 to 2024-01-03 | 482 | 128 |
| 9 | 2022-01-03 to 2023-12-01 | 2024-01-03 to 2024-07-03 | 482 | 126 |
| 10 | 2022-07-05 to 2024-06-03 | 2024-07-03 to 2025-01-03 | 482 | 128 |
| 11 | 2023-01-03 to 2024-12-03 | 2025-01-03 to 2025-07-03 | 483 | 124 |
| 12 | 2023-07-03 to 2025-06-03 | 2025-07-03 to 2026-01-02 | 482 | 127 |
| 13 | 2024-01-02 to 2025-12-03 | 2026-01-05 to 2026-05-29 | 483 | 101 |

## Coverage

- Effective start is the latest available inception among required risk symbols.
- This avoids fabricating returns before FNGU history is available in the current data source.

| Symbol | Start | End | Rows | Blocks Requested Start |
|---|---:|---:|---:|---:|
| FNGU | 2018-01-02 | 2026-05-29 | 2113 | False |
| MSTR | 2018-01-02 | 2026-05-29 | 2113 | False |
| SOXL | 2018-01-02 | 2026-05-29 | 2113 | False |

## Remaining Risk

- **Full-window report**: FNGU/SOXL pre-inception rows are synthetic (is_proxy=True); seam-adjusted P0 gate passed.
- During proxy period: hard valves triggered on real market signals (2018 Q4/2020/2022 bear markets) → BOXX/DBMF routing.
- CAGR/MaxDD reflect combined proxy+real behaviour; treat as indicative, not final calibration.
- PCR/NAAIM/true BTC funding-basis-DVOL still pending; MSTR D-M3 uses BTC price proxy.
- Results suitable for engineering verification, not production sizing.
