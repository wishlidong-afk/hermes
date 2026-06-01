# Phase 5 Report - Verdict Layer

Date: 2026-06-01

## Scope

Phase 5 separates final action judgment from raw scoring:

- Base score to status mapping.
- Hard-valve override to `EXIT` and 100% sell fraction.
- General upgrade rules:
  - `C >= 18` sets minimum `REDUCE`.
  - `B >= 18` and `C >= 12` sets minimum `DEFENSIVE_EXIT`.
  - Red-light factor count >= 4 sets minimum `REDUCE`.
  - FNGU/SOXL while QQQ is below EMA20 sets minimum `TRIM`.
  - Missing weight above blind-spot threshold upgrades one level.
- Optional soft-sell confirmation: when enabled, non-hard sell upgrades require a second close.

## Integration

`score_symbol(...)` now calls `make_verdict(...)` after raw scoring and hard-valve evaluation. The scorer wrappers `status_from_score(...)` and `sell_fraction_for(...)` are preserved for compatibility.

## Verification

- Hard valves bypass confirmation and force `EXIT`.
- Blind-spot missing data upgrades one level.
- C-module floor upgrades to at least `REDUCE`.
- Soft upgrade confirmation can hold a first sell signal at `WATCH`.
- Ladder helper functions are covered.

## Remaining Gaps

- Persistent signal journal integration is not wired in greenfield yet, so confirmation is implemented as a pure function but not stateful in the CLI.
- SOXL leadership-specific upgrade rules that depend on component breadth/flow remain blocked until component soft-data adapters are complete.
