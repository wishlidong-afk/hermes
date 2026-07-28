# Market Admission Reliability Review

Date: 2026-07-28

Scope: read-only review of the existing live market-admission archive. No
network request, canonical promotion, threshold change, live write, scoring
run, or IBKR connection was performed.

## Decision

- Evidence status: **INSUFFICIENT_EVIDENCE (11/30 completed sessions)**.
- Production policy: **HOLD_FAIL_CLOSED_POLICY**.
- A field-aware admission policy is a research candidate only. This report
  does not authorize a config, flag, source-role, or threshold change.

The reproducible source report is:

- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_07_28.json`
- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_07_28.md`

## Observed Reliability

The archive contains 15 dated artifacts covering 11 independent completed US
sessions from 2026-07-13 through 2026-07-27.

| Measure | Result |
|---|---:|
| Sessions blocked on their first artifact | 5 / 11 (45.45%) |
| Unique blocking symbol/dates | 7 |
| Volume mismatches | 6 |
| Price mismatches | 1 |
| Events with later evidence | 5 |
| Events recovered on the next observed run | 5 / 5 |
| Events awaiting later evidence | 2 |
| Blocking events whose close remained within 0.5% | 7 / 7 |
| Input artifact manifest SHA-256 | `7451001a0c44db3b43373d60117665cf3dc0a6adcf48996b40ed96ada4edd901` |

The five matured events were `BRK.B`, `DBMF`, `IAU`, `SHV`, and `AMZN`.
Every one was admitted on the next observed run without a policy change. The
two events from 2026-07-27 (`BRK.B` and `SMH`) have no later artifact yet and
must remain pending rather than being called recovered or persistent.

The blocked-session rate intentionally uses the first artifact for each
`completed_through` session. It measures whether the first observed official
run was blocked, not whether a later same-session rerun eventually cleared.
That choice can be conservative when duplicate artifacts exist, so the report
exposes `session_selection_policy=FIRST_ARTIFACT_PER_COMPLETED_THROUGH` rather
than presenting the rate as an end-of-session success measure.

This pattern is consistent with transient vendor finalization. It is not yet
proof that the volume policy is wrong: the sample is short, the unresolved
events are the newest observations, and the current artifacts do not retain
the exact raw candidate and witness bars needed to attribute which provider
changed.

## Decision-Field Review

Static inspection shows that the current full-OHLCV row policy is stricter than
the fields consumed by several affected production paths:

| Symbol | Current role | Decision fields visible in the cited path | Review result |
|---|---|---|---|
| `BRK.B` | DEFCON2 primary/fallback monitor | close, MA200, close-return correlation with SPY | Observed volume mismatch does not enter this routing calculation. |
| `DBMF` | DEFCON1 trend execution leg | route weight and price history | No production score dependency on raw volume was found. |
| `IAU` | DEFCON1 gold execution leg | route weight and price history | No production score dependency on raw volume was found. |
| `SHV` | cash-like route/history support | price history | No production score dependency on raw volume was found. |
| `SMH` | SOXL radar/hard-valve confirmation | close, MA200, EMA50 duration | The cited hard-valve paths do not consume raw volume. |
| `AMZN` | FNGU component-flow constituent | CMF20, MFI14, AD slope20 | High/low/close/volume are decision-relevant. The artifact records only the maximum OHLC difference, so it cannot prove whether the changed field was consumed; retain the strict block pending raw evidence. |

Code evidence:

- `src/hermes_escape_top/core/routing/capital_routing.py`:
  `evaluate_brkb_defense()` uses BRK.B close/MA200 and close-return
  correlation.
- `src/hermes_escape_top/core/scoring/hard_valves.py`: SOXL radar checks use
  SOXX/SMH close, MA200, and EMA50 duration.
- `src/hermes_escape_top/core/scoring/module_d.py`: FNGU/SOXL component flow
  consumes CMF, MFI, and AD slope, which depend on OHLCV.

This is a candidate hypothesis, not a safe production shortcut. Before any
field-aware policy is proposed, a machine-generated dependency inventory must
prove which canonical fields can reach every score, hard valve, sizing, risk,
routing, and action-intent path.

## Evidence Debt

Current mismatch rows retain status, relative differences, and hashes, but not
the exact Yahoo candidate and Alpaca witness bars. Hashes prove identity but do
not permit independent reconstruction or third-source arbitration. Future
shadow evidence should retain immutable per-event values for:

- candidate and witness date/OHLCV;
- adjustment mode, feed, fetch timestamp, and completed-session cutoff;
- response/blob SHA-256 and source URL;
- corporate-action context when available; and
- a later-observation link showing whether either provider revised the row.

This evidence addition must be reporting-only and must not change admission or
`input_hash` behavior.

## Next Gate

1. Continue natural daily collection until 30 independent completed sessions.
2. Do not issue manual repeat refreshes solely to improve the measured rate.
3. Add immutable raw mismatch evidence and a third-source shadow witness before
   attributing fault to Yahoo or Alpaca.
4. Generate a code-derived required-field inventory for every admitted symbol.
5. At 30 sessions, pre-register one policy comparison:
   current full-OHLCV fail-closed versus field-aware admission. Compare blocked
   session rate, delayed recoveries, score/input-hash differences, hard-valve
   differences, and next-open baseline behavior.
6. Any policy candidate that changes an already certified score payload or
   weakens close evidence requires independent review and a formal gate.

Until those conditions are met, the current fail-closed policy remains the
correct production choice despite its operational false-positive cost.
