# Dollar SLO Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the dollar signal's scoring, soft-data, and external-source freshness limits at 14 calendar days without silently changing unrelated source behavior.

**Architecture:** Keep `config/config.json` as the deployed soft-data SLO authority, retain the risk source's intrinsic safety limit, and make the external-source profile report the same limit. Extend the governance checker so future 14/6/10 drift fails CI. Treat the change as behavior-affecting: prove ordinary-date equivalence and separately report the intended 2026-07-10 difference.

**Tech Stack:** Python 3, pytest, JSON config, existing Hermes governance and replay tooling.

## Global Constraints

- Do not modify or stage the existing deploy/watchdog track files.
- Do not run against writable live state; all score replays use isolated data clones.
- Do not deploy or apply live config in this plan.
- Stop before a formal gate if the directed replay changes action status, target weight, or DEFCON routing.
- Use TDD: each behavior test must fail for the expected old 6/10-day behavior before production changes.

---

### Task 1: Pin the 14-day contract in tests

**Files:**
- Modify: `src/hermes_escape_top/tests/test_soft_data_slo.py`
- Modify: `src/hermes_escape_top/tests/test_refresh_external_cli.py`
- Modify: `src/hermes_escape_top/tests/test_governance_consistency.py`

**Interfaces:**
- Consumes: `apply_soft_data_slo(records, config)`, `refresh_external.status(config, today=...)`, `check_repository(root)`.
- Produces: regression coverage for 7-day availability, 15-day degradation, profile max-age 14, and cross-layer SLO governance.

- [ ] **Step 1: Write the failing soft-data boundary tests**

Set the test config's `dollar` max age to 14. Assert a 7-day record remains available and a 15-day record becomes missing with `max_age 14d` in the reason.

- [ ] **Step 2: Write the failing external-profile test**

Assert the dollar profile reports `max_age_days == 14`, is not stale at age 14, and becomes stale at age 15.

- [ ] **Step 3: Write the failing governance test**

Assert `check_repository(ROOT)` exposes `checks["dollar_slo_alignment"] == "OK"`. Add a direct unit test for a helper that reports an error when any of config, external profile, or risk-source max-age differs.

- [ ] **Step 4: Run RED tests**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_soft_data_slo.py \
  src/hermes_escape_top/tests/test_refresh_external_cli.py \
  src/hermes_escape_top/tests/test_governance_consistency.py -q
```

Expected: failures show the current config/profile values are 6 and 10 and the governance check is absent.

### Task 2: Align the three production thresholds

**Files:**
- Modify: `src/hermes_escape_top/config/config.json`
- Modify: `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Modify: `scripts/check_governance_consistency.py`
- Modify: `context.md`

**Interfaces:**
- Consumes: config `soft_data_slo.max_age_days.dollar`, `PROFILES["dollar"]`, and the registered `FredPercentileSource` named `dollar`.
- Produces: `dollar_slo_alignment(config) -> tuple[dict[str, int], list[str]]` and a governance snapshot containing the effective dollar SLO.

- [ ] **Step 1: Change only the dollar thresholds**

Set `config.soft_data_slo.max_age_days.dollar` to 14. Set the external profile to `max_age_days=14` and `warn_age_days=12`. Leave the risk source at its existing 14.

- [ ] **Step 2: Add the governance invariant**

Implement `dollar_slo_alignment(config)` by reading the config value, `profile_for("dollar").max_age_days`, and the registered risk source's `max_age_days`. Return an error unless all three equal 14. Add the values to `governance_snapshot` and the result to `checks`.

- [ ] **Step 3: Regenerate the context snapshot**

Run:

```bash
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python scripts/check_governance_consistency.py --write-context-snapshot
```

Expected: `ok=true` and `dollar_slo_alignment=OK`.

- [ ] **Step 4: Run GREEN tests**

Run the Task 1 pytest command. Expected: all selected tests pass.

### Task 3: Prove behavior and scope

**Files:**
- Create: `docs/history/2026-07-11_dollar_slo_alignment_evidence.md`
- Create: `building/reports/dollar_slo_alignment_2026_07_11.json`

**Interfaces:**
- Consumes: baseline commit `8a2709e`, candidate worktree, isolated copies of live history/soft-history, and score payloads.
- Produces: machine-readable and human-readable before/after evidence.

- [ ] **Step 1: Run four ordinary-date comparisons**

Replay `2022-06-30`, `2024-06-28`, `2026-05-29`, and `2026-07-09` against baseline and candidate in separate isolated data roots. Compare input hash, factor scores, status, target weights, and DEFCON routing.

- [ ] **Step 2: Run the directed 2026-07-10 comparison**

Record the dollar soft record, A11 score, symbol totals/status, target weights, and routing before and after. This date is expected to differ only because latency 7 is intentionally accepted.

- [ ] **Step 3: Apply the gate rule**

If any symbol status, target weight, or routing changes, stop and mark `FORMAL_GATE_REQUIRED`. If only data availability, confidence, or non-decision score evidence changes, record the exact delta and mark `DIRECTED_REPLAY_REVIEW_REQUIRED` for human approval.

- [ ] **Step 4: Run complete verification**

Run:

```bash
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python scripts/check_governance_consistency.py
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q src/hermes_escape_top scripts/check_governance_consistency.py
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
git diff --check
```

Expected: governance and compile exit 0, full suite passes, and diff check is clean.

### Task 4: Review and hand off

**Files:**
- Modify: `docs/history/2026-07-11_dollar_slo_alignment_evidence.md`

**Interfaces:**
- Consumes: all Task 3 evidence.
- Produces: an external-audit checklist and explicit deploy/no-deploy recommendation.

- [ ] **Step 1: Self-review the exact diff**

Confirm no files outside the plan are staged and no live runtime file was written.

- [ ] **Step 2: Commit only the approved scope**

Use explicit pathspecs; never `git add -A`.

- [ ] **Step 3: Push for external audit**

Push `hermes-docs`, then verify `HEAD == origin/hermes-docs`. Do not deploy.
