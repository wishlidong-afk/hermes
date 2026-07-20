# Hermes System Trust Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> and complete tasks strictly in order with RED/GREEN checkpoints.

**Goal:** Implement and independently verify the seven approved trust-hardening
changes without deploying or flipping live behavior.

**Architecture:** Add narrow policy and transaction modules at existing seams.
Keep reporting metadata separate from scoring. Put all strategy changes behind
default-OFF flags and use the existing one-shot formal-gate machinery.

**Tech Stack:** Python 3, pytest, pandas, JSON/JSONL, SQLite, Bash, GitHub Actions.

## Global Constraints

- Never connect to live IBKR or write live/shared data.
- Never edit live config or deploy.
- Use `HERMES_DATA_DIR` isolation for score and gate runs.
- Run one full backtest/formal gate process at a time.
- Do not retune or rerun a failed experiment.

---

### Task 1: Approved Live Configuration Policy

**Files:** create `src/hermes_escape_top/governance/approved_live_config.json`
and `src/hermes_escape_top/governance/live_config_policy.py`; modify `scripts/deploy_to_live.sh`,
`ops/morning_acceptance.py`, governance checks, and their tests.

- [x] Add tests proving an extra/missing feature diff, changed non-feature
  value, changed policy, or violated readonly invariant fails closed.
- [x] Verify the new tests fail for the current self-attestation behavior.
- [x] Implement semantic hashing, exact diff validation, attestation policy
  binding, deployment refusal, and morning revalidation.
- [x] Run deploy, morning-acceptance, and governance focused tests; review diff.

### Task 2: Seven-Artifact Score Transaction

**Files:** modify `core/data/adapters.py`, `core/data/store.py`, `pipeline.py`,
`tests/test_pipeline_transaction.py`, and persistence comparison tooling.

- [x] Add fault tests that include `soft_adapter_snapshot_<as_of>.json`.
- [x] Verify a fault currently changes the snapshot while six artifacts restore.
- [x] Split soft collection from persistence; atomically write inside the score
  transaction and include the dated path in the manifest.
- [x] Run fault matrix, four-date identity, and pipeline tests; review diff.

### Task 3: Source Role And Provenance Contract

**Files:** modify external-source profiles, adapters, runner/ledger, health,
Web reporting, and focused tests.

- [x] Add tests proving a stale research source cannot degrade strategy health
  and every fallback records primary failure and selected provider.
- [x] Add `decision_role` and a normalized provenance record to the source
  policy/runner interfaces.
- [x] Update all active adapters and ledger/status rendering.
- [x] Run external-source, health, and dashboard tests; review diff.

### Task 4: Recoverable History Promotion

**Files:** add `core/data/history_transaction.py`; modify
`scripts/backfill_history.py` and `tests/test_backfill_guard.py`.

- [x] Add deterministic crash-state tests for partial promotion and startup
  recovery, including manifest-before-evidence ordering.
- [x] Implement staged candidates, old-byte backups, operation manifest,
  atomic promotion, commit, and recovery.
- [x] Run history/admission tests and isolated fault injection; review diff.

### Task 5: Route-Set Transition Experiment

**Files:** modify routing/portfolio construction behind
`use_route_set_transition_buffer`; add tests, experiment manifest, flag card,
and one formal-gate result.

- [ ] Add OFF identity and hard-valve non-delay tests before implementation.
- [ ] Implement only the pre-registered 2pp non-risk-leg suppression rule.
- [ ] Run four-date OFF identity and the one-shot formal gate once.
- [ ] Record Candidate-gate-passed or Rejected; do not flip or retune; review.

### Task 6: C/D Trend Ownership Experiment

**Files:** modify module D/scoring behind `use_cd_trend_dedup`; add tests,
experiment manifest, ownership decision, flag card, and one formal-gate result.

- [ ] Add OFF identity and D1/D2 suppression tests before implementation.
- [ ] Implement C-owned MA trend semantics without reweighting thresholds.
- [ ] Run four-date OFF identity and the one-shot formal gate once.
- [ ] Record Candidate-gate-passed or Rejected; do not flip or retune; review.

### Task 7: Maintenance And Final Audit

**Files:** modify `web/server.py`, IBKR/report writers, README/CONTRIBUTING and
current status docs; add `.github/workflows/ci.yml` and focused tests.

- [ ] Add tests for atomic auxiliary writes and absence of retired M4 handlers.
- [ ] Remove unreachable M4 functions and migrate direct writes to safe I/O.
- [ ] Update current architecture/baseline docs and add minimal CI.
- [ ] Run full pytest, governance, compileall, shell syntax, secret/live-data
  scan, and final diff review; present deployment decision without deploying.
