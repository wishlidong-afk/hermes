# Watchdog Live Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the standalone Hermes watchdog and deploy the accumulated safety fixes through R6 without changing live config.

**Architecture:** Keep watchdog runtime logic in one standard-library-only ops entrypoint. Extend the existing R6 deployment transaction so watchdog sync and rollback are covered by the same pipeline lock and backup set.

**Tech Stack:** Python 3 standard library, Bash, pytest, launchd, R6 symlink deployment.

## Global Constraints

- Never run a second official daily or refresh IBKR during this work.
- Never apply repo config to live; Dollar SLO remains 6 days.
- Never stage local baseline/execution-timing artifacts or unrelated main-worktree changes.
- Deploy only when 8766 is healthy, no daily process is running, and local time is outside 07:00-07:20 CST.

---

### Task 1: Harden watchdog parsing and calendar

**Files:**
- Create: `ops/hermes_watchdog.py`
- Modify: `src/hermes_escape_top/tests/test_ops_entrypoints.py`
- Modify: `src/hermes_escape_top/web/refresh.py`
- Modify: `src/hermes_escape_top/tests/test_health_truth.py`

**Interfaces:**
- Produces: `resolve_audit_log(home)`, `latest_audit_as_of(home)`, `is_trading_day(day)`, and `completed_trading_days_after(as_of, now_et)`.

- [x] Add failing tests proving active/shared/legacy path precedence, malformed-tail recovery, all-invalid behavior, and holidays beyond 2028.
- [x] Run the focused tests and confirm the new cases fail for the expected reasons.
- [x] Implement newest-valid-record recovery and algorithmic NYSE holidays with no package imports.
- [x] Run focused tests and `/usr/bin/python3 ops/hermes_watchdog.py --self-test` to green.

### Task 2: Complete deployment transaction coverage

**Files:**
- Modify: `scripts/deploy_to_live.sh`
- Modify: `src/hermes_escape_top/tests/test_deploy_to_live.py`

**Interfaces:**
- Consumes: repository `ops/hermes_watchdog.py`.
- Produces: live `~/.hermes/bin/hermes_watchdog.py` covered by backup, sync, rollback, mode, and Git pathspec.

- [x] Add failing deployment tests for successful sync and rollback restoration of the watchdog.
- [x] Run focused deployment tests and confirm the sync assertion fails before implementation.
- [x] Extend backup, rollback, R6/legacy sync, permissions, and Git pathspec narrowly.
- [x] Run deployment tests and Bash syntax checks to green.

### Task 3: Audit and repository verification

**Files:**
- Create: `docs/history/2026-07-12_watchdog_live_deploy_audit.md`

**Interfaces:**
- Produces: an external reviewer checklist tied to exact code and test evidence.

- [x] Run focused watchdog/deployment tests.
- [x] Run the full suite in the isolated worktree.
- [x] Write the audit handoff with scope, invariants, test output, deployment preconditions, and rollback procedure.
- [x] Run JSON/Markdown/diff hygiene checks and review the final changed-file list.
- [ ] Commit and push only the watchdog, deployment, tests, and audit documents.

### Task 4: Integrate and deploy

**Files:**
- Integrate the verified commit into `hermes-docs` without staging unrelated main-worktree files.
- Deploy with `echo N | bash scripts/deploy_to_live.sh`.

**Interfaces:**
- Produces: new R6 live VERSION and a working `~/.hermes/bin/hermes_watchdog.py`.

- [ ] Confirm repo/head/push status, local time, 8766 HTTP 200, and no daily process.
- [ ] Run the R6 deployment once with live config preserved.
- [ ] Verify VERSION, 8766, official receipt/default-page state, watchdog self-test, active audit path, and `~/.hermes` commit.
- [ ] Confirm no rollback occurred and report every warning verbatim.
