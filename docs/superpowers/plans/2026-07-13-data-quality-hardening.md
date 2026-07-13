# Hermes Data Quality Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every active strategy input one canonical writer, one runtime freshness policy, auditable PIT/provenance evidence, honest decision coverage, and an independent OHLCV shadow witness.

**Architecture:** Deepen `ExternalSourceRunner` rather than adding another refresh framework. `SourcePolicy` supplies one reporting interface over config-owned SLO values; runner promotions bind canonical hashes to ledger evidence; the daily scheduler consumes precheck evidence instead of unconditionally refetching. A separate `MarketDataWitness` module compares Alpaca daily bars with canonical local history but cannot promote data or change scoring.

**Tech Stack:** Python 3.11, pandas, stdlib HTTP/JSON, existing safe I/O and pipeline lock, pytest.

## Global Constraints

- No scoring threshold, valve, sizing or routing behavior changes.
- Any OHLCV provider change remains shadow-only and outside `input_hash`.
- No network access in tests and no test writes to live data.
- External refresh failure preserves canonical bytes.
- Paid AAII/NAAIM credentials are not inferred or stored in git.
- Existing untracked reports remain untouched.
- Every behavior change follows RED -> GREEN -> focused regression -> full suite.

---

### Task 1: Config-Backed Source Policy Interface

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Modify: `src/hermes_escape_top/scripts/refresh_external.py`
- Test: `src/hermes_escape_top/tests/test_external_source_profiles.py`

**Interfaces:**
- Produces: `effective_source_profile(config: dict, source_id: str) -> ExternalSourceProfile | None`
- Produces: profile fields `feature_flag`, `decision_weight`, `automation_mode`, `pit_rule`, `migration_deadline`, `max_age_days`, `warn_age_days`
- Invariant: effective `max_age_days` comes from `config.soft_data_slo`, never a second production constant.

- [ ] **Step 1: Write failing tests**

```python
def test_effective_profile_uses_config_slo_as_single_runtime_truth():
    cfg = {"soft_data_slo": {"default_max_age_days": 13, "max_age_days": {"dollar": 6}}}
    profile = effective_source_profile(cfg, "dollar")
    assert profile.max_age_days == 6
    assert profile.warn_age_days == 4


def test_naaim_profile_declares_subscription_migration_deadline():
    profile = effective_source_profile({}, "naaim_exposure")
    assert profile.automation_mode == "official_file"
    assert profile.migration_deadline == "2026-08-01"
```

- [ ] **Step 2: Verify RED**

Run: `PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_profiles.py -q`

Expected: missing effective policy interface/metadata assertions fail.

- [ ] **Step 3: Implement the minimal immutable profile metadata plus config merge**
- [ ] **Step 4: Route `refresh_external.status()` through effective profiles**
- [ ] **Step 5: Verify focused tests GREEN**

---

### Task 2: Bind Canonical Artifacts To Ledger Promotions

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/registry.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Produces ledger fields `canonical_sha256`, `canonical_latest_as_of`, `fetched_at`, `pit_rule`, `source_url`
- Produces status fields `evidence_status` and `evidence_detail`
- `source_status(...)[source_id]["evidence_status"]` is `MATCH`, `MISSING_CANONICAL`, or `EVIDENCE_DRIFT`.

- [ ] **Step 1: Write a failing drift test**

```python
def test_source_status_detects_canonical_bytes_changed_after_promotion(tmp_path):
    run_external_source_refresh(spec, GoodAdapter(), archive)
    spec.target_path.write_text("date,value\n2026-07-10,999\n", encoding="utf-8")
    row = source_status(archive, [spec])[spec.source_id]
    assert row["evidence_status"] == "EVIDENCE_DRIFT"
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Compute canonical hash after atomic promotion and persist it in the successful ledger row**
- [ ] **Step 4: Compare the current canonical file against latest successful promotion in `source_status`**
- [ ] **Step 5: Add a semantic-validator hook to `ExternalSourceSpec` and prove validation failure preserves canonical bytes**
- [ ] **Step 6: Verify focused tests GREEN**

---

### Task 3: Remove Duplicate Writers And Reuse Morning Precheck

**Files:**
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `src/hermes_escape_top/scripts/refresh_external.py`
- Modify: `ops/refresh_external_precheck.sh`
- Modify: `docs/PRODUCTION_RUNBOOK.md`
- Test: `src/hermes_escape_top/tests/test_run_daily_external_sources.py`
- Test: `src/hermes_escape_top/tests/test_ops_entrypoints.py`
- Test: `src/hermes_escape_top/tests/test_refresh_external_cli.py`

**Interfaces:**
- Produces: `refresh_retry_sources(config, today=None) -> dict`
- Produces CLI `--retry-needed`
- Daily helper consumes a same-day precheck artifact when present; it does not invoke FRED/AAII legacy writers.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_legacy_refresh_does_not_invoke_runner_owned_fred_or_aaii(monkeypatch):
    calls = capture_subprocess_modules(monkeypatch)
    refresh_soft_data()
    assert "backfill_soft_data --only fred" not in calls
    assert "backfill_soft_data --only fred_risk" not in calls
    assert "refresh_aaii_public" not in calls


def test_retry_needed_only_runs_failed_or_unready_sources(monkeypatch):
    calls = []
    monkeypatch.setattr(
        refresh_external,
        "status",
        lambda config, today=None: {
            "dollar": {
                "status": "OK",
                "freshness_status": "OK",
                "evidence_status": "MATCH",
                "latest_attempt_finished_at": "2026-07-13T06:45:00+08:00",
            },
            "aaii_sentiment": {
                "status": "OK",
                "freshness_status": "OK",
                "evidence_status": "MATCH",
                "latest_attempt_status": "FETCH_ERROR",
                "latest_attempt_finished_at": "2026-07-13T06:45:00+08:00",
            },
        },
    )
    monkeypatch.setattr(
        refresh_external,
        "refresh_source",
        lambda source_id, config, auto_import=True: calls.append(source_id)
        or {"source_id": source_id, "status": "OK"},
    )
    refresh_external.refresh_retry_sources({}, today=date(2026, 7, 13))
    assert calls == ["aaii_sentiment"]
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Remove FRED and AAII from the legacy daily writer block**
- [ ] **Step 4: Implement retry-needed selection from same-day ledger/canonical evidence**
- [ ] **Step 5: Make 06:45 full refresh, 07:05 retry-needed, and daily reuse a recent valid precheck**
- [ ] **Step 6: Verify focused orchestration tests and `bash -n` GREEN**

---

### Task 4: Migrate Remaining Soft Sources Behind Runner

**Files:**
- Create: `src/hermes_escape_top/core/data/external_sources/market_soft.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/__init__.py`
- Modify: `src/hermes_escape_top/scripts/refresh_external.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Test: `src/hermes_escape_top/tests/test_external_source_market_soft.py`
- Test: `src/hermes_escape_top/tests/test_run_daily_external_sources.py`

**Interfaces:**
- Produces adapters/specs for `cboe_equity_pcr`, `cot_nq`, `occ_equity_pcr`, and `btc_funding_basis`.
- Adapters reuse existing fetch/parse functions but return normalized frames; only runner promotes canonical files.

- [ ] **Step 1: Add failing adapter tests with injected fetch functions**

```python
def test_cboe_adapter_rejects_ratio_that_disagrees_with_volumes(tmp_path):
    adapter = CboePcrAdapter(seed_path=seed, fetch_page=lambda: bad_page)
    run = run_external_source_refresh(spec, adapter, archive)
    assert run.status == "VALIDATION_ERROR"
    assert target.read_bytes() == before
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement CBOE and COT adapters first, including semantic bounds and PIT publish dates**
- [ ] **Step 4: Implement OCC and BTC micro adapters, preserving current schemas and provider annotations**
- [ ] **Step 5: Register sources and remove their direct daily subprocess writers**
- [ ] **Step 6: Verify each adapter and daily orchestration GREEN**

---

### Task 5: Decision Input Coverage

**Files:**
- Modify: `src/hermes_escape_top/core/data/quality.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `src/hermes_escape_top/web/render.py`
- Test: `src/hermes_escape_top/tests/test_data_quality.py`
- Test: `src/hermes_escape_top/tests/test_system_health_report.py`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Produces: `decision_input_coverage(scores: dict) -> dict`
- Output contains `coverage_pct`, `available_weight`, `active_weight`, and `missing_by_symbol`.
- Existing `DataQuality.overall_score` remains unchanged.

- [ ] **Step 1: Write failing weighted-coverage tests**

```python
def test_decision_coverage_uses_actual_missing_weight_from_scores():
    result = decision_input_coverage({
        "MSTR": {"missing_analysis": {"missing_weight": 4, "effective_max_score": 96}},
        "FNGU": {"missing_analysis": {"missing_weight": 0, "effective_max_score": 100}},
    })
    assert result["coverage_pct"] == 98.0
```

- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement report-only calculation from scored missing evidence**
- [ ] **Step 4: Attach it to system-health evidence, not the scoring input hash**
- [ ] **Step 5: Render market completeness, provenance, timeliness and decision coverage separately**
- [ ] **Step 6: Verify focused report/render tests GREEN**

---

### Task 6: OHLCV Shadow Witness

**Files:**
- Create: `src/hermes_escape_top/core/data/market_witness.py`
- Create: `src/hermes_escape_top/scripts/check_market_witness.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Test: `src/hermes_escape_top/tests/test_market_witness.py`
- Test: `src/hermes_escape_top/tests/test_run_daily_market_witness.py`

**Interfaces:**
- Produces: `compare_market_witness(canonical: pd.DataFrame, witness: pd.DataFrame, symbol: str) -> WitnessResult`
- Produces: `refresh_market_witness(as_of, config) -> dict`, writing only `archive/market_witness_latest.json`.
- Result statuses: `MATCH`, `DATE_MISMATCH`, `PRICE_MISMATCH`, `VOLUME_MISMATCH`, `NO_WITNESS`, `FETCH_ERROR`.

- [ ] **Step 1: Write failing pure comparison tests for exact match, split-adjustment mismatch and unsupported symbol**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Implement pure comparison with explicit tolerances and no promotion method**
- [ ] **Step 4: Add Alpaca daily-bar adapter using existing secret loader; tests inject transport**
- [ ] **Step 5: Run witness after canonical history refresh as a nonblocking auxiliary step**
- [ ] **Step 6: Prove four-date score payload/input hashes are unchanged**

---

### Task 7: Migration And Reliability Telemetry

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/profiles.py`
- Modify: `src/hermes_escape_top/web/render.py`
- Modify: `docs/PRODUCTION_RUNBOOK.md`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Produces reliability fields `success_rate_30d`, `success_rate_90d`, `consecutive_failures`, `last_success_at`, `migration_status`.
- NAAIM becomes `MIGRATION_DUE`; AAII becomes `ACTION_REQUIRED` only when its expected issue is overdue and no official artifact is ready.

- [ ] **Step 1: Write failing rolling reliability and migration-state tests**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Aggregate ledger evidence without counting multiple same-day retries as independent publisher failures**
- [ ] **Step 4: Add migration/action states and concise WebUI operations copy**
- [ ] **Step 5: Document official-file drop workflow and credential/licensing boundary**
- [ ] **Step 6: Verify focused tests GREEN**

---

### Task 8: PIT Evidence And Final Verification

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/fred.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Modify: `context.md`
- Create: `docs/history/2026-07-13_data_quality_hardening_handoff.md`
- Test: `src/hermes_escape_top/tests/test_external_source_fred.py`

**Interfaces:**
- FRED raw evidence includes query `realtime_start`, `realtime_end`, retrieval time and `pit_rule`; normalized scoring schema stays unchanged.

- [ ] **Step 1: Write failing FRED evidence metadata test**
- [ ] **Step 2: Verify RED**
- [ ] **Step 3: Add metadata without changing normalized CSV bytes**
- [ ] **Step 4: Run all focused tests from Tasks 1-7**
- [ ] **Step 5: Run full suite**
- [ ] **Step 6: Run four-date byte-identical replay and persistence preservation tests**
- [ ] **Step 7: Run read-only live canaries and `ops/morning_acceptance.py`; do not refresh live data during verification**
- [ ] **Step 8: Self-review the full diff, document residual paid-provider and unsupported-index risks, then present deployment decision**

## Self-Review

- Spec coverage: source SSOT, single writer, selective retry, remaining runner migrations, decision coverage, shadow OHLCV, subscription migration, PIT and reliability are each assigned to a task.
- Placeholder scan: no implementation requirement is deferred without an explicit external credential/license boundary.
- Interface consistency: status fields and result states use the names defined above throughout the plan.
- Safety: no task permits shadow market data to promote or alter scoring.
