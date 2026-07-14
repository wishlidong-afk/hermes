# FRED / ALFRED Vintage PIT Gate Result

Date: 2026-07-14
Experiment: `fred-vintage-pit-v1`
Sealed commit: `0cd674e079c5c8bad41d7b222a51aae2b5f7a89d`
Verdict: **REJECTED**
Authorization: **NO_FLIP**

## Scope

The candidate replaces the legacy FRED `observation_date + 1 day` approximation
with an ALFRED `output_type=3` event store and exact `realtime_start` as-of
replay for Dollar, Real Rate, and Net Liquidity. The new path is isolated behind
`features.use_fred_vintage_pit=false`; the legacy files and ledgers are not
modified.

## Pre-Gate Evidence

- Four historical dates produced byte-identical payloads, `input_hash` values,
  and six persistence artifacts with the flag OFF.
- The isolated official bootstrap produced 29,970 unique vintage events across
  five FRED series; no API key appears in raw evidence.
- Exact derived canonicals rebuilt deterministically.
- Baseline and candidate full-window artifacts were both `FRESH`, used commit
  `0cd674e`, manifest `72dcbe43555dbc8cbea8974a8091b4cadb559a25f4ccf8e90f0b9d923d0024fe`,
  soft-history SHA256 `0d96aa5fe4a665d6ef013ec6e0bc82027645d3ff0600325bf79127a0d511cbc2`,
  and `next_open` execution timing.

## Full-Window Result

| Metric | Baseline | Exact vintage | Delta |
|---|---:|---:|---:|
| CAGR | 15.5629% | 13.8970% | -1.6659pp |
| Max drawdown | -20.8283% | -22.5537% | -1.7254pp |
| Sharpe | 1.062906 | 0.964497 | -0.098409 |
| Final value | $341,554.04 | $301,930.14 | -$39,623.90 |

## Formal Gate

| Check | Result |
|---|---|
| Walk-forward PBO 0.4286 <= 0.5 | PASS |
| CPCV PBO 0.0667 <= 0.5 | PASS |
| Walk-forward OOS delta +0.165206 >= 0 | PASS |
| CPCV OOS delta -0.077120 >= 0 | **FAIL** |
| MaxDD degradation <= 1pp | **FAIL** |
| DSR 0.835557 >= 0 | PASS |

Canonical evidence:

- `building/reports/formal_gate/fred-vintage-pit-v1/result.json`
- `building/reports/formal_gate/fred-vintage-pit-v1/REPORT.md`
- `building/reports/formal_gate/fred-vintage-pit-v1/artifacts/baseline.json`
- `building/reports/formal_gate/fred-vintage-pit-v1/artifacts/fred_vintage_pit.json`
- `building/reports/formal_gate/fred-vintage-pit-v1/ARTIFACTS.sha256`

The experiment-local artifact snapshot is deliberate: the tracked
`building/reports/flag_sweep/baseline*.json` files remain the current deployment
baseline and are not overwritten by a rejected experiment.

## Decision And Boundary

The production flag remains OFF. The exact event store and replay implementation
may remain as non-scoring research and audit infrastructure, but the four exact
files are not installed as production scoring inputs. This experiment is closed:
no threshold weakening, parameter tuning, or second gate is permitted.

The result also makes the remaining methodological debt explicit: the production
backtest baseline still uses the documented legacy FRED approximation. Replacing
that baseline on correctness grounds would be a separate governance decision,
not a retry of this alpha gate, and would require a new pre-registered migration
plan plus a restated baseline.
