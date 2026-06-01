# Phase 0 Report - Greenfield Scaffold and Contracts

Generated: 2026-05-31

## Scope

Built the independent greenfield package at `hermes_escape_top/`. This does not replace or mutate the live v2.5 system. Phase 0 only establishes contracts, config validation, an empty deterministic scoring pipeline, and the progress ledger.

## Delivered

- `config/config.json`: greenfield single source of truth.
- `config.py`: config load, path resolution, schema guardrails.
- `core/data/base.py`: `Field` and `SymbolSnapshot`.
- `core/scoring/result.py`: `ScoreResult`.
- `core/data/quality.py`: missing-data scaling, blind-spot flags, data-quality skeleton.
- `pipeline.py`: empty score pipeline returning deterministic `ScoreResult` objects.
- `cli.py`: `bootstrap`, `empty-score`, `archive-soft-inputs`, and `flow` commands.
- `STATUS.md`: phase progress ledger.

## Audit

- Missing critical fields are not treated as safe. `close` missing maps to `adjusted_score=100`.
- Empty pipeline uses local history only and produces a stable `input_hash`.
- No real orders or IBKR order paths exist in greenfield.

## Verification

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/tests -p 'test_*.py'
```

Result: `Ran 9 tests in 0.387s OK`

Smoke output:

- `empty-score --as-of 2026-05-29`
- Data quality: `HIGH`
- Scores: all three symbols return empty `HOLD` contracts with zero score.

## Limitations

- Coverage tooling is not installed; line coverage percentage is not measured yet.
- Phase 0 intentionally does not implement A/B/C/D scoring logic.
