# Phase 9 Report - 3-3-4 Reentry Plan

Date: 2026-06-01

## Scope

Phase 9 adds a pure 3-3-4 reentry planner:

- Phase 0 locks:
  - `days_since_last_sell >= 11`
  - final score below configured unlock threshold
  - C/D module risks cleared
  - no active sell/hard-valve signal
- T1: radar close above EMA20 and MACD cross near zero.
- T2: after T1, radar close breaks prior 20D high close.
- T3: after T2, QQQ/SPY confirms 252D high; otherwise reserve remains parked.

## Verification

- Time lock blocks reentry.
- T1 unlocks when locks clear and radar confirms.
- T2 requires prior-high breakout.
- `score_pipeline(...)` includes a `reentry` block.

## Remaining Gaps

- Pipeline currently uses `days_since_last_sell=0` because greenfield state persistence is not wired yet.
- T1/T2 active state is not persisted yet.
