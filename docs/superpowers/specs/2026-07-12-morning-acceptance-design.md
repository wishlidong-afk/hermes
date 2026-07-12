# Hermes Morning Acceptance Design

## Purpose

At 09:05 Asia/Shanghai, verify the first production evidence produced by the
07:10 scheduled run and the 09:00 watchdog. The verifier is read-only with
respect to Hermes strategy data: it must not run daily, score, refresh market
data, connect to IBKR, or alter official receipts and audit records.

## Scope

The verifier reads the R6 live tree at
`~/.hermes/skills/investment/escape-top`, the dashboard health API at
`http://127.0.0.1:8766/api/health_status`, and
`~/.hermes/logs/watchdog.log`. It writes only its own JSON and Markdown reports
under `~/.hermes/logs/acceptance/`.

## Acceptance Contract

The report contains seven independently evidenced checks:

1. **Release identity**: `current` is a release symlink and its `VERSION` hash
   matches the release directory name.
2. **Scheduled receipt**: `run_receipt.json` is `OK`, `ok=true`,
   `run_type=scheduled`, and completed on the acceptance date.
3. **Scheduled audit**: the active `current/shared` audit contains exactly one
   scheduled record whose `run_ts` falls on the acceptance date. Its `as_of`
   matches the receipt and it has an `input_hash`.
4. **Persistence transaction**: that audit record names protocol
   `recoverable-journal-v1`; the corresponding transaction manifest is
   `COMMITTED`, covers the six business artifacts, and no `active.json`
   remains.
5. **Bound health report**: the report for the audit `as_of` was generated on
   the acceptance date, has the same `input_hash`, and contains the successful
   scheduled receipt. The only permitted strategy warning is stale `dollar`;
   stale IBKR is permitted only as position-reconciliation `INFO`.
6. **Dashboard**: `/api/health_status` returns HTTP 200, matches audit `as_of`,
   reports receipt `OK`, and has no unapproved strategy or auxiliary-flow
   degradation.
7. **Watchdog**: a scheduled-window log entry exists between 08:55 and 09:15
   on the acceptance date and is `ok`, not `ALERT`.

Any failed check makes the report `FAIL`. Permitted Dollar and IBKR conditions
remain visible as `WARN`; they are never silently converted to PASS.

## Components

`ops/morning_acceptance.py` is a standalone Python 3 standard-library program.
Its evidence collectors return structured check rows so tests can inject a
temporary home tree, a fixed clock, and a fake HTTP reader without touching
live state. The CLI atomically writes dated and `latest` JSON/Markdown reports
and exits `0` for PASS or `2` for FAIL.

The recurring Codex heartbeat runs the verifier daily at 09:05 CST and reports
the result in the current task. Its prompt explicitly forbids daily runs,
refreshes, IBKR access, and repairs.

## Failure Handling

Missing, malformed, mismatched, or inaccessible evidence is a failed check,
not an exception that aborts the entire report. The report preserves the
specific path or status that failed. Only failure to write the verifier's own
report is a CLI error.

## Verification

- Unit fixtures prove a clean PASS with Dollar WARN and IBKR INFO.
- Negative tests cover duplicate scheduled runs, hash mismatch, residual
  transaction state, non-committed manifest, and watchdog ALERT.
- A live read-only run confirms current paths and HTTP behavior.
- The full Hermes test suite remains green.

