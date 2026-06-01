# NEXT-2 Report - Backtest Foundation Pass

Date: 2026-06-01

Source spec: `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## Scope Completed

Implemented the next set of pure backtest foundations:

- N2-T01 `build_snapshot(as_of, store, cfg)`
- N2-T02 `apply_cost(trade_notional, atr_pct, cfg)`
- N2-T03 minimal routed portfolio simulator `simulate(decisions, price_panel, cfg)`
- N2-T04 `compute_metrics(equity, benchmark, trades)`
- N2-T05 `eval_labels(signals, price, H, dd_threshold)`
- N2-T06 `walk_forward_splits(...)`
- N2-T07 `deflated_sharpe(returns, n_trials, skew, kurt)`
- N2-T08 full routed backtest runner and markdown/json reports
- N2-T09 hard-valve historical trigger tests

These are foundation utilities. They do not yet constitute the full 2018-2026 rule replay with routing legs, but they remove several missing primitives required for that replay.

## Implemented Files

- `core/backtest/snapshot.py`
  - Builds point-in-time market snapshots.
  - Forces `offline_replay_mode=True` internally.
  - Adds `SOFT` pseudo snapshot from cached/locally computed soft-data sources.
- `core/backtest/costs.py`
  - Transaction cost model with round-trip bps plus optional fixed/ATR slippage.
- `core/backtest/simulator.py`
  - Adds `DayDecision`.
  - Adds pure `simulate()` over target route weights and leg price series.
  - Tracks equity, turnover, and costs.
- `core/backtest/metrics.py`
  - Adds `compute_metrics()` on top of existing equity metrics.
  - Adds Calmar, turnover, benchmark CAGR/DD, drawdown reduction, CAGR drag, and insurance ratio.
- `core/backtest/labeling.py`
  - Adds `eval_labels()` for forward drawdown labels.
- `core/backtest/validation.py`
  - Adds `WalkForwardSplit`.
  - Adds date-based walk-forward splits with purge and embargo.
  - Adds `deflated_sharpe()` signature with conservative shape penalty.
- `core/backtest/run_full.py`
  - Adds `run_full_backtest()`.
  - Converts daily score/sizing/routing output into route-leg `DayDecision`s.
  - Simulates routed legs including `BOXX`, `BRK.B`, `SOXX`, `QQQ`, and `DBMF` where applicable.
  - Freezes and records `data_manifest_id`.
- `core/backtest/reports.py`
  - Adds `write_full_backtest_markdown()`.
- `tests/test_hard_valve_history.py`
  - Adds historical hard-valve assertions for 2022 MSTR and SOXL breaks.
  - Adds clean synthetic uptrend non-trigger test.

## Full Backtest Output

Generated:

- `reports/Backtest_FULL.json`
- `reports/Backtest_FULL.md`

Current report summary:

| Item | Value |
|---|---:|
| Requested window | `2018-01-01` to `2026-05-29` |
| Effective window | `2025-02-20` to `2026-05-29` |
| Trading dates | `320` |
| Final value | `$148,626.34` |
| CAGR | `36.87%` |
| MaxDD | `-11.43%` |
| Sharpe | `1.7050` |
| Sortino | `2.2471` |
| SPY CAGR / MaxDD | `19.83% / -18.42%` |
| QQQ CAGR / MaxDD | `29.20% / -22.44%` |

Coverage caveat:

- FNGU currently starts at `2025-02-20` in the available price source.
- The runner therefore uses `2025-02-20` as `effective_start` instead of fabricating 2018-2025 FNGU returns.
- This report is suitable for engineering acceptance of the backtest pipeline, not final capital calibration.

## Verification

```text
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m unittest discover -s hermes_escape_top/tests
Ran 78 tests in 19.375s
OK

PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m compileall -q hermes_escape_top
OK
```

## Remaining NEXT-2 Work

- Performance optimization: full runner currently rebuilds daily snapshots naively and takes a few minutes.
- Trade attribution detail can be expanded beyond daily turnover/cost rows.
- Full strict 2018-2026 strategy backtest remains blocked by FNGU history coverage unless a reliable source/proxy is approved.
