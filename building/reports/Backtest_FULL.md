# Hermes Full Backtest Report

Data manifest: `594e08958dde96fd6ce97c3c04fb91c0a0deb2480f94ec2f765f7d7cb89f524d`
Requested window: `2018-01-01` to `2026-05-29`
Effective window: `2025-02-20` to `2026-05-29`
Trading dates: `320`

## Portfolio Metrics

| Metric | Value |
|---|---:|
| Final value | $148,626.34 |
| CAGR | 36.87% |
| Max drawdown | -11.43% |
| MaxDD start | `2025-10-06` |
| MaxDD end | `2025-12-18` |
| Sharpe | 1.7050 |
| Sortino | 2.2471 |
| Turnover | `73.119932` |

## Benchmarks

| Benchmark | Final | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|---:|
| SPY | $125,733.75 | 19.83% | -18.42% | 1.0744 |
| QQQ | $138,300.20 | 29.20% | -22.44% | 1.2490 |

## Signal Quality

| Symbol | Signals | Label rows | Hit rate | Avg fwd DD | Avg fwd ret |
|---|---:|---:|---:|---:|---:|
| FNGU | 292 | 292 | 42.12% | -11.80% | 6.21% |
| MSTR | 251 | 250 | 55.60% | -14.01% | -0.98% |
| SOXL | 198 | 198 | 53.54% | -16.78% | 21.52% |

## Walk Forward

Deflated Sharpe: `1.595024`

| Fold | Train | Test | Train N | Test N |
|---:|---|---|---:|---:|

## Coverage

- Effective start is the latest available inception among required risk symbols.
- This avoids fabricating returns before FNGU history is available in the current data source.

| Symbol | Start | End | Rows | Blocks Requested Start |
|---|---:|---:|---:|---:|
| FNGU | 2025-02-20 | 2026-05-29 | 320 | True |
| MSTR | 2018-01-02 | 2026-05-29 | 2113 | False |
| SOXL | 2018-01-02 | 2026-05-29 | 2113 | False |

## Remaining Risk

- This report is coverage-constrained by the current FNGU history source.
- PCR/NAAIM/true BTC funding-basis-DVOL are still pending; current MSTR D-M3 is a BTC price proxy.
- Results are suitable for engineering验收, not final capital calibration.
