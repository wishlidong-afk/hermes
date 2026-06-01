# Phase 1 Report - Data Store, Offline Replay, Dated Archive, Flow v2

Generated: 2026-05-31

## Scope

Built the first real data layer for the greenfield system. It reuses local CSV history, seeds dated soft-data archives, and implements price/volume-derived flow v2 metrics. It does not fetch live data in offline mode and does not affect v2.5.

## Delivered

- `core/data/store.py`: local CSV history store, legacy history bootstrap, dated archive read/write.
- `core/data/market.py`: deterministic local OHLCV snapshots with MA/EMA/RSI/MACD/ATR/chandelier-ready fields.
- `core/features/indicators.py`: Phase 1 indicator frame used by snapshots.
- `core/data/network_guard.py`: `assert_no_network()` test hook.
- `core/data/flow.py`: CMF20, MFI14, AD line slope, outflow-days and basket aggregation.
- CLI commands:
  - `bootstrap`
  - `archive-soft-inputs --as-of YYYY-MM-DD`
  - `flow --as-of YYYY-MM-DD`

## Verification Evidence

History bootstrap:

- Copied/reused 30 local history CSVs.

Dated archive seed for `2026-05-29`:

- `data/archive/enrichment_cache_2026-05-29.json`
- `data/archive/valuation_snapshot_2026-05-29.json`
- `data/archive/cboe_pcr_2026-05-29.json`

Flow v2 smoke result for `2026-05-29`:

| Symbol | Severity | CMF20 | MFI14 |
|---|---|---:|---:|
| MSTR | NORMAL | 0.1310 | 36.9734 |
| FNGU | NORMAL | 0.2622 | 67.7865 |
| SOXL | NORMAL | 0.2884 | 60.3394 |

## Safety Checks

- Offline no-network hook passed around the flow snapshot call.
- `load_dated_snapshot(name, as_of)` never returns future snapshots.
- CMF signs are correct on synthetic distribution/accumulation candles.
- Missing soft data is archived as unavailable rather than filled with invented values.

## Environment Facts

- `sklearn_available=false`; future covariance shrinkage must use the hand-written fallback unless sklearn is installed later.

## Limitations

- Phase 1 archives are seed placeholders for soft data. Real adapters are Phase 10.
- Phase 1 does not yet implement the scoring modules or hard valves.
- Coverage tooling is not installed; line coverage percentage is not measured yet.
