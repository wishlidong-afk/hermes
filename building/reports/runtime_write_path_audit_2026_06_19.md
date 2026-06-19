# Hermes Runtime Write-Path Audit

Date: 2026-06-19
Baseline: `3f48dd3`
Scope: production decision data, market/soft inputs, operational receipts, and Web-triggered writes.

## Transaction contract

The shared mutex is `<archive_dir>/.pipeline.lock`. Public score entry points acquire it;
the private `_score_pipeline_locked` path requires an active lease minted by that context
and validates capability, PID, thread owner, active lifetime, and lock path. Web writers use
non-blocking acquisition and return HTTP 409 on contention. Scheduled/CLI writers wait for a
bounded timeout.

## Entry-point map

| Entry | Writes | Lock behavior after remediation | Contention behavior |
|---|---|---|---|
| scheduled `run_daily_package` | history/soft inputs, manifest, score stores, audit/journal, artifacts, state, receipt | one outer lease; score consumes active lease | wait up to configured 600s, then non-zero |
| manual/deploy-verify daily | score stores, shadow/live artifacts, audit/journal; no official state/receipt in deploy verify | same outer lease | bounded wait, then non-zero |
| CLI `score` | complete score persistence set | public `score_pipeline` transaction | bounded wait |
| CLI `ibkr-live` | IBKR report plus complete score persistence set | public `run_live_check` transaction | bounded wait |
| CLI `dashboard` / `mirror-dashboard` | score persistence, then requested HTML file | score transaction covers production writes | bounded wait |
| CLI bootstrap/backfill/freeze/archive-soft/soft-data | history, manifest, or soft archives | explicit CLI transaction | bounded wait |
| 8766 refresh score/positions | refreshed history/manifest, score stores, refresh ledger | one non-blocking refresh+score lease | HTTP 409, no write |
| 8766 refresh manifest/soft data | manifest or soft inputs | non-blocking lease | HTTP 409, no write |
| 8766 IBKR demo/live | demo snapshot or report plus optional score stores | one non-blocking lease | HTTP 409, no write |
| 8766 execution confirmation | `hermes_state.sqlite` confirmation row | non-blocking lease | HTTP 409, no write |
| legacy M4 backfill | history and legacy baseline artifacts, then package shadow score | history/baseline under one non-blocking lease; shadow reacquires normally | HTTP 409 |
| legacy M4 shadow | shadow score artifacts | child package transaction with zero wait | HTTP 409 when busy |
| legacy M4 go-live | run entry script | non-blocking lease | HTTP 409 |
| 8765 mirror refresh | same refresh+score transaction as 8766 | non-blocking lease | HTTP 409 |
| deploy code swap | live code, VERSION, entry scripts | one helper-held `fcntl` lease for backup/sync/config/smoke | timeout/non-zero; exact rollback |

## Score persistence set

The score transaction protects these 13 logical write points (some share one SQLite file):

1. reentry plan rows;
2. reentry state rows;
3. mirror reference rows;
4. flow reference rows;
5. inferred execution-confirmation rows;
6. score-run rows;
7. decision rows;
8. factor-value rows;
9. posterior-P/L rows;
10. calibration rows;
11. source-quality rows and IBKR snapshot metadata;
12. audit JSONL record;
13. signal-journal JSONL entries.

Canonical artifacts compared by the equivalence harness are:

- `hermes_state.sqlite`
- `reentry_state.sqlite`
- `mirror_reference.sqlite`
- `flow_reference.sqlite`
- `audit_log.jsonl`
- `signal_journal.jsonl`

## Receipt and auxiliary boundary

The official receipt is orchestration state, not score input. A scheduled run writes
`RUNNING`, then atomically replaces it with `OK` or `FAILED`. If the replacement cannot be
written, the previous attestation is removed so health reports missing/critical instead of an
old green run. A stale `RUNNING` becomes critical after two hours; an `OK` receipt expires
after 26 hours, allowing the next 07:10 run a two-hour grace window.

Alpaca SIP flow is explicitly auxiliary. Its daily snapshot and status file are atomic, but a
failure degrades health rather than rewriting a successful core receipt. Backtest reports and
user-selected HTML output paths are research/output artifacts, not production decision state.

## Behavioral evidence

`building/reports/pipeline_persistence_equivalence_2026_06_19.json` compares the baseline and
candidate on four isolated data roots. Payload, status, `input_hash`, all SQLite schemas/rows,
audit rows, and journal rows are equal after normalizing only timestamps, temporary root paths,
and the timestamp-derived top-level audit `payload_hash`. The similarly named `payload_hash`
column in any SQLite table remains strict. `archive_soft_inputs()` and its dated snapshots are a
separate command outside the `score_pipeline` transaction, so they are intentionally outside this
proof. Result: `all_equal=true`.
