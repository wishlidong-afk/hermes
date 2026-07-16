# FRED / ALFRED Correctness Migration Gate Result

Date: 2026-07-16
Experiment: `fred-alfred-correctness-v1`
Sealed commit: `1dde064769f0558aafef951a230c09b43071c319`
Verdict: **MIGRATION_IMPACT_RECORDED**
Authorization: **NO_FLIP**

## Scope

This correctness lane measures the impact of replacing the production FRED
`observation_date + 1 day` approximation with authoritative ALFRED
`realtime_start` event history for Dollar, Real Rate, and Net Liquidity. The
candidate uses an isolated data root and the production feature flag remains
OFF. Positive alpha is not an authorization criterion for this lane.

## Evidence Boundary

- Baseline and candidate were run sequentially in independent processes against
  `/private/tmp/hermes-fred-correctness.BREoNz`.
- Both artifacts are `FRESH`, use commit `1dde064`, manifest
  `52235bb4ae7988338d739304cfa4f26f59910b6fcce26756d7053e114dbc7dac`,
  the same 2018-01-01 through 2026-07-14 window, and `next_open` execution.
- Both report `required_missing_rows=0` for execution-required open prices.
- The formal gate was run once. It was not tuned or repeated after seeing the
  result.

## Full-Window Result

| Metric | Baseline | Exact vintage | Delta |
|---|---:|---:|---:|
| CAGR | 16.9320% | 15.5720% | -1.3600pp |
| Max drawdown | -18.9881% | -20.1695% | -1.1814pp |
| Sharpe | 1.144520 | 1.064371 | -0.080149 |
| Final value | $371,899.96 | $337,103.35 | -$34,796.61 |

## Formal Gate

| Check | Result |
|---|---|
| Walk-forward PBO 0.4615 <= 0.5 | PASS |
| CPCV PBO 0.1333 <= 0.5 | PASS |
| Walk-forward OOS delta +0.033584 >= 0 | PASS |
| CPCV OOS delta -0.146057 >= 0 | **FAIL** |
| MaxDD degradation <= 1pp | **FAIL** |
| DSR 0.948214 >= 0 | PASS |

Canonical evidence:

- `building/reports/formal_gate/fred-alfred-correctness-v1/result.json`
- `building/reports/formal_gate/fred-alfred-correctness-v1/REPORT.md`
- `building/reports/formal_gate/fred-alfred-correctness-v1/artifacts/`
- `building/reports/formal_gate/fred-alfred-correctness-v1/ARTIFACTS.sha256`

The experiment-local snapshot is the sealed evidence. The shared
`building/reports/flag_sweep/baseline*.json` files are not promoted by this
NO_FLIP result.

## Decision

The exact PIT path remains research-only and `use_fred_vintage_pit` remains
false. The measured deterioration is accepted as correctness-migration evidence,
not hidden or optimized away. Production adoption and baseline restatement need
an explicit human governance decision; this result does not authorize either.
