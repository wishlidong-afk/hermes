# Phase 4 Report - Hard Valves

Date: 2026-06-01

## Scope

Phase 4 adds a pure hard-valve evaluator to the greenfield scoring path:

- `H-M1` through `H-M6`
- `H-F1` through `H-F7`
- `H-S1` through `H-S8`

The evaluator has no implicit IO. Any rule requiring multi-day history, such as `H-M4`, receives history frames from the caller. A hard-valve hit forces:

- `status = EXIT`
- `sell_fraction = 1.0`
- `hard_valve_hits = [...]`

## Migrated Behavior

- MSTR MA200 break and BTC/MSTR EMA20 confirmation rules.
- FNGU and SOXL QQQ/radar MA200 rules.
- Single-day and two-day crash rules.
- Three-days-below-EMA50 rules using injected histories.
- SOXL 60-day peak drawdown trigger.
- Chandelier 22D / 4.5x ATR trailing-stop rules.
- QQQ distribution + VIX curve stress rules.

## Verification

- Historical local sample 2026-05-29 triggers MSTR `H-M1` and `H-M4`, matching the frozen baseline family.
- Synthetic clean uptrend produces no false hard-valve hits.
- Synthetic SOXL 60D peak damage triggers `H-S6`.
- Synthetic FNGU QQQ MA200 break triggers `H-F1`.

## Remaining Gaps

- Full historical trigger matrix is still limited by available local daily raw/precheck coverage.
- Phase 5 verdict stabilization is not wired yet; hard valves already bypass it by forcing EXIT directly.
