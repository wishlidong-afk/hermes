# Market Admission Reliability Study

Generated: `2026-07-28T09:58:29.611343+00:00`
Evidence source: `/Users/liweishi/.hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive`

> Read-only study. It does not fetch data, promote canonical rows, change thresholds, or alter live state.

## Decision

- Evidence: **INSUFFICIENT_EVIDENCE** (`11/30` completed sessions).
- Policy: **HOLD_FAIL_CLOSED_POLICY**.
- A threshold or source-role change is not authorized by this report.

## Summary

| Metric | Value |
|---|---:|
| Completed-session window | 2026-07-13..2026-07-27 |
| Admission artifacts | 15 |
| Session selection | FIRST_ARTIFACT_PER_COMPLETED_THROUGH |
| Artifact manifest SHA-256 | `7451001a0c44db3b43373d60117665cf3dc0a6adcf48996b40ed96ada4edd901` |
| Independent completed sessions | 11 |
| Blocked sessions | 5 (45.45%) |
| Unique blocking symbol/dates | 7 |
| Matured events with later evidence | 5 |
| Matured events recovered | 5 (100.0%) |
| Recovered on next observed run | 5 |
| Pending with no later evidence | 2 |
| Blocking events with close inside 0.5% band | 7 |

## Blocking Events

| Symbol | Session | First seen | Status | Close diff | Max OHLC diff | Volume diff | Resolution | Recovery run |
|---|---|---|---|---:|---:|---:|---|---:|
| AMZN | 2026-07-23 | 2026-07-24 | PRICE_MISMATCH | 0.0000% | 3.7429% | 0.3239% | RECOVERED | 1 |
| BRK.B | 2026-07-20 | 2026-07-21 | VOLUME_MISMATCH | 0.0000% | 0.0123% | 26.3522% | RECOVERED | 1 |
| BRK.B | 2026-07-27 | 2026-07-28 | VOLUME_MISMATCH | 0.0000% | 0.0010% | 37.4140% | PENDING_NO_LATER_EVIDENCE | - |
| DBMF | 2026-07-20 | 2026-07-21 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 52.6064% | RECOVERED | 1 |
| IAU | 2026-07-22 | 2026-07-23 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 32.4847% | RECOVERED | 1 |
| SHV | 2026-07-21 | 2026-07-22 | VOLUME_MISMATCH | 0.0000% | 0.0000% | 36.0426% | RECOVERED | 1 |
| SMH | 2026-07-27 | 2026-07-28 | VOLUME_MISMATCH | 0.0000% | 0.1216% | 26.4692% | PENDING_NO_LATER_EVIDENCE | - |

## Interpretation

All 5 blocking events with later evidence recovered; this is consistent with transient vendor finalization, but the sample is not yet sufficient for a policy change. All 7 blocking events retained a close inside the current 0.5% match band; the observed blocks came from volume or another OHLC field.

The next review gate remains 30 independent completed sessions. Before that gate, keep the existing fail-closed admission policy and collect third-source evidence only in shadow mode.
