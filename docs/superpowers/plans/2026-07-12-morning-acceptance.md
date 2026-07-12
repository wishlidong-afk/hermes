# Hermes Morning Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily, read-only PASS/FAIL verifier for the 07:10 scheduled run and 09:00 watchdog.

**Architecture:** A standalone standard-library script reads the R6 live symlink, shared runtime evidence, dashboard health API, and watchdog log. Pure evidence functions produce structured checks; the CLI writes only atomic reports in `~/.hermes/logs/acceptance/`.

**Tech Stack:** Python 3.9+ standard library, pytest, Codex heartbeat automation.

## Global Constraints

- Do not run daily, score, market refresh, external refresh, or IBKR code.
- Do not write anywhere under the live strategy data tree.
- Dollar staleness stays visible as WARN; IBKR staleness stays visible as INFO.
- Any other strategy or auxiliary-flow degradation is FAIL.
- All time comparisons use `Asia/Shanghai`; audit `run_ts` may be UTC.

---

### Task 1: Evidence Contract

**Files:**
- Create: `src/hermes_escape_top/tests/test_morning_acceptance.py`
- Create: `ops/morning_acceptance.py`

**Interfaces:**
- Produces: `collect_acceptance(home, now, dashboard_reader) -> dict`
- Produces: `render_markdown(report) -> str`
- Produces: `write_reports(report, output_dir) -> dict[str, Path]`

- [ ] **Step 1: Write the failing happy-path test**

Create an R6-shaped temporary live tree with one OK receipt, one scheduled
audit record, one committed six-artifact transaction, one hash-bound health
report, an HTTP 200 health payload, and a 09:00 watchdog `ok` line. Assert the
result is PASS while Dollar and IBKR remain WARN.

- [ ] **Step 2: Run the focused test and verify RED**

Run:
`PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_morning_acceptance.py -q`

Expected: collection or import failure because `ops/morning_acceptance.py` does
not yet exist.

- [ ] **Step 3: Implement the minimal collector**

Implement release, receipt, audit, transaction, report, HTTP, and watchdog
checks with structured `id/status/detail/evidence` rows. Preserve individual
failures instead of aborting collection.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command. Expected: PASS.

### Task 2: Failure Modes and Report Output

**Files:**
- Modify: `src/hermes_escape_top/tests/test_morning_acceptance.py`
- Modify: `ops/morning_acceptance.py`

**Interfaces:**
- Consumes: `collect_acceptance`, `render_markdown`, `write_reports`
- Produces: CLI exit `0` for PASS and `2` for FAIL

- [ ] **Step 1: Add failing tests for unsafe evidence**

Add separate tests for duplicate scheduled audit records, audit/report hash
mismatch, `active.json`, non-COMMITTED manifest, unexpected health degradation,
and watchdog ALERT. Add a report-output test that verifies dated and latest
files are atomically replaced.

- [ ] **Step 2: Run focused tests and verify RED**

Run the focused test command and confirm each new assertion fails for the
intended missing behavior.

- [ ] **Step 3: Implement minimal failure handling and CLI**

Make each unsafe condition produce a FAIL check, render a concise Markdown
table, write JSON/Markdown reports beneath the selected output directory, and
return the documented exit code.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the focused test command. Expected: all tests pass.

### Task 3: Operational Integration

**Files:**
- Modify: `ops/README.md`
- Create: `docs/history/2026-07-12_morning_acceptance_audit.md`

**Interfaces:**
- Consumes: `/usr/bin/python3 ops/morning_acceptance.py`
- Produces: daily 09:05 Codex heartbeat result in the current task

- [ ] **Step 1: Document the read-only command and evidence paths**

Document exit codes, report paths, permitted warnings, and the explicit ban on
using the verifier to repair live state.

- [ ] **Step 2: Run static and focused verification**

Run `/usr/bin/python3 -m py_compile ops/morning_acceptance.py`, the focused test
file, and `git diff --check`.

- [ ] **Step 3: Run live read-only verification**

Run `/usr/bin/python3 ops/morning_acceptance.py` and inspect the generated JSON
and Markdown. Do not modify live strategy evidence.

- [ ] **Step 4: Run the full suite**

Run the Hermes pytest suite. Expected baseline is at least `785 passed` with no
new warning class.

- [ ] **Step 5: Commit, integrate, and create the heartbeat**

Commit only the script, tests, and docs; push the feature branch; integrate the
exact commit into `hermes-docs`; push main. Create a daily 09:05 CST heartbeat
that runs the read-only verifier and reports PASS/FAIL without repair actions.

