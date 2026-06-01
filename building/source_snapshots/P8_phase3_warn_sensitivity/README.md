# P8 Phase III WARN Sensitivity Source Snapshot

**Date**: 2026-06-02  
**Scope**: read-only EXTREME_CORR threshold/penalty sensitivity for the Phase III WARN review.

## Files

| File | Purpose |
|---|---|
| `hermes_escape_top/scripts/phase3_warn_sensitivity.py` | Reuses one 252-day replay cache to evaluate 24 threshold/penalty dry-run human-gate scenarios. |
| `hermes_escape_top/tests/test_phase3_warn_sensitivity.py` | Unit tests for parsing, readiness states, review scoring, candidate picking, and duplicate-date price-panel rows. |

## Acceptance

| Check | Result |
|---|---:|
| scenarios | 24 |
| current candidate | 110 / 0.70 |
| P8 review candidate | 110 / 0.90 |
| current WARN 10d candidate-old avg | -0.29% |
| P8 candidate WARN 10d candidate-old avg | -0.13% |
| current max turnover delta | 0.4022 |
| P8 candidate max turnover delta | 0.2886 |
| P8 candidate R3 / BLOCK | 0 / 0 |
| package tests | 270 OK |
| golden tests | 11 OK |

## Live Effect

None. `110/0.90` is only a review candidate. It must pass full-window backtest sensitivity and exact optimizer spot-check before any migration pack is considered.
