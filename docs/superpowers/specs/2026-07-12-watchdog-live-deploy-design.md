# Watchdog Live Deploy Design

## Goal

Make the Hermes read-only watchdog follow the R6 runtime layout reliably, survive a torn audit-log tail, and ship through the same atomic deployment and rollback path as the other live entrypoints.

## Scope

- Resolve the audit log in this order: active `current`, stable `shared`, then the pre-R6 legacy root.
- Read the newest valid JSONL record, skipping blank or malformed tail records instead of crashing.
- Count completed US-market sessions with a deterministic standard-library holiday calendar that does not expire after a hard-coded year.
- Keep the 8766 health trading-day helper aligned with the same Saturday-New-Year exception.
- Keep the watchdog standalone under `/usr/bin/python3`; it must not import the Hermes package or third-party libraries.
- Include `hermes_watchdog.py` in deployment sync, backup, rollback, executable permissions, and the live Git allowlist.
- Treat only config-verified SLO expiry as a nonfatal predeploy warning; every unverified missing source remains fatal.
- Add deterministic tests for path precedence, malformed tails, long weekends, and deploy success/rollback.
- Produce an external-audit handoff before deployment.

## Non-Goals

- Do not change strategy scoring, config, daily scheduling, IBKR behavior, or notification thresholds.
- Do not modify the existing `com.hermes.watchdog` LaunchAgent; it already invokes `~/.hermes/bin/hermes_watchdog.py`.
- Do not commit local full-baseline or execution-timing artifacts.

## Design

`ops/hermes_watchdog.py` remains a small standalone program. Runtime path discovery is explicit and testable. Audit parsing retains the newest valid `as_of` while ignoring malformed records; an entirely invalid or missing file yields the existing unknown-state alert.

Trading-day logic computes NYSE full-session holidays algorithmically for any supported Python `date` year: observed New Year, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, and Christmas. It preserves NYSE's explicit exception that a Saturday New Year's Day is not observed on the preceding Friday. The watchdog continues to use 16:30 ET as its close-settlement boundary.

`scripts/deploy_to_live.sh` treats the watchdog like every other live entrypoint: it is backed up before swap, copied while the pipeline lock is held, restored on failure, made executable, and included in the narrow `~/.hermes` Git pathspec.

The predeploy smoke recognizes an expected SLO expiry only when all of the following agree: `use_soft_data_max_age=true`, the source's configured `max_age_days`, payload `latency_days`, and the canonical `stale: latency Nd > max_age Md` reason. Such a record remains visible as a WARN and keeps 8766 health degraded, but it does not make code deployment impossible. Any mismatch, fetch failure, parse error, disabled guard, or always-on daily source outage remains fatal.

## Verification

1. Focused unit tests must prove path precedence, malformed-tail recovery, holiday behavior, deployment sync, and rollback.
2. `ops/hermes_watchdog.py --self-test` must pass under `/usr/bin/python3`.
3. The full repository test suite must pass in the isolated worktree.
4. External-audit evidence must list changed files, tests, live preconditions, and rollback checks.
5. Deployment may proceed only outside 07:00-07:20 CST, with no daily process and 8766 healthy. Repo config must not replace live config.
6. A rolled-back deployment must not be retried until its smoke-policy conflict has its own tests, review, and commit.
