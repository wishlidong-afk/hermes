# AAII/NAAIM Source Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AAII and NAAIM resilient to public-page blocking or subscription changes by adding official file-import fallbacks that still use the ExternalSourceRunner ledger, validation, and promotion path.

**Architecture:** Keep the existing automatic public/official fetchers as primary paths. Add explicit official file-import adapters for AAII and NAAIM, wired through `refresh_external --import-file`, so manual/browser downloads produce the same raw evidence, normalized CSV, validation result, source ledger, and promoted `soft_history` output as automatic fetches. Mirrors are allowed only as corroboration/documented fallback evidence, not as production truth.

**Tech Stack:** Python stdlib, pandas, existing `ExternalSourceRunner`, existing safe CSV write path, pytest.

## Global Constraints

- Do not run official daily as part of this work.
- Do not write to live data during tests; use temp directories and isolated config.
- Do not make mirror data a silent replacement for AAII or NAAIM official data.
- External refresh failures must be explicit in the ledger and must not promote stale data as OK.
- Keep output schemas byte-compatible with current scoring CSVs.

---

### Task 1: AAII Official File Import

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/aaii.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/refresh_external.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_external_source_aaii.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_refresh_external_cli.py`

**Interfaces:**
- Consumes: `parse_aaii_sentiment_xls(path: Path) -> pd.DataFrame`
- Produces: `AaiiSentimentImportAdapter(import_path: Path, seed_path: Path)` and CLI `--source aaii_sentiment --import-file PATH`

- [ ] Add a failing test proving an official AAII spreadsheet import promotes through `run_external_source_refresh`.
- [ ] Add a failing CLI test proving `--import-file` is accepted only with `--source`.
- [ ] Implement import adapter that records `import_path`, file metadata, and base64 content in `raw.json`.
- [ ] Reuse the existing AAII XLS parser and normalize/merge output exactly like automatic AAII rows.
- [ ] Run focused AAII/CLI tests.

### Task 2: NAAIM Official File Import

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/naaim.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/refresh_external.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_external_source_naaim.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_refresh_external_cli.py`

**Interfaces:**
- Consumes: existing NAAIM XLSX row parser.
- Produces: `NaaimExposureImportAdapter(import_path: Path)` and CLI `--source naaim_exposure --import-file PATH`

- [ ] Add a failing test proving downloaded/subscription NAAIM workbook import promotes through `run_external_source_refresh`.
- [ ] Implement import adapter using the same parser and schema as automatic NAAIM.
- [ ] Add CLI dispatch for NAAIM import.
- [ ] Run focused NAAIM/CLI tests.

### Task 3: Operator-Facing Guidance

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/aaii.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/naaim.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/render.py`
- Modify: `/Users/liweishi/Documents/github/hermes/docs/PRODUCTION_RUNBOOK.md`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Consumes: source-run `error_message`.
- Produces: clearer 8766 external-source table hint and runbook commands for official file import.

- [ ] Ensure automatic AAII block message points to `--import-file`.
- [ ] Ensure NAAIM discovery failure mentions official workbook/subscription import.
- [ ] Add concise 8766 hint for AAII/NAAIM manual official-file fallback.
- [ ] Add runbook commands for AAII and NAAIM import.
- [ ] Run focused dashboard/render tests.

### Task 4: Verification and Deployment Readiness

**Files:**
- Test command only.

**Interfaces:**
- Produces: evidence for review/deploy.

- [ ] Run focused tests for external sources, CLI, and dashboard.
- [ ] Run full suite.
- [ ] Review diff for accidental scoring/live-data changes.
- [ ] If clean and requested, commit/push/deploy with existing atomic deploy script.

## Self-Review

- Spec coverage: AAII import, NAAIM import, CLI, operator guidance, and verification are covered.
- Placeholder scan: no TBD/TODO placeholders.
- Scope check: mirrors are intentionally not promoted to production truth in this slice; they can be added later as mismatch/corroboration telemetry without changing scoring data.
