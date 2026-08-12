# Hermes Bounded Exception and Deployment-Ledger Audit

Date: 2026-08-13
Scope: Task 8 only; production Python under `src/`, `scripts/`, and `ops/`,
excluding tests. No strategy, config, live data, worktree, or deployment mutation.

## Counting Contract

AST inventory counts bare handlers plus handlers catching `Exception` or
`BaseException`. It deliberately does not classify narrow catches such as
`ValueError`, `OSError`, or `JSONDecodeError` as broad.

- Before bounded remediation: 247 broad catches in 69 files; 22 direct silent
  handlers whose only statement was `pass` or `continue`.
- After bounded remediation: 246 broad catches in 69 files; 20 direct silent
  handlers.
- This is an inventory, not a target to mechanically drive to zero. Boundary
  behavior and typed evidence matter more than the count.

Highest broad-catch concentrations after remediation:

| File | Count | Disposition |
|---|---:|---|
| `web/server.py` | 32 | Separate endpoint-contract audit; no mass edit |
| `scripts/run_daily_package.py` | 25 | Required catches convert failures to receipt/status/log evidence |
| `scripts/system_validation.py` | 15 | Diagnostic harness; defer |
| `ops/morning_acceptance.py` | 13 | Required collector boundary; each result is typed PASS/WARN/FAIL |
| `web/refresh.py` | 12 | Separate Web refresh contract audit; defer |
| `core/data/risk_signals.py` | 10 | Legacy adapter audit; defer |
| `pipeline.py` | 9 | One scoring-sensitive silent handler remains; see P1 below |
| `external_sources/runner.py` | 7 | Promotion boundary now fails closed on unreadable canonical |
| `scripts/backfill_history.py` | 7 | Separate history transaction audit; defer |
| `core/data/run_transaction.py` | 5 | Rollback boundary intentionally catches broadly and records failure |

## Remediated High-Risk Boundaries

| Boundary | Prior failure mode | New typed outcome |
|---|---|---|
| External source canonical admission | Existing canonical unreadable was treated as no staleness conflict and later crashed outside validation | `VALIDATION_ERROR`; canonical remains untouched; ledger records reason |
| Shared daily state | Corrupt shared state silently fell through to legacy or empty state | Raises `RuntimeError`; existing top-level daily state machine writes FAILED receipt |
| Immutable health evidence | Unreadable report candidates were silently skipped | Matching valid report can still be used, but acceptance records an explicit WARN naming unreadable evidence |
| Alpaca SIP fallback | Cached fallback parse/read failure disappeared | Auxiliary status includes `fallback_error`; strategy run remains nonblocking |
| Predeploy audit scan | Malformed JSONL rows were silently skipped | Predeploy raises `ValueError` and blocks certification of incomplete audit evidence |
| Daily preflight lag | Calendar calculation failure produced no indication | Preflight log records `lag unavailable:<type>`; scoring behavior is unchanged |

Every changed catch has a direct regression test. No catch was changed merely to
reduce the count.

## Deferred Risks

### P1: scoring-sensitive malformed history index

`pipeline.py` still skips a trade-symbol history whose final index cannot be
converted to a timestamp. Silently excluding that symbol can understate maximum
staleness. Changing it to neutral or fail-closed would alter confidence under a
malformed-input condition, so it requires a separate fault-injection task with
four-date normal-path equivalence and an explicit conservative-error contract.

### P2: Web read-path catch density

`web/server.py` and `web/refresh.py` contain 44 broad catches. Write endpoints
already map pipeline contention to 409 and unexpected failures to explicit HTTP
errors, but optional read attachments still contain silent compatibility paths.
Audit them endpoint-by-endpoint; do not mass-replace them with crashes.

### P2: legacy adapter catch density

`risk_signals.py` has 10 broad catches spanning optional/legacy data adapters.
The new ExternalSourceRunner path is typed and ledger-backed. Retire or migrate
legacy callers before narrowing their catches.

## FRED Credential Migration

The repository-local `src/hermes_escape_top/data/fred_api_key.txt` was ignored,
untracked, and byte-equivalent to the existing `FRED_API_KEY` in
`~/.hermes/.env`. The refresh entrypoint now reads only that named key. Process
environment takes precedence, an explicitly injected config remains next, and
`~/.hermes/.env` is the final fallback. The fallback is passed through an
ephemeral config copy and does not source or export any other `.env` value.

Pre-delete hash comparison and post-delete production-resolver smoke both
passed. Only the redundant repository copy was removed. Two live/shared legacy
copies remain untouched until a later controlled R6 migration.

## Dedicated Escape-Top Deployment Ledger Draft

Do not execute this migration in Task 8.

1. Create a standalone repository at
   `~/.hermes/deploy-ledgers/escape-top/`, outside both the runtime release tree
   and the root `~/.hermes` repository.
2. Track only immutable deployment manifests plus `current.json` and
   `previous.json`. A manifest records source commit, release ID, runtime-lock
   SHA, approved-policy SHA, live-config semantic SHA, current/previous targets,
   verification results, and timestamp. It never contains config values,
   credentials, data, reports, SQLite, positions, or orders.
3. Import historical metadata by reading root-`~/.hermes` commits whose subject
   matches `deploy escape-top @...`; write derived manifests without copying
   their trees or blobs.
4. Add a shadow ledger write to a future R6 deployment and compare three
   controlled deployments against the existing allowlisted commit evidence.
5. After independent audit, switch `commit_deploy_allowlist` to commit only the
   standalone manifest. Ledger commit failure remains a deployment failure and
   must occur before the final `deploy OK` message.
6. Preserve the old root repository read-only through a user-approved retention
   window. Any repack, archival, or deletion is a separate destructive task.

Current evidence justifying the migration: root `~/.hermes` tracks 24,407 files,
has 10,493 changed tracked entries and 10,354 untracked entries, and its Git pack
is 1.19 GiB. This is operationally noisy and far broader than deployment proof.

## Worktree and Storage Disposition

The machine-readable inventory is
`REPO_RUNTIME_STORAGE_2026_08_12.json`. Two missing `/private/tmp` worktrees are
marked `PRUNE_METADATA_ONLY`; no prune command was run. Existing clean worktrees
whose commits are merged are marked review-before-remove, while three unmerged
branches are retained. No runtime or worktree data was deleted.
