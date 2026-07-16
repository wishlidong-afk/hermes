# System Evidence Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove six remaining truthfulness and evidence-chain gaps without changing strategy factors, thresholds, routing, or live feature flags.

**Architecture:** Preserve all current compatibility artifacts and interfaces, then add stricter metadata or immutable evidence beside them. Each task is independently testable and follows RED-GREEN verification before the next task begins.

**Tech Stack:** Python 3.11, pytest, pandas, standard-library JSON/hash/time handling, Bash deployment harness.

## Global Constraints

- Do not run daily, refresh live data, connect to IBKR, flip a feature, or deploy while implementing.
- Do not change factor values, thresholds, score normalization, DEFCON routing, or baseline configuration.
- Keep the seven existing morning-acceptance checks; add operational observations without changing their count.
- Preserve compatibility files and existing external-source ledger consumers.
- Use `apply_patch` for manual edits and verify each task before starting the next.

---

### Task 1: Truthful BTC Funding Provenance

**Files:**
- Modify: `src/hermes_escape_top/core/data/crypto.py`
- Create: `src/hermes_escape_top/tests/test_crypto_funding_source.py`

**Interfaces:**
- Consumes: canonical `btc_funding_basis.csv` columns `is_proxy` and `funding_source`.
- Produces: unchanged `SoftDataRecord` shape with row-derived provenance.

- [x] Add failing tests proving a Deribit row is direct with zero quality penalty and a legacy proxy row retains its two-point penalty.
- [x] Run the focused test and confirm the Deribit case fails because the consumer still hardcodes proxy metadata.
- [x] Parse row-level boolean/source metadata conservatively; unknown or legacy metadata remains proxy.
- [x] Run the focused source tests, soft-data quality tests, and a current payload comparison proving factor values/status/routing are unchanged.

### Task 2: Immutable Per-Run Health Evidence

**Files:**
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `src/hermes_escape_top/web/server.py`
- Modify: `ops/morning_acceptance.py`
- Modify: `src/hermes_escape_top/tests/test_run_receipt_writer.py`
- Modify: `src/hermes_escape_top/tests/test_dashboard_workbench.py`
- Modify: `src/hermes_escape_top/tests/test_morning_acceptance.py`

**Interfaces:**
- Produces compatibility `system_health_<as_of>.json/.md` plus immutable `system_health_runs/system_health_<as_of>_<run timestamp>_<input hash>.json/.md`.
- Morning acceptance selects immutable evidence by `as_of`, `input_hash`, and scheduled receipt time, with compatibility fallback for pre-migration releases.

- [x] Add failing tests for two same-as-of runs retaining both immutable reports and for hash-bound acceptance selection.
- [x] Add deterministic filename construction and write both compatibility and immutable artifacts atomically.
- [x] Extend dashboard report discovery to immutable files while preserving current history deduplication.
- [x] Run receipt, dashboard, and acceptance focused suites.

### Task 3: Crash-Safe External Ledger Append

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Modify: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Reuses: `core.data.jsonl.append_jsonl_records` tail repair and fsync behavior.
- Preserves: `append_source_run(...) -> Path` and all reader behavior.

- [x] Add a failing test with a truncated JSON fragment followed by an append.
- [x] Replace direct text append with the shared durable JSONL helper.
- [x] Verify the damaged fragment is removed and both prior complete and new records remain readable.

### Task 4: AAII Channel Reliability

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Modify: `src/hermes_escape_top/web/render.py`
- Modify: `src/hermes_escape_top/tests/test_external_source_aaii.py`
- Modify: `src/hermes_escape_top/tests/test_external_source_runner.py`
- Modify: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Adds optional ledger fields `source_channel`, `fallback_used`, and `primary_failure`.
- Adds reliability fields for per-channel successes and seven-day fallback rescues; legacy records remain valid.

- [x] Add failing tests for public HTML success, RSS rescue metadata, manual import metadata, and daily-deduplicated rescue counts.
- [x] Extract channel metadata from adapter raw evidence into ledger records.
- [x] Surface fallback rescue separately from total source failure in the reliability text.
- [x] Run AAII, runner, ledger, and dashboard focused tests.

### Task 5: Secret-Free Live Config Attestation

**Files:**
- Modify: `scripts/deploy_to_live.sh`
- Modify: `ops/morning_acceptance.py`
- Modify: `src/hermes_escape_top/tests/test_deploy_to_live.py`
- Modify: `src/hermes_escape_top/tests/test_morning_acceptance.py`

**Interfaces:**
- Produces release-local `hermes_escape_top/LIVE_CONFIG_ATTESTATION.json` after the config decision and before smoke/switch.
- Stores hashes and boolean feature differences only; never stores credentials or arbitrary config values.

- [x] Add failing deployment tests for attestation content, allowlisted commit, and rollback.
- [x] Generate attestation from the effective shared live config and repository config.
- [x] Extend `release_identity` acceptance to verify attested SHA256 against current live config.
- [x] Run deployment failure injection, Bash syntax, and morning acceptance tests.

### Task 6: Retention and Market Admission Operational Evidence

**Files:**
- Modify: `ops/morning_acceptance.py`
- Modify: `src/hermes_escape_top/tests/test_morning_acceptance.py`
- Modify: `ops/README.md`

**Interfaces:**
- Adds top-level `operational_observations` while preserving exactly seven primary checks.
- Retention becomes WARN only after its first expected Sunday window or when APPLY evidence is older than eight days.
- Market admission reports consecutive successful dated evidence and declares observation maturity at three days.

- [x] Add failing tests for pre-window pending, post-window missing warning, stale retention warning, and three-day market-admission maturity.
- [x] Read only release attestation, retention report, and dated market-admission evidence.
- [x] Feed observation warnings into the acceptance summary without turning informational states into failures.
- [x] Document semantics and run focused acceptance tests.

### Final Verification

- [x] Run focused tests for all six tasks.
- [x] Run `scripts/system_validation.py` and governance consistency checks.
- [x] Run the complete pytest suite.
- [x] Inspect `git diff --check`, changed-file scope, and live/repo status; do not deploy.

## Execution Result

- Production interpreter compatibility: `/usr/bin/python3` compiled and imported `ops/morning_acceptance.py` successfully.
- Deployment script syntax: `bash -n scripts/deploy_to_live.sh` passed.
- Full regression: `1049 passed in 121.12s`.
- Governance consistency: 4/4 checks OK.
- System validation: 28/28 checks passed.
- No deployment, live-data refresh, IBKR connection, feature flip, or config mutation was performed.
