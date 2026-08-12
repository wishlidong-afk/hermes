# Hermes System Relevance And Data Trust Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Hermes distinguish decision-bearing data from auxiliary and
research data, prevent stale repo data from being mistaken for live data, and
make freshness/acceptance evidence truthful without changing strategy scores,
thresholds, routing, or live feature flags.

**Architecture:** Extend the existing Source Policy Registry instead of adding
a second source registry. Use two explicit refresh lanes (`decision` and
`shadow`), keep all-source observability separate from decision-grade quality,
and make production entry points require an explicit runtime data root. Preserve
official immutable evidence; represent a post-deploy run awaiting natural
recertification as pending, never as a synthetic pass.

**Tech Stack:** Python 3.11, pytest, JSON/JSONL, pandas, launchd, Bash, R6
versioned releases, existing formal-gate and four-date equivalence tooling.

## Global Constraints

- Do not change scoring thresholds, module caps, routing weights, factor weights,
  portfolio sizing, hard-valve behavior, or reentry behavior in Tasks 1-8.
- Do not edit or replace live config. The three approved live-only flags remain
  attested differences from the repo default.
- Do not connect to IBKR, change `ibkr_readonly`, or add an order path.
- Do not run an official daily to validate code or deployment.
- Do not manually refresh live market/external data during equivalence tests.
- Every code task follows RED -> GREEN -> focused suite -> diff review.
- Use isolated `HERMES_DATA_DIR` copies for score/equivalence tests.
- Score, sizing, routing, hard-valve, reentry, and portfolio target outputs must
  remain byte-identical through Tasks 1-8.
- Reporting-only differences are allowed only on the documented paths:
  `data_quality`, `all_source_data_quality`, `data_quality_breakdown`,
  `decision_layers.*.strategy_confidence`, their existing compatibility mirrors
  under `decision_layers.*.action_confidence` and `action_intents.*` confidence
  scores, `today_ops.data_quality*`, and health/acceptance metadata.
- `audit_log.jsonl` and `hermes_state.sqlite` embed those reporting fields, so
  their raw hashes necessarily change in Task 3. Require strict equality after
  removing only the paths above; the other five transaction artifacts must stay
  raw-equal. This clarifies the internally inconsistent Task 0 wording without
  relaxing any score, status, sizing, routing, reentry, target, or input-hash
  comparison.
- Any future NAAIM factor retirement, mNAV activation, or route turnover change
  is a strategy experiment: default OFF, one formal gate, no retuning after FAIL.

## Current Evidence Anchor

- Repo/live release: `c6aaa14`.
- Current official run: `as_of=2026-08-11`, scheduled receipt/audit/transaction OK.
- Market admission: 122 admitted rows, 0 rejected, 111 price-evidence MATCH.
- Current reported quality: completeness 100, quality 90, latency 76,
  overall 92.2 HIGH.
- Research-only BTC funding/basis contributes 4 raw quality penalty points,
  equivalent to 1.2 overall points, despite decision weight 0.
- Current external freshness: AAII DUE_SOON (11d), Dollar DUE_SOON (5d), NAAIM
  RETIRED_PAYWALL/STALE (14d); market and remaining active strategy sources OK.
- Current repo-local ignored runtime data is roughly 596 MB; `.worktrees` is
  roughly 636 MB; `~/.hermes/.git` is roughly 1.2 GB.

---

### Task 0: Freeze The Before Evidence

**Files:**
- Create: `building/reports/system_update_2026_08_12/BEFORE_EVIDENCE.json`
- Create: `building/reports/system_update_2026_08_12/FOUR_DATE_BEFORE_EQUIVALENCE.json`
- Create: `building/reports/system_update_2026_08_12/README.md`

**Interfaces:**
- Consumes: current repo config, live attestation, official score payload,
  external-source status, governance output, and four isolated historical dates.
- Produces: immutable hashes and allowed-difference policy used by Tasks 1-9.

- [ ] Capture HEAD, repo status, live VERSION, live config attestation, `/readyz`,
  official receipt, scheduled audit input hash, and seven-artifact transaction.
- [ ] Record the current selected external refresh set and classify each source
  as active strategy, hard gate, auxiliary, research, inactive, or retired.
- [ ] Record current `data_quality`, per-symbol score/status/missing weights,
  sizing, routing, reentry, and portfolio targets for four historical dates.
- [ ] Hash the evidence files and write the exact allowed-difference JSON paths.
- [ ] Run governance and the existing equivalence harness; require 7/7 governance
  OK and four valid input hashes before Task 1 starts.
- [ ] Commit only the evidence manifest and README, not live/runtime data.

### Task 1: Single Decision-Relevance Contract

**Files:**
- Create: `src/hermes_escape_top/core/data/source_relevance.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Test: `src/hermes_escape_top/tests/test_external_source_profiles.py`
- Test: `src/hermes_escape_top/tests/test_source_relevance.py`

**Interfaces:**
- Consumes: `effective_source_profile(config, source_id)` and existing
  `decision_role`, `active`, feature flag, lifecycle, and dependency metadata.
- Produces:
  `source_is_decision_bearing(config, source_id) -> bool`,
  `source_refresh_lane(config, source_id) -> str`, and
  `soft_record_decision_role(config, record_name) -> str`.

- [ ] Add failing tests for `cot_nq` OFF, `occ_equity_pcr` inactive,
  `btc_funding_basis` research, `cboe_vix9d` auxiliary, FRED vintage hard-gate
  dependencies, NAAIM retired probe, and unknown soft records.
- [ ] Require unknown soft records to default to `strategy`, preventing an
  unregistered source from being optimistically excluded from quality.
- [ ] Implement only the three pure helpers above. Reuse the existing profile
  registry; do not add config keys or duplicate source metadata.
- [ ] Verify the pure contract tests and all external-profile tests pass.
- [ ] Review that this task changes no refresh, quality, scoring, or Web behavior.
- [ ] Commit as `refactor: define decision relevance for data sources`.

### Task 2: Split Decision And Shadow Refresh Lanes

**Files:**
- Modify: `src/hermes_escape_top/scripts/refresh_external.py`
- Create: `ops/refresh_external_shadow.sh`
- Create: `ops/launchagents/com.hermes.external-shadow.plist`
- Modify: `scripts/deploy_to_live.sh`
- Modify: `ops/README.md`
- Modify: `docs/PRODUCTION_RUNBOOK.md`
- Test: `src/hermes_escape_top/tests/test_refresh_external_cli.py`
- Test: `src/hermes_escape_top/tests/test_ops_entrypoints.py`
- Test: `src/hermes_escape_top/tests/test_deploy_to_live.py`

**Interfaces:**
- Consumes: Task 1 relevance helpers.
- Produces:
  `scheduled_source_ids(config, today, lane="decision") -> tuple[str, ...]` and
  CLI mode `--lane decision|shadow`.

- [ ] Add failing tests proving the 06:45/07:05 decision lane excludes disabled,
  inactive, auxiliary, and research sources but includes active strategy,
  hard-gate dependencies, and a due retired NAAIM probe.
- [ ] Add failing tests proving the shadow lane includes active auxiliary/research
  sources only; inactive OCC/COT remain manual and are never scheduled.
- [ ] Implement `decision` as the default lane for existing pre-daily entrypoints.
- [ ] Add a nonblocking 09:20 shadow job for BTC funding and VIX9D. Lock BUSY must
  exit 75, write its own log/evidence, and never affect strategy readiness.
- [ ] Keep explicit `--source <id>` available for manual research collection.
- [ ] Update R6 sync, backup, rollback, first-install, and plist reload paths
  symmetrically for the new shadow job.
- [ ] Run refresh CLI, ops entrypoint, deploy, plist lint, and shell syntax tests.
- [ ] Verify selected decision sources contain no `cot_nq`, `occ_equity_pcr`,
  `btc_funding_basis`, or `cboe_vix9d` on an ordinary weekday.
- [ ] Commit as `fix: separate decision and shadow source refresh`.

### Task 3: Separate Decision Quality From All-Source Quality

**Files:**
- Modify: `src/hermes_escape_top/core/data/quality.py`
- Modify: `src/hermes_escape_top/pipeline.py`
- Modify: `src/hermes_escape_top/core/decision/action_intents.py`
- Modify: `src/hermes_escape_top/core/reporting/system_health.py`
- Modify: `src/hermes_escape_top/web/render.py`
- Test: `src/hermes_escape_top/tests/test_phase1_data_flow.py`
- Test: `src/hermes_escape_top/tests/test_action_confidence_split.py`
- Test: `src/hermes_escape_top/tests/test_health_truth.py`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Consumes: Task 1 soft-record relevance and the existing snapshot/soft-record
  payloads.
- Produces: `data_quality` as decision-grade quality and
  `all_source_data_quality` as the unfiltered operational metric.

- [x] Add a failing test with identical snapshots where a research-only BTC
  proxy lowers `all_source_data_quality` but cannot lower `data_quality` or
  strategy confidence.
- [x] Add failing tests proving strategy/hard-gate proxies and stale inputs still
  lower decision quality, and unknown records remain decision-bearing.
- [x] Extend quality calculation with an optional excluded soft-field set while
  preserving the current default behavior for existing callers.
- [x] Build the excluded field set from soft records and Task 1 policy; do not
  add metadata to scoring snapshots or change the score input hash.
- [x] Populate both metrics in the payload. Health and action confidence consume
  decision quality; the folded all-source panel consumes operational quality.
- [x] Rename Web labels to `策略输入质量` and `全源观测质量`; never present
  research quality as a strategy blocker.
- [x] Verify the current fixture changes from quality 90/overall 92.2 to expected
  decision quality 94/overall 93.4 while all-source remains 90/92.2.
- [x] Run four-date comparison. Scores, statuses, sizing, routing, hard valves,
  reentry, targets, and input hashes must be identical; only allowed reporting
  paths may differ.
- [ ] Commit as `fix: scope strategy confidence to decision inputs`.

### Task 4: Fail Closed On An Implicit Repo Data Root

**Files:**
- Create: `src/hermes_escape_top/core/data/runtime_root.py`
- Modify: `src/hermes_escape_top/cli.py`
- Modify: `src/hermes_escape_top/web/server.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `src/hermes_escape_top/scripts/predeploy_smoke.py`
- Modify: `CONTRIBUTING.md`
- Modify: `docs/PRODUCTION_RUNBOOK.md`
- Test: `src/hermes_escape_top/tests/test_runtime_data_root.py`
- Test: `src/hermes_escape_top/tests/test_predeploy_smoke.py`
- Test: `src/hermes_escape_top/tests/test_next5_runtime_isolation.py`

**Interfaces:**
- Produces:
  `require_explicit_runtime_data_root(operation: str) -> pathlib.Path`.
- The guard applies only to production-like score, dashboard, refresh, and daily
  entrypoints launched from a git checkout. Tests/backtests must pass an explicit
  isolated data root; packaged R6 live continues using its shared symlink/root.

- [x] Add failing tests proving repo `score`, dashboard, refresh, and daily reject
  a missing `HERMES_DATA_DIR` with a clear nonzero exit and no writes.
- [x] Add tests proving isolated tests/backtests and R6 live roots still work.
- [x] Implement the narrow entrypoint guard; do not change `resolve_path()`
  globally because research tooling legitimately uses explicit fixture roots.
- [x] Keep predeploy smoke's live-mirror behavior, but make its selected root
  explicit in output evidence.
- [x] Generate a read-only inventory of package-local ignored runtime files and
  their sizes. Do not delete anything in this code task.
- [x] Run CLI, smoke, runtime isolation, and four-date equivalence tests.
- [ ] Commit as `fix: reject implicit repo runtime data`.

### Task 5: Make Retired And Missing Inputs Explicit

**Files:**
- Modify: `src/hermes_escape_top/web/render.py`
- Modify: `src/hermes_escape_top/core/reporting/system_health.py`
- Modify: `docs/FLAG_REGISTRY.md`
- Create: `docs/history/2026-08-12_naaim_b6_lifecycle_decision.md`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`
- Test: `src/hermes_escape_top/tests/test_health_truth.py`

**Interfaces:**
- Consumes: existing factor `max_score`, missing fields, source lifecycle, and
  decision weight. Produces reporting only.

- [x] Add failing UI tests proving max-score-zero placeholders A2 CNN, B5 social,
  D-M4, and D-M5 appear only in a folded `非计分占位` section and never count as
  strategy missing weight.
- [x] Add failing tests proving NAAIM is labeled `已退役来源，等待 SLO 缺失路径`
  and MSTR B6 is labeled `计分输入缺失 5 分`, not a generic proxy warning.
- [x] Implement reporting changes without editing module registries or config.
- [x] Record the binding decision: keep NAAIM's conservative missing-weight path
  and B6's 5-point missing path until separately pre-registered formal gates.
- [x] Verify score/status/input-hash identity and focused Web/health tests.
- [ ] Commit as `docs: clarify retired and missing decision inputs`.

### Task 6: Instrument Publisher-Aware Freshness

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Modify: FRED and AAII adapters under
  `src/hermes_escape_top/core/data/external_sources/`
- Create: `building/reports/data_quality/FRED_AAII_RELEASE_POLICY_2026_08_12.md`
- Test: `src/hermes_escape_top/tests/test_external_source_profiles.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`
- Test: `src/hermes_escape_top/tests/test_external_source_expected_release.py`

**Interfaces:**
- Produces exact `latest_expected_release_date`, publisher issue/release ID,
  content fingerprint, grace status, and recovery evidence for AAII, Dollar,
  Real Rate, and Net Liquidity.

- [x] First write the source-verification report from official publisher metadata
  and existing 90-day ledgers; do not guess hard-coded weekdays.
- [x] Add failing tests for US holidays, mixed daily/weekly FRED components,
  unchanged official releases, delayed AAII RSS issues, and fallback recovery.
- [x] Derive expected FRED releases from official release metadata/calendar and
  AAII expectations from issue identity, not merely file age.
- [x] Keep new expected-release checks warning-only until each source has at least
  five expected-release samples; existing SLO/fail-closed behavior remains.
- [x] Verify `UNINSTRUMENTED` disappears only for sources with verified calendars.
- [x] Run external failure drill and require network_used=false/live_data_touched=false.
- [ ] Commit as `feat: add publisher-aware freshness evidence`.

### Task 7: Represent Post-Deploy Recertification Honestly

**Files:**
- Modify: `src/hermes_escape_top/core/reporting/system_health.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `ops/morning_acceptance.py`
- Modify: `src/hermes_escape_top/web/health.py`
- Test: `src/hermes_escape_top/tests/test_run_receipt_writer.py`
- Test: `src/hermes_escape_top/tests/test_morning_acceptance.py`
- Test: `src/hermes_escape_top/tests/test_health_truth.py`

**Interfaces:**
- Health reports gain `generator_release_hash` and
  `generator_policy_sha256` evidence fields.
- Morning acceptance may return `PENDING_POST_DEPLOY`, which is neither PASS nor
  FAIL and cannot authorize trading or deployment.

- [x] Add failing tests for an old-code hash-bound report plus a newer live
  release, current dashboard OK, and unchanged official receipt.
- [x] Add tests proving genuine stale market data, bad receipt, audit mismatch,
  or transaction failure remains FAIL even across a deployment.
- [x] Write generator identity into newly generated health reports.
- [x] Return `PENDING_POST_DEPLOY` only when runtime integrity is PASS, the
  official report predates the attested deployment, and current readiness is OK.
- [x] Do not reinterpret or overwrite the immutable old report; the next natural
  scheduled run is the only path from pending to PASS.
- [x] Update Web copy and runbook with the pending state.
- [x] Run morning acceptance, receipt, and health focused tests.
- [ ] Commit as `fix: distinguish post-deploy pending certification`.

### Task 8: Bounded Technical-Debt And Storage Cleanup

**Files:**
- Modify only modules already touched in Tasks 1-7.
- Create: `building/reports/maintenance/REPO_RUNTIME_STORAGE_2026_08_12.json`
- Create: `building/reports/maintenance/EXCEPTION_AUDIT_2026_08_12.md`
- Modify: `.gitignore` only if a demonstrated runtime artifact is not covered.

**Interfaces:**
- Produces reviewable inventories; no live deletion is automatic.

- [x] Inventory the roughly 223 broad production catches and prioritize only
  catches around persistence, refresh, receipt, and deployment boundaries.
- [x] Replace silent pass/continue in touched high-risk paths with typed outcomes
  already supported by ledger/receipt evidence. Do not mass-format or mass-fix.
- [x] List every worktree with branch, dirty state, merged state, and disk size.
- [x] Mark the two missing `/private/tmp` worktrees as prunable metadata; do not
  delete any real worktree until its dirty/merged state is reviewed.
- [x] Inventory repo-local ignored runtime data and the `~/.hermes` git footprint.
- [x] Move the local FRED credential to the existing environment/key mechanism,
  verify the ignored file is not tracked, then delete only the redundant local
  copy after a credential-read smoke check.
- [x] Draft, but do not execute, migration from whole-`~/.hermes` git history to
  a dedicated escape-top deployment ledger. This migration is a later R6 task.
- [x] Run focused tests for every changed catch and `git diff --check`.
- [ ] Commit as `chore: document and bound runtime maintenance debt`.

### Task 9: Final Audit, Single R6 Deployment, And Observation

**Files:**
- Create: `docs/history/2026-08-12_system_relevance_update_handoff.md`
- Create: `building/reports/system_update_2026_08_12/AFTER_EVIDENCE.json`
- Update current architecture/status docs only where code behavior changed.

- [ ] Run all focused suites from Tasks 1-8.
- [ ] Run the full suite; require at least the current 1264 tests plus new tests,
  with zero failures.
- [ ] Run governance; require 7/7 OK, live-policy attestation valid, and
  `ibkr_readonly=true`.
- [ ] Run compileall, severe Ruff rules, changed-file Ruff, shell syntax, plist
  lint, secret scan, live-data scan, and `git diff --check`.
- [ ] Run four-date equivalence. Require all decision outputs/input hashes equal
  and only the approved reporting paths different.
- [ ] Run the external failure drill; require PASS, no network, no live writes.
- [ ] Obtain an independent read-only audit covering source lanes, quality scope,
  data-root refusal, pending acceptance, config safety, and equivalence evidence.
- [ ] Commit and push only after audit approval and a clean worktree.
- [ ] Deploy once with R6, preserve live config, hold the pipeline lock, and do
  not run official daily as deployment verification.
- [ ] Verify VERSION, `/livez`, `/readyz`, official receipt/audit, seven-artifact
  transaction, dashboard default page, launchd jobs, and deploy ledger commit.
- [ ] Observe five natural trading days without manual refresh. Require 06:45 and
  07:05 decision lanes, 09:20 shadow lane, 07:10 daily, 09:00 watchdog, and
  morning acceptance to agree on source roles and freshness.

## Deferred Strategy Work: Not Part Of This Deployment

1. **NAAIM factor retirement candidate:** default-OFF flag, pre-register how A2's
   2 points are removed/normalized, run one formal gate, and archive FAIL without
   retuning.
2. **MSTR B6 decision:** first prove an automated PIT source for market cap,
   BTC holdings, and BTC price. If unavailable, pre-register B6 retirement rather
   than leaving a permanent unnamed gap.
3. **Route turnover research:** reconcile actual user execution costs and cadence
   against 238.0632 turnover and 70.04% route-set-change attribution. Do not add a
   new buffer unless a new, distinct hypothesis is pre-registered.
4. **Historical live-flag recertification:** re-run formal evidence only where old
   live flags still rely on pre-formal-gate reports; one signal, one gate.

## Delivery Order And Estimate

| Batch | Tasks | Engineering estimate | Deployable independently |
|---|---|---:|---|
| A: Evidence truth | 0-3 | 2-3 days | Yes; highest priority |
| B: Runtime isolation | 4-5 | 1-1.5 days | Yes |
| C: Freshness/acceptance | 6-7 | 1.5-2 days | Yes |
| D: Maintenance/audit | 8-9 | 1-2 days plus 5 trading days observation | Final release |

Total implementation estimate: **5.5-8.5 engineering days**, followed by five
natural trading days of observation. Batch A should be completed and reviewed
before any other feature, WebUI enhancement, or strategy experiment begins.
