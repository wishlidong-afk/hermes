# Phase 7 Report - Position Sizing And Clamp

Date: 2026-06-01

## Scope

Phase 7 adds final position sizing primitives:

- `assert_not_more_aggressive(...)` guardrail.
- Per-leg volatility scaler using the Phase 2 volatility snapshot.
- Portfolio gross scaler input from Phase 6.
- Final target weight clamp: target cannot exceed the verdict-after-sell reference weight or sleeve cap.
- `score_pipeline(...)` now includes a `sizing` block for MSTR/FNGU/SOXL.

## Verification

- Invariant rejects a target above the reference.
- High-volatility synthetic series reduces target weight.
- 100%-sold position sizes to zero.
- Score pipeline includes sizing for all trade symbols.

## Remaining Gaps

- The gross scaler is still shadow-only because Phase 6 has not been backtest-calibrated.
- Persistent state for hysteresis is not wired yet.
