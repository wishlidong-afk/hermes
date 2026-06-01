# Phase 11 Report - Backtest And Replay Harness

Date: 2026-06-01

## Scope

Phase 11 adds the first greenfield replay/backtest primitives:

- Equity curve metrics: final value, CAGR, max drawdown period, Sharpe, Sortino.
- Deterministic score replay over local QQQ trading dates.
- Transaction-level rebalanced-weight simulator with friction.
- Strategy backtest CLI over greenfield sizing targets.
- Param-sweep scaffold for vol budget / correlation window / extreme-correlation penalty.
- Triple-barrier labels and sample uniqueness weights.
- Purged K-fold and deflated Sharpe helper.
- CLI command: `python3 -m hermes_escape_top.cli replay --start YYYY-MM-DD --end YYYY-MM-DD --limit N`.
- CLI command: `python3 -m hermes_escape_top.cli backtest --start YYYY-MM-DD --end YYYY-MM-DD --limit N`.
- CLI command: `python3 -m hermes_escape_top.cli param-sweep --start YYYY-MM-DD --end YYYY-MM-DD --limit N`.

## Verification

- Max drawdown period is tested against a known equity curve.
- Equity metrics produce expected final value and drawdown sign.
- Two-day local replay is deterministic and returns 3 symbol rows per date.
- Local strategy backtest and param-sweep scaffolds run deterministically.
- Labeling and purged validation helpers are unit-tested.

## Remaining Gaps

- The current param sweep uses static target weights as a calibration shell; full rule-replay optimization is still pending.
- Backtest simulates close-to-close weights and friction; it does not yet model intraday fills, partial fills, tax lots, or real IBKR executions.
