# Market Admission Reliability Study

Generated: `2026-08-06T01:47:39.601708+00:00`
Evidence source: `/Users/liweishi/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive`

> Read-only study. It does not fetch data, promote canonical rows, change thresholds, or alter live state.

## Decision

- Evidence: **INSUFFICIENT_EVIDENCE** (`18/30` completed sessions).
- Policy: **HOLD_FAIL_CLOSED_POLICY**.
- A threshold or source-role change is not authorized by this report.

## Summary

| Metric | Value |
|---|---:|
| Completed-session window | 2026-07-13..2026-08-05 |
| Admission artifacts | 24 |
| Session selection | FIRST_ARTIFACT_PER_COMPLETED_THROUGH |
| Artifact manifest SHA-256 | `fb59ede5037b207dd797a6b0ed673a411ed559b6e5fb3a26559f2106fcc37464` |
| Field inventory SHA-256 | `b17ac01d885ea090e14e0b6255711b0eb32b8321ed794a029be68280d4a49613` |
| Independent completed sessions | 18 |
| Blocked sessions | 10 (55.56%) |
| Unique blocking symbol/dates | 15 |
| Matured events with later evidence | 14 |
| Matured events recovered | 14 (100.0%) |
| Recovered on next observed run | 14 |
| Pending with no later evidence | 1 |
| Blocking events with close inside 0.5% band | 15 |
| Field-aware shadow eligible events | 5 |
| Field-aware shadow avoided blocked sessions | 3 |

## Blocking Events

| Symbol | Session | First seen | Status | Close diff | Max OHLC diff | Volume diff | Shadow | Resolution | Recovery run |
|---|---|---|---|---:|---:|---:|---|---|---:|
| AAPL | 2026-07-30 | 2026-07-31 | VOLUME_MISMATCH | 0.0000% | 0.0090% | 25.5496% | REMAINS_BLOCKED | RECOVERED | 1 |
| AMZN | 2026-07-23 | 2026-07-24 | PRICE_MISMATCH | 0.0000% | 3.7429% | 0.3239% | REMAINS_BLOCKED | RECOVERED | 1 |
| BRK.B | 2026-07-20 | 2026-07-21 | VOLUME_MISMATCH | 0.0000% | 0.0123% | 26.3522% | REMAINS_BLOCKED | RECOVERED | 1 |
| BRK.B | 2026-07-27 | 2026-07-28 | VOLUME_MISMATCH | 0.0000% | 0.0010% | 37.4140% | REMAINS_BLOCKED | RECOVERED | 1 |
| BRK.B | 2026-07-30 | 2026-07-31 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 26.8148% | WOULD_ADMIT_PRICE_CONSENSUS | RECOVERED | 1 |
| BRK.B | 2026-07-31 | 2026-08-01 | VOLUME_MISMATCH | 0.0000% | 0.0020% | 36.1505% | WOULD_ADMIT_PRICE_CONSENSUS | RECOVERED | 1 |
| BRK.B | 2026-08-04 | 2026-08-05 | VOLUME_MISMATCH | 0.0000% | 0.0019% | 27.2091% | WOULD_ADMIT_PRICE_CONSENSUS | RECOVERED | 1 |
| BRK.B | 2026-08-05 | 2026-08-06 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 36.4139% | WOULD_ADMIT_PRICE_CONSENSUS | PENDING_NO_LATER_EVIDENCE | - |
| DBMF | 2026-07-20 | 2026-07-21 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 52.6064% | REMAINS_BLOCKED | RECOVERED | 1 |
| DBMF | 2026-08-03 | 2026-08-04 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 39.0908% | WOULD_ADMIT_PRICE_CONSENSUS | RECOVERED | 1 |
| FNGS | 2026-07-30 | 2026-07-31 | PRICE_MISMATCH | 0.0000% | 1.3587% | 4.0935% | REMAINS_BLOCKED | RECOVERED | 1 |
| FNGS | 2026-08-03 | 2026-08-04 | PRICE_MISMATCH | 0.0000% | 1.1587% | 3.8060% | REMAINS_BLOCKED | RECOVERED | 1 |
| IAU | 2026-07-22 | 2026-07-23 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 32.4847% | REMAINS_BLOCKED | RECOVERED | 1 |
| SHV | 2026-07-21 | 2026-07-22 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 36.0426% | REMAINS_BLOCKED | RECOVERED | 1 |
| SMH | 2026-07-27 | 2026-07-28 | VOLUME_MISMATCH | 0.0000% | 0.1216% | 26.4692% | REMAINS_BLOCKED | RECOVERED | 1 |

## Interpretation

All 14 blocking events with later evidence recovered; this is consistent with transient vendor finalization, but the sample is not yet sufficient for a policy change. All 15 blocking events retained a close inside the current 0.5% match band; the observed blocks came from volume or another OHLC field.

The next review gate remains 30 independent completed sessions. Before that gate, keep the existing fail-closed admission policy and collect third-source evidence only in shadow mode.
