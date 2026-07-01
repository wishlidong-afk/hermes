# External Data Daily Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FRED external-data bundle (`dollar`, `real_rate`, `fred_net_liquidity`) run automatically before each daily package run, and make 8766 explain the latest external-source automation status.

**Architecture:** Reuse the existing `ExternalSourceRunner` and `refresh_external.SOURCE_IDS`; do not create a second fetch path. The daily wrapper treats each external refresh as non-fatal and writes all outcomes to the source-run ledger. The Web health layer reads `payload["external_source_status"]` and reports automation failures separately from scoring failures.

**Tech Stack:** Python stdlib, existing `pipeline_lock`, existing JSONL source-run ledger, pytest.

## Global Constraints

- Do not change `pipeline.py` or `config/config.json`.
- Do not write official run records from Web single-source refreshes.
- Daily external refresh is allowed to promote only validated source CSVs through `ExternalSourceRunner`.
- External source failure must keep cached soft-history data and must not abort `run_daily`.
- Tests must be red before implementation and full suite must pass before commit.

---

### Task 1: Daily FRED-Bundle External Refresh Preflight

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/run_daily_package.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_run_daily_external_sources.py`

**Interfaces:**
- Consumes: `hermes_escape_top.scripts.refresh_external.refresh_source(source_id: str) -> dict`
- Produces: `refresh_external_sources() -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
from hermes_escape_top.scripts import run_daily_package as rdp


def test_refresh_external_sources_runs_fred_bundle_without_raising(monkeypatch):
    calls = []
    monkeypatch.setattr(
        rdp.refresh_external,
        "refresh_source",
        lambda source: calls.append(source) or {"source_id": source, "status": "OK"},
    )

    out = rdp.refresh_external_sources()

    assert calls == list(rdp.refresh_external.SOURCE_IDS)
    assert [row["source_id"] for row in out] == list(rdp.refresh_external.SOURCE_IDS)


def test_refresh_external_sources_keeps_daily_alive_on_single_source_failure(monkeypatch):
    def flaky(source):
        if source == "real_rate":
            raise RuntimeError("fred timeout")
        return {"source_id": source, "status": "OK"}

    monkeypatch.setattr(rdp.refresh_external, "refresh_source", flaky)

    out = rdp.refresh_external_sources()

    by_source = {row["source_id"]: row for row in out}
    assert by_source["dollar"]["status"] == "OK"
    assert by_source["real_rate"]["status"] == "ERROR"
    assert "fred timeout" in by_source["real_rate"]["error"]
    assert by_source["fred_net_liquidity"]["status"] == "OK"
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_run_daily_external_sources.py -q
```

Expected: FAIL because `refresh_external_sources` does not exist.

- [ ] **Step 3: Implement minimal daily helper**

Add `from hermes_escape_top.scripts import refresh_external` and:

```python
def refresh_external_sources() -> list[dict]:
    source_ids = tuple(refresh_external.SOURCE_IDS)
    print(f"[M4-1a] Refreshing external source ledger sources ({', '.join(source_ids)})...")
    runs = []
    for source_id in source_ids:
        try:
            run = refresh_external.refresh_source(source_id)
            runs.append(run)
            print(f"[M4-1a] {source_id} external refresh {run.get('status')} latest={run.get('latest_promoted_as_of')}")
        except Exception as exc:
            run = {"source_id": source_id, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
            runs.append(run)
            print(f"[M4-1a] WARNING: {source_id} external refresh failed ({exc!r}); keeping cached data.")
    return runs
```

Call it inside `_execute_daily` before `refresh_soft_data()`, wrapped non-fatally.

- [ ] **Step 4: Run tests to verify green**

Run the same pytest command. Expected: PASS.

---

### Task 2: Health Explains External Source Automation Failures

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/health.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_health_truth.py`

**Interfaces:**
- Consumes: `payload["external_source_status"]` mapping, already attached by `web.server`
- Produces: health checks with labels `外部数据源刷新失败` or `外部数据源未自动刷新`

- [ ] **Step 1: Write failing tests**

```python
def test_external_source_failure_degrades_with_reason():
    payload = _payload()
    payload["external_source_status"] = {
        "dollar": {"source_id": "dollar", "status": "FETCH_ERROR", "error_message": "FRED 503"}
    }

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any("外部数据源刷新失败" in check["label"] and "dollar" in check["detail"] for check in health["checks"])


def test_missing_external_source_ledger_degrades_but_not_critical():
    payload = _payload()
    payload["external_source_status"] = {"dollar": {"source_id": "dollar", "status": "MISSING"}}

    health = _health(payload)

    assert health["level"] == "DEGRADED"
    assert any("外部数据源未自动刷新" in check["label"] for check in health["checks"])
```

- [ ] **Step 2: Run tests to verify red**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_health_truth.py::test_external_source_failure_degrades_with_reason src/hermes_escape_top/tests/test_health_truth.py::test_missing_external_source_ledger_degrades_but_not_critical -q
```

Expected: FAIL because health currently ignores `external_source_status`.

- [ ] **Step 3: Implement minimal health checks**

In `compute_health`, read `external_sources = payload.get("external_source_status") or {}` and add DEGRADED checks:

```python
for source_id, row in external_sources.items():
    if not isinstance(row, dict):
        continue
    status = str(row.get("status") or "")
    if status == "OK":
        continue
    if status == "MISSING":
        add("DEGRADED", "外部数据源未自动刷新", str(source_id))
    else:
        detail = f"{source_id}: {status} {row.get('error_message') or row.get('error') or ''}".strip()
        add("DEGRADED", "外部数据源刷新失败", detail[:160])
```

- [ ] **Step 4: Run tests to verify green**

Run the same focused pytest command. Expected: PASS.

---

### Task 3: Verification And Delivery

**Files:**
- All files above.

**Interfaces:**
- No new public API beyond `refresh_external_sources()`.

- [ ] **Step 1: Run related tests**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_run_daily_external_sources.py src/hermes_escape_top/tests/test_health_truth.py src/hermes_escape_top/tests/test_phase15_integration.py src/hermes_escape_top/tests/test_dashboard_workbench.py -q
```

- [ ] **Step 2: Run full suite**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-01-external-data-daily-health.md src/hermes_escape_top/scripts/run_daily_package.py src/hermes_escape_top/web/health.py src/hermes_escape_top/tests/test_run_daily_external_sources.py src/hermes_escape_top/tests/test_health_truth.py
git commit -m "feat: refresh external fred bundle during daily run"
```

---

## Self-Review

- Spec coverage: covers daily preflight and health explanation only.
- Placeholder scan: no TBD/TODO/implement later placeholders.
- Type consistency: `refresh_external_sources() -> list[dict]` is used only by daily wrapper and tests.
