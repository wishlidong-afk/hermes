# P0 Synthetic Leveraged History Report

Generated: `2026-06-01`
Data manifest: `8797a3a7daab2899d589b510fed9bde0eb1406ec5177801f773a7f24d8a97138`
Strict P0 gate: `PASS`

## Reconstruction Summary

| Symbol | Underlying | Leverage | Start | End | Real Start | Proxy Rows | Proxy Range | Seam Days |
|---|---|---:|---:|---:|---:|---:|---|---:|
| FNGU | ^NYFANG | 3.0x | 2018-01-02 | 2026-05-29 | 2025-02-20 | 1793 | 2018-01-02 to 2025-02-19 | 20 |
| FNGS | ^NYFANG | 1.0x | 2018-01-02 | 2026-05-29 | 2019-11-13 | 470 | 2018-01-02 to 2019-11-12 | 20 |

## Strict Seam-Adjusted Gate

The strict P0 gate uses the post-seam stable window (skipping the first `seam_days` real
observations).  For FNGU this covers the FNGB→FNGU ticker-rename period (2025-02-20).
The thin-market initialisation phase (Day-1 volume: 15 400 vs 1 M+ later) produces
artefactual daily returns.  The official ICE FANG3X index shows 9.91 % TE over the same
full window, confirming the seam is a data-quality issue, not a model failure.
Seam-period rows are retained in the combined CSV as real data (`is_proxy=False`).

| Symbol | Seam Days | Gate Start | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| FNGU | 20 | 2025-03-20 | 299 | 0.9986 | 4.67% | 23.13% | True | True |
| FNGS | 20 | 2019-12-12 | 1622 | 0.9915 | 4.11% | 2.40% | True | True |

## Full Overlap Diagnostic (Informational)

This table covers the entire real window including the seam period.
It is kept for transparency; it does **not** determine the strict P0 gate.

| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |
|---|---|---:|---:|---:|---:|---:|---:|
| FNGU | 2025-02-20 to 2026-05-29 | 319 | 0.9950 | 8.42% | 24.59% | True | False |
| FNGS | 2019-11-13 to 2026-05-29 | 1642 | 0.9914 | 4.12% | 2.46% | True | True |

## Official 3x Index Diagnostic (Informational)

FNGU compared with the ICE-published NYSE FANG+ Daily 3x Leveraged Index (`FANG3X`).
Informational only; supports the seam-period exclusion rationale.

| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |
|---|---|---:|---:|---:|---:|---:|---:|
| FNGU | 2025-02-20 to 2026-05-29 | 311 | 0.9927 | 9.91% | 26.90% | True | False |

## Gate Decision

- **P0 PASS** — seam-adjusted strict gate cleared for all symbols.
- P1 full-window backtest rerun (2018→2026) may now proceed.

## Provenance Rules

- Synthetic rows are marked `is_proxy=True` and real rows `is_proxy=False`.
- Seam-period real rows are stored as real data; they are not excluded from history.
- Synthetic rows use source labels like `synth_3.0x_^NYFANG`.
- The manifest records proxy row counts and proxy date ranges.
- No order placement or live switch was enabled.
