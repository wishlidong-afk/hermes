# P0 Execution Log — Synthetic Leveraged History

Generated: `2026-06-01`

## Source Instructions Read

- GitHub repo: `wishlidong-afk/hermes`
- Branch: `hermes-docs`
- Required entrypoints read before work:
  - `README.md`
  - `docs/CODEX_GUIDANCE.md`
  - `docs/STATUS.md`
  - `docs/ROADMAP.md`
  - `docs/BUILD_TICKETS.md`
  - `docs/00_MASTER_OVERVIEW.md`
  - `docs/SYSTEM_OVERVIEW.md`

## Implemented Scope

- Added `core/data/synth_leverage.py`.
- Added `scripts/build_synth_history.py`.
- Added `tests/test_p0_synth_leverage.py`.
- Updated `core/data/manifest.py` so manifests record proxy row count, proxy date range, and proxy sources.
- Updated `core/data/market.py` so snapshots propagate `is_proxy` and source provenance into OHLCV and derived fields.
- Generated `reports/P0_synth_history_report.md/json`.
- Updated local `STATUS.md`.

## Data Generation

- FNGU:
  - Underlying: `^NYFANG`
  - Leverage: `3.0x`
  - History after P0: `2018-01-02` to `2026-05-29`
  - Real start: `2025-02-20`
  - Proxy rows: `1793`
  - Proxy range: `2018-01-02` to `2025-02-19`
- FNGS:
  - Underlying: `^NYFANG`
  - Leverage: `1.0x`
  - History after P0: `2018-01-02` to `2026-05-29`
  - Real start: `2019-11-13`
  - Proxy rows: `470`
  - Proxy range: `2018-01-02` to `2019-11-12`

## Validation

Strict P0 gate result: `NOT PASSED`

| Symbol | Return Corr | Annual TE | Gate |
|---|---:|---:|---|
| FNGU | `0.9950` | `8.42%` | Corr passed, TE failed |
| FNGS | `0.9914` | `4.12%` | Passed |

Stable diagnostic skipping first 20 real observations:

| Symbol | Return Corr | Annual TE | Gate |
|---|---:|---:|---|
| FNGU | `0.9986` | `4.67%` | Diagnostic pass only |
| FNGS | `0.9915` | `4.11%` | Passed |

Conclusion: P0 code and data plumbing are built, but strict FNGU tracking-error acceptance is not met. Per `CODEX_GUIDANCE.md`, P1/NEXT-2 full-window rerun and NEXT-3 calibration remain blocked until FNGU synthetic quality is improved or an alternative real/proxy source is approved.

## Tests

Command:

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m unittest discover -s tests
```

Result: `Ran 82 tests in 18.403s — OK`

## Next Required Action

Continue P0, but do not advance to P1:

1. Investigate FNGU tracking-error concentration in the first 20 yfinance real observations.
2. Try an alternative underlying/proxy source for FANG+ or a documented vendor adjustment.
3. Re-run strict overlap validation until FNGU annual TE is `<5%`.
