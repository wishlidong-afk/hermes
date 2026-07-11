# 2026-07-11 Score Run Transaction External Audit Handoff

## Status

Step 5 of `2026-07-10_single_agent_20_dimension_review.md` is implemented in:

- Source commit: `d05f7b3 fix: recover cross-store score transactions`
- Deployment status: **not deployed**
- Focused transaction/Web tests: `17 passed`
- Full suite: `751 passed`
- Four-date payload and six-artifact comparison: `all_equal=true`
- Evidence: `building/reports/pipeline_persistence_equivalence_2026_07_11.json`

## Contract

One score run writes six independent business files:

1. `reentry_state.sqlite`
2. `mirror_reference.sqlite`
3. `flow_reference.sqlite`
4. `hermes_state.sqlite`
5. `audit_log.jsonl`
6. `signal_journal.jsonl`

The pipeline mutex prevents concurrent writers, but it cannot atomically commit
these six files. The new recovery contract is:

1. The lock-owning pipeline first reconciles any active incomplete run.
2. Before the first persistence write, all six files are snapshotted under one
   random run id.
3. An atomic manifest advances `PREPARING -> PREPARED -> PENDING`.
4. Every payload persisted by the run carries the same
   `persistence.run_id`.
5. A normal exception restores all six files before it escapes and records
   `ROLLED_BACK`.
6. A process killed while `PENDING` leaves the active marker and backups behind;
   the next lock-owning run restores them before reading state and records
   `RECOVERED_ROLLBACK`.
7. Only after every write succeeds does the manifest become `COMMITTED`; the
   active marker and backups are then removed.
8. The 8766 audit reader excludes a payload whose run id is still active, so an
   audit append immediately before a crash cannot become the official headline.

This is a recoverable multi-file protocol, not a claim that POSIX offers one
atomic rename across six files. It covers process exceptions and process death.
Power-loss durability still depends on the filesystem and each underlying
writer's fsync/SQLite settings.

## Capability Boundary

Both mutation interfaces require the private active pipeline lease and verify:

- capability identity;
- active state;
- current process;
- current thread;
- exact `<archive_dir>/.pipeline.lock` path.

Calling recovery or opening a score transaction without that lease raises before
touching files. Read-only status inspection does not require a lease.

## Fault Injection

The integration test injects an exception after every cross-store checkpoint:

1. `reentry_state`
2. `mirror_reference`
3. `flow_reference`
4. `execution_confirmations`
5. `unified_state`
6. `audit_log`
7. `signal_journal`

After each injected failure, SHA-256 for all six business artifacts must equal
the pre-run snapshot. The several writes inside `write_state_snapshot` share one
SQLite connection context and therefore roll back as one SQLite transaction;
the checkpoint is placed after that transaction returns.

Separate tests cover:

- successful `COMMITTED` transition;
- immediate exception rollback;
- simulated kill followed by next-run recovery;
- no recovery of a committed run;
- rejection without a valid lease;
- 8766 hiding an active transaction's audit payload;
- comparator normalization ignoring only the new transaction envelope while
  remaining strict on business fields.

## Behavior Equivalence

The comparator ran source commit `517043c` and candidate commit `d05f7b3`
against fresh clones of the same live shared history and soft-history inputs for:

- `2022-06-30`
- `2024-06-28`
- `2026-05-29`
- `2026-07-10`

It compares the normalized score payload and full logical contents of all six
business artifacts. The only intentional omission is the new operational
`persistence` envelope, whose random run id cannot be byte-identical. Result:
`all_equal=true` for all four dates.

## Required External Audit Questions

1. Does recovery run after validating the lease and before `LocalStore`, market,
   state, or journal reads?
2. Are all six production and shadow write paths included in the artifact set?
3. Can any approved `_score_pipeline_locked` caller bypass the transaction?
4. If a checkpoint raises, are existing files restored byte-for-byte and files
   created by the failed run deleted?
5. If the process dies after audit append, does 8766 continue to select the last
   committed official payload?
6. Can a stale `active.json` whose manifest is already `COMMITTED` trigger an
   incorrect rollback?
7. Does a corrupt/missing recovery manifest stop the run loudly rather than
   blessing partial state?
8. Are SQLite `-journal`, `-wal`, and `-shm` sidecars removed during restore?
9. Is the comparator strict on scores, decisions, rows, schemas, and order after
   omitting only transaction metadata?
10. Are the unrelated dirty deploy/watchdog files absent from commit `d05f7b3`?

## Recommended Commands

```bash
cd /Users/liweishi/Documents/github/hermes

git show --stat d05f7b3
git diff --check 517043c..d05f7b3

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_score_run_transaction.py \
  src/hermes_escape_top/tests/test_pipeline_transaction.py \
  src/hermes_escape_top/tests/test_pipeline_persistence_comparator.py \
  src/hermes_escape_top/tests/test_phase14_web.py -q

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

To reproduce the four-date equivalence report, use a detached worktree at
`517043c`, an isolated clone of the live shared data root, and
`scripts/compare_pipeline_persistence.py`. Never point replay runs at writable
live data.

## Residual Risk

- The transaction journal directories retain small terminal manifests; capacity
  pruning belongs to Step 7.
- Readers other than 8766 that parse `audit_log.jsonl` directly do not yet apply
  the active-run filter. The official dashboard is protected, and the next score
  run restores before reading state; direct forensic readers must consult the
  transaction manifest during an active incident.
- This batch does not change official run receipts, deployment, IBKR authority,
  production flags, or order safety.

## Pass Condition

Mark Step 5 `PASS` only if the capability checks, seven fault points, hard-kill
recovery, pending-audit filter, four-date equivalence report, focused tests, and
full suite all reproduce. A green full suite alone is insufficient.
