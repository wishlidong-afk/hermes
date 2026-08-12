# Hermes System Update Evidence

Captured on 2026-08-12 before any implementation change in Tasks 1-9.

The directory now also contains the Task 9 candidate evidence. The immutable
before anchor remains unchanged; `AFTER_EVIDENCE.json`,
`FINAL_FOUR_DATE_EQUIVALENCE.json`, and `FINAL_EXTERNAL_FAILURE_DRILL.json`
record the final pre-release candidate checks.

## Purpose

This directory is the immutable comparison anchor for the system-relevance and
data-trust update. It answers three separate questions:

1. Was production healthy before the change?
2. Which external sources were actually decision-bearing, and which were only
   auxiliary, research, inactive, or retired?
3. Did a later change alter a decision, routing result, position target, reentry
   state, input hash, or persisted business artifact?

The capture was read-only. It did not run an official daily, refresh market or
external data, connect to IBKR, or write to live data.

## Files

- `BEFORE_EVIDENCE.json`: human-readable production, source, decision, and
  verification snapshot. It also defines the exact allowed and protected JSON
  paths for later comparisons.
- `FOUR_DATE_BEFORE_EQUIVALENCE.json`: strict isolated replay of the current
  source tree against itself on four dates. It compares the normalized full
  score payload and seven persisted business artifacts on each date.

## Evidence Hashes

```text
b991e141f3b7332a426c95d93745768affde27945dab4d73711ecb0359e3c23b  BEFORE_EVIDENCE.json
c9f40f54be236fef5db6c61b0d24ec3edcbf21d3de5ba751cc41b593039aaa5e  FOUR_DATE_BEFORE_EQUIVALENCE.json
724c6076a4420e23c1053ab2fa2aad05b2bbd12d60e3289b1bb77615556e3c79  docs/superpowers/plans/2026-08-12-system-relevance-and-data-trust-update.md
```

The evidence JSON does not contain its own hash because that would be
self-referential. This README records the hash after the final JSON
serialization.

## Acceptance Result

- Repo HEAD: `c6aaa144902ea885f61fac98dac0e800c8de0ac7`
- Live VERSION: `c6aaa14 20260812_161823`
- Live `/readyz`: HTTP 200, strategy readiness `OK`
- Official scheduled receipt: `OK`, `as_of=2026-08-11`
- Scheduled audit input hash:
  `ca06101ead2616d8069970342d4cdbe9c59cfa4cebb9ba8507c88b2327666e27`
- Latest score transaction: `COMMITTED`, seven artifacts
- Governance: `7/7 OK`
- Full suite: `1264 passed`
- Four-date equivalence: `all_equal=true`, four valid input hashes, seven
  artifacts per date

The first attempt to invoke the full suite with the production managed runtime
showed that runtime intentionally does not install pytest. The suite was then
run with the repository's standard development environment. Production runtime
dependency compatibility had already been checked separately.

## Current Source-Relevance Finding

The ordinary Wednesday refresh schedule contains 13 sources. Four are not
active decision inputs:

- `cot_nq`: strategy source with its feature OFF
- `occ_equity_pcr`: inactive research source
- `btc_funding_basis`: active research source with decision weight 0
- `cboe_vix9d`: active auxiliary source with decision weight 0

`naaim_exposure` is a retired strategy source whose certified history remains
frozen; only the Friday lifecycle probe is scheduled. The market-admission gate
is a decision hard gate outside the external-source registry. Exact FRED vintage
sources are configured out because `use_fred_vintage_pit=false`.

## Comparison Contract

Tasks 1-8 may change reporting-only fields under these paths:

```text
data_quality
all_source_data_quality
data_quality_breakdown
decision_layers.*.strategy_confidence
health
system_health_report
acceptance
```

They must not change scores, score statuses, module or factor scores, missing
weights, hard valves, sizing, routing, reentry, portfolio targets, action
destinations, input hashes, or any of the seven business artifacts. A difference
outside the allowlist blocks the next task and deployment.

## Recheck

From the repository root:

```bash
python3 -m json.tool building/reports/system_update_2026_08_12/BEFORE_EVIDENCE.json >/dev/null
python3 -m json.tool building/reports/system_update_2026_08_12/FOUR_DATE_BEFORE_EQUIVALENCE.json >/dev/null
shasum -a 256 building/reports/system_update_2026_08_12/BEFORE_EVIDENCE.json \
  building/reports/system_update_2026_08_12/FOUR_DATE_BEFORE_EQUIVALENCE.json
```

The isolated replay command and its normalization contract are implemented by
`scripts/compare_pipeline_persistence.py`. It clones only history and soft
history into temporary data roots; it does not write to live data.

## Task 3 Quality Split

- `TASK3_CURRENT_QUALITY_SPLIT.json` proves the current fixture now reports
  decision quality `94 / 93.4` while all-source quality remains `90 / 92.2`.
- `TASK3_FOUR_DATE_EQUIVALENCE.json` proves all protected decision outputs and
  all four input hashes remain equal to Task 2.
- Five transaction artifacts are raw-equal. `audit_log.jsonl` and
  `hermes_state.sqlite` change only because they embed the reporting payload;
  after removing the documented quality/confidence reporting paths, all seven
  artifacts are equal. Calling all seven raw-byte-identical would be false.

## Task 4 Runtime Root Refusal

- `TASK4_RUNTIME_ROOT_EVIDENCE.json` records real-process refusal for repo
  score, dashboard/Web refresh service, and daily entrypoints when
  `HERMES_DATA_DIR` is absent. Every case exits before runtime writes.
- `TASK4_REPO_RUNTIME_INVENTORY.json` is a read-only path-and-size inventory of
  2,144 ignored package-local runtime files (619,209,329 bytes). No file was
  deleted or edited.
- `TASK4_FOUR_DATE_SELF_EQUIVALENCE.json` is a fresh isolated deterministic
  replay. Its four input hashes exactly match Task 3. This is deliberately
  described as self-replay plus hash continuity, not as an independent
  source-tree before/after comparison.
- Repo predeploy smoke passed against the explicit R6 live-mirror root and now
  records that selected root in its JSON result.

## Task 5 Input Lifecycle Reporting

- `TASK5_LIFECYCLE_EVIDENCE.json` records the binding reporting distinction:
  retired NAAIM, the scored MSTR B6 five-point gap, and four zero-point
  placeholders are three different states.
- `TASK5_FOUR_DATE_SELF_EQUIVALENCE.json` is a fresh isolated replay. For every
  date, the full payload hash, all seven artifacts, and `input_hash` equal Task
  4, proving the change stayed in Web/health reporting.
- System health remains exactly 20 dimensions. Lifecycle evidence is attached
  to the existing `factor_scores_present` dimension instead of inventing a
  twenty-first dimension.
- The binding rationale is in
  `docs/history/2026-08-12_naaim_b6_lifecycle_decision.md`.

## Task 6 Publisher-Aware Freshness

- `../data_quality/FRED_AAII_RELEASE_POLICY_2026_08_12.md` binds Dollar to
  FRED release 17, Real Rate to release 18, Net Liquidity to releases 20 and
  379, and AAII to its verified official issue sequence. No fixed weekday is
  used for these four sources.
- Publisher observations and expectations are distinct ledger fields. AAII's
  inferred next issue date is never represented as an already published issue.
- Expected-release reliability is warning-only and remains
  `INSUFFICIENT_EVIDENCE` below five matured samples. Sources lacking verified
  publisher evidence remain `UNINSTRUMENTED`; their existing age SLO and
  fail-closed validation are unchanged.
- `TASK6_EXTERNAL_FAILURE_DRILL.json` records 13/13 isolated scenarios passing
  with `network_used=false` and `live_data_touched=false`.
- `TASK6_FOUR_DATE_SELF_EQUIVALENCE.json` is a fresh isolated replay. All seven
  business artifacts, payloads, statuses, and input hashes are equal for four
  dates, and its complete `dates` object equals Task 5.
- Verification: 220 focused tests and 1,317 full-suite tests passed; governance
  is 7/7 OK, compileall passed, and `git diff --check` passed.

## Task 7 Post-Deploy Recertification

- New immutable health reports bind their generator to both the release hash
  and approved live-policy SHA256. Missing or mismatched live attestation fails
  report generation instead of creating unbound evidence.
- Morning acceptance now distinguishes `PENDING_POST_DEPLOY` from both PASS and
  FAIL. Pending never authorizes trading or another deployment, including after
  a same-hash redeploy; only the next natural scheduled run can certify it.
- Pending is allowed only when runtime integrity passes, the selected immutable
  report predates the current attestation, and the live strategy layer is OK.
  Stale market data, receipt/audit mismatch, or transaction failure remains
  FAIL and takes precedence in both acceptance and Web copy.
- `TASK7_POST_DEPLOY_CERTIFICATION_EVIDENCE.json` records the state contract and
  verification. `TASK7_FOUR_DATE_SELF_EQUIVALENCE.json` is a fresh isolated
  replay; all dates equal internally and its complete `dates` object equals
  Task 6, including all four input hashes and seven business artifacts.
- Verification: 179 focused tests and 1,330 full-suite tests passed; governance
  is 7/7 OK, compileall passed, and `git diff --check` passed. Ruff was not run
  because it is not installed in the project runtime venv; no dependency was
  changed merely to add a checker.

## Task 8 Bounded Maintenance

- `../maintenance/EXCEPTION_AUDIT_2026_08_12.md` inventories 246 broad catches
  across 69 production files after remediation. Six persistence, receipt,
  admission, or predeploy evidence paths now emit typed outcomes; no mass catch
  rewrite was attempted.
- `../maintenance/REPO_RUNTIME_STORAGE_2026_08_12.json` lists all 15 worktree
  records, including two missing `/private/tmp` entries marked metadata-prunable.
  No real worktree or runtime file was deleted.
- The ignored, untracked repository FRED-key copy was removed only after its hash
  matched the existing environment mechanism and a post-delete production
  resolver smoke passed. Process environment and explicit config remain above
  the `~/.hermes/.env` fallback. Live/shared legacy copies were not touched.
- Migration away from the 1.19-GiB whole-`~/.hermes` Git pack is drafted as a
  standalone, manifest-only escape-top deployment ledger; it was not executed.
- `TASK8_FOUR_DATE_SELF_EQUIVALENCE.json` is internally equal and its complete
  `dates` object equals Task 7. `TASK8_MAINTENANCE_EVIDENCE.json` records the
  complete verification contract.
- Verification: 200 focused tests and 1,338 full-suite tests passed; governance
  is 7/7 OK, compileall passed, and `git diff --check` passed.

## Task 9 Final Candidate Gate

- `AFTER_EVIDENCE.json` consolidates the live-config source lanes, decision/all-
  source quality split, runtime/lifecycle contracts, and every final gate.
- `FINAL_FOUR_DATE_EQUIVALENCE.json` compares a read-only archive of git
  `c6aaa144902ea885f61fac98dac0e800c8de0ac7` with the current candidate. It
  binds both source-tree manifests, the complete 74-file seed manifest, the
  comparator hash, and the Python/numpy/pandas runtime. The
  `decision-quality-v1` contract is `all_equal=true` on all four dates; strict
  differences are limited to the approved reporting payload and the two
  persistence artifacts that embed it (`audit_log.jsonl` and
  `hermes_state.sqlite`).
- `FINAL_EXTERNAL_FAILURE_DRILL.json` records 13/13 isolated scenarios passing
  with no network and no live write.
- Fresh final verification: 478 Task 1-8 focused tests, 260 first-remediation
  tests, 218 second-remediation tests, 243 final-remediation tests, 1,348
  full-suite tests, 7/7 governance,
  compileall, severe Ruff, shell syntax, plist lint, secret/live-data scans,
  and diff hygiene passed. Pinned
  default Ruff findings remain 39 in both HEAD and candidate, with zero
  findings in new files; this is zero new lint debt, not a claim that the
  historical repository is fully lint-clean.
- The first independent review found three P1 gaps and one P2 evidence gap. A
  second review found three more P1 integration gaps and one P3 defense gap:
  daily-plist deployment, run-type override, auxiliary acceptance blocking, and
  refresh-run lane filtering. A third review found argparse's long-option
  abbreviation could still accept `--run-ty scheduled`; the daily parser now
  disables abbreviation and has a failing-then-passing regression test. These
  findings have regression-tested remediations. Final independent review found
  no P0/P1/P2/P3 issue and approved commit/push. Deployment and the five-
  trading-day natural observation remain separate gates and are not represented
  as complete here.
