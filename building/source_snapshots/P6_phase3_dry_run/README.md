# P6 Phase III Dry-run Comparator Source Snapshot

**Date**: 2026-06-02  
**Scope**: read-only old-vs-new dry-run comparator for the Phase II review candidate `threshold=110 / penalty=0.70`.

## Files

| File | Purpose |
|---|---|
| `hermes_escape_top/scripts/phase3_dry_run_compare.py` | Replays cached backtest rows and compares old route chain vs candidate route chain. |
| `hermes_escape_top/tests/test_phase3_dry_run_compare.py` | Unit coverage for target extraction, route normalization, turnover, deltas, and PASS/WARN/BLOCK gates. |

## Acceptance

| Check | Result |
|---|---:|
| 252-day comparator rows | 252 |
| errors | 0 |
| R3 violations | 0 |
| PASS | 128 |
| WARN | 124 |
| BLOCK | 0 |
| package tests | 260 OK |
| golden tests | 11 OK |

## Live Effect

None. This snapshot does not change live config, feature flags, account state, signal journal, or order routing. It only creates dry-run reports for human review.
