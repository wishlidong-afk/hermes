# P7 Phase III WARN Review Source Snapshot

**Date**: 2026-06-02  
**Scope**: read-only human-gate analysis for `PhaseIII_Dry_Run_Comparator.json` WARN rows.

## Files

| File | Purpose |
|---|---|
| `hermes_escape_top/scripts/phase3_warn_review.py` | Classifies WARN rows and measures candidate-vs-old forward return deltas over 1/5/10 trading days. |
| `hermes_escape_top/tests/test_phase3_warn_review.py` | Unit tests for reason classification, forward return math, month bucketing, and stats helpers. |

## Acceptance

| Check | Result |
|---|---:|
| comparator rows reviewed | 252 |
| WARN rows | 124 |
| EXTREME_CORR WARN rows | 102 |
| WARN 1d candidate-old avg | -0.00% |
| WARN 5d candidate-old avg | -0.05% |
| WARN 10d candidate-old avg | -0.29% |
| package tests | 264 OK |
| golden tests | 11 OK |

## Live Effect

None. This snapshot does not approve migration and does not change live config, feature flags, account state, signal journal, or order routing. It only prepares evidence for human review.
