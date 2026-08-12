# NAAIM Retirement and CFTC TFF Implementation Plan

> Execute test-first. Do not modify `config/config.json`, production scoring,
> routing, or live data.

**Goal:** Retire the structurally unavailable NAAIM public source without hiding
data/evidence failures, and add a research-only CFTC TFF Asset Manager candidate.

## Task 1: Source lifecycle metadata

**Files:**
- Modify `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Modify `src/hermes_escape_top/tests/test_external_source_profiles.py`
- Modify `src/hermes_escape_top/tests/test_refresh_external_cli.py`

1. Add failing tests for post-deadline retirement, subscriber recovery, and
   lifecycle fields.
2. Add lifecycle metadata to `ExternalSourceProfile` and NAAIM's profile.
3. Make retirement the post-deadline default while preserving subscriber-ready
   precedence and evidence fields.
4. Run the focused profile and refresh tests.

## Task 2: Weekly probe and readiness

**Files:**
- Modify `src/hermes_escape_top/scripts/refresh_external.py`
- Modify `src/hermes_escape_top/tests/test_refresh_external_cli.py`

1. Add failing tests proving non-probe-day exclusion, Friday inclusion, retry
   behavior, retired stale nonblocking behavior, and evidence-drift blocking.
2. Filter scheduled refreshes by lifecycle/probe weekday.
3. Keep explicit `--source naaim_exposure` and official imports available for
   controlled diagnostics; only automatic scheduling changes.
4. Run the focused refresh suite.

## Task 3: Health, acceptance, and WebUI truth

**Files:**
- Modify `src/hermes_escape_top/web/health.py`
- Modify `ops/morning_acceptance.py`
- Modify `src/hermes_escape_top/web/external_source_view.py` if needed
- Modify corresponding tests

1. Add failing tests for nonblocking retirement and critical evidence drift.
2. Exclude retired NAAIM staleness from generic soft-source degradation while
   retaining an operations/lifecycle note.
3. Make morning acceptance report retirement as PASS with a recorded note.
4. Ensure the source table exposes the lifecycle without suggesting paid/manual
   action is required.

## Task 4: CFTC TFF research candidate

**Files:**
- Add `src/hermes_escape_top/core/research/cftc_tff_asset_manager.py`
- Add `src/hermes_escape_top/tests/test_cftc_tff_asset_manager_research.py`
- Add a research decision document under `docs/history/`

1. Add failing parser and PIT tests using official-schema fixtures.
2. Parse only selected equity-index rows and compute Asset Manager net/OI.
3. Reject ambiguous markets, nonpositive OI, malformed position fields, and
   publication dates earlier than the report date.
4. Assert the module has no production registration/config dependency.

## Task 5: Governance and verification

**Files:**
- Modify `context.md`
- Modify `docs/PRODUCTION_RUNBOOK.md`
- Modify `docs/FLAG_REGISTRY.md`
- Add `docs/history/2026-08-12_naaim_retirement_cftc_tff_handoff.md`

1. Document retirement, weekly probe, missing-weight behavior, and candidate
   displacement rule.
2. Run focused tests after each task.
3. Run the complete test suite and governance consistency checks.
4. Run four-date payload/input-hash equivalence in an isolated data root.
5. Review the diff for config/flag/scoring changes and prepare external-audit
   evidence. Do not deploy without a separate release decision.
