# P0 Synthetic Leveraged History Report

Generated: `2026-06-01`
Data manifest: `80d347e87027cc45a6f6355dcbab46781c91f9e79601569bdb1a8be1ee28a213`
Strict P0 gate: `NOT PASSED`

## Reconstruction Summary

| Symbol | Underlying | Leverage | Start | End | Real Start | Proxy Rows | Proxy Range |
|---|---|---:|---:|---:|---:|---:|---|
| FNGU | ^NYFANG | 3.0x | 2018-01-02 | 2026-05-29 | 2025-02-20 | 1793 | 2018-01-02 to 2025-02-19 |
| FNGS | ^NYFANG | 1.0x | 2018-01-02 | 2026-05-29 | 2019-11-13 | 470 | 2018-01-02 to 2019-11-12 |

## Strict Overlap Validation

| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |
|---|---|---:|---:|---:|---:|---:|---:|
| FNGU | 2025-02-20 to 2026-05-29 | 319 | 0.9950 | 8.42% | 24.59% | True | False |
| FNGS | 2019-11-13 to 2026-05-29 | 1642 | 0.9914 | 4.12% | 2.46% | True | True |

## Stable Window Diagnostic

This secondary diagnostic skips the first 20 real observations to reveal whether failures are concentrated at the vendor seam. It is diagnostic only and does not override the strict P0 gate.

| Symbol | Overlap | Obs | Return Corr | Annual TE | Max Abs Dev | Corr Gate | TE Gate |
|---|---|---:|---:|---:|---:|---:|---:|
| FNGU | 2025-03-20 to 2026-05-29 | 299 | 0.9986 | 4.67% | 23.13% | True | True |
| FNGS | 2019-12-12 to 2026-05-29 | 1622 | 0.9915 | 4.11% | 2.40% | True | True |

## Gate Decision

- P0 code/data plumbing is built, but strict acceptance is not fully passed; do not start P1 calibration yet.
- FNGU is expected to be the gating item if annual tracking error remains above 5%.

## Provenance Rules

- Synthetic rows are marked `is_proxy=True` and real rows `is_proxy=False`.
- Synthetic rows use source labels like `synth_3.0x_^NYFANG`.
- The manifest records proxy row counts and proxy date ranges.
- No order placement or live switch was enabled.
