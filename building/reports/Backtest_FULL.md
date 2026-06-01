# Hermes Full Backtest Report — Real-only (2025-02 to 2026-05, high-confidence)

Data manifest: `8797a3a7daab2899d589b510fed9bde0eb1406ec5177801f773a7f24d8a97138`
Requested window: `2025-02-20` to `2026-05-29`
Effective window: `2025-02-20` to `2026-05-29`
Trading dates: `320`

## Portfolio Metrics

| Metric | Value |
|---|---:|
| Final value | $159,041.37 |
| CAGR | 44.39% |
| Max drawdown | -10.43% |
| MaxDD start | `2025-10-08` |
| MaxDD end | `2025-12-18` |
| Sharpe | 1.7871 |
| Sortino | 2.2201 |
| Turnover | `63.915068` |

## Benchmarks

| Benchmark | Final | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|---:|
| SPY | $125,733.75 | 19.83% | -18.42% | 1.0744 |
| QQQ | $138,300.20 | 29.20% | -22.44% | 1.2490 |

## Signal Quality

| Symbol | Signals | Label rows | Hit rate | Avg fwd DD | Avg fwd ret |
|---|---:|---:|---:|---:|---:|
| FNGU | 169 | 169 | 61.54% | -15.85% | 7.15% |
| MSTR | 251 | 250 | 55.60% | -14.01% | -0.98% |
| SOXL | 198 | 198 | 53.54% | -16.78% | 21.52% |

## Walk Forward

Deflated Sharpe: `1.664361`

| Fold | Train | Test | Train N | Test N |
|---:|---|---|---:|---:|

## Coverage

- Effective start is the latest available inception among required risk symbols.
- This avoids fabricating returns before FNGU history is available in the current data source.

| Symbol | Start | End | Rows | Blocks Requested Start |
|---|---:|---:|---:|---:|
| FNGU | 2018-01-02 | 2026-05-29 | 2113 | False |
| MSTR | 2018-01-02 | 2026-05-29 | 2113 | False |
| SOXL | 2018-01-02 | 2026-05-29 | 2113 | False |

## Remaining Risk

- **Real-only report** (high-confidence window): no synthetic data in this range.
- This is the primary reference for engineering acceptance and calibration discussions.
- PCR/NAAIM/true BTC funding-basis-DVOL still pending; MSTR D-M3 uses BTC price proxy.
- Results suitable for engineering verification, not production sizing.
