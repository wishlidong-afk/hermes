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

---

### Addendum: AAII ExternalSourceRunner Probe

**Files:**
- Add: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/aaii.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/refresh_external.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/render.py`
- Tests: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_external_source_aaii.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_refresh_external_cli.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Behavior:**
- `aaii_sentiment` joins `refresh_external.SOURCE_IDS` and attempts to refresh `soft_history/aaii_sentiment.csv` through `ExternalSourceRunner`.
- The adapter reads AAII's official public sentiment results page, parses the recent rendered table, merges rows into the existing seeded history, and recomputes the existing AAII percentile columns.
- The public page is treated as a recent-row probe, not a full-history authority. Existing seeded history remains necessary for rolling percentiles.
- Output columns stay compatible with existing scoring: `date`, `publish_date`, `aaii_bull`, `aaii_bear`, `aaii_bull_bear_spread`, `aaii_bull_pctl`, `aaii_spread_pctl`.
- 8766 external-source operations table renders `aaii_sentiment` with its own refresh button.

**Source Risk:**
- AAII's official public page is currently visible in a browser, but Python fetches can be blocked by Imperva/anti-bot interstitials. A blocked page must surface as source-run `FETCH_ERROR` and health DEGRADED while keeping cached soft-history data; it must not silently promote stale data as fresh.
- If AAII keeps blocking non-browser automation, the next increment should be a manual import path for a downloaded AAII CSV/XLS file through the same runner.

**Verification:**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_aaii.py src/hermes_escape_top/tests/test_refresh_external_cli.py::test_refresh_external_source_aaii_calls_runner src/hermes_escape_top/tests/test_refresh_external_cli.py::test_refresh_external_cli_accepts_aaii src/hermes_escape_top/tests/test_dashboard_workbench.py::test_trust_zone_uses_external_source_ledger_status -q
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
from hermes_escape_top.core.data.external_sources.aaii import AaiiSentimentAdapter, aaii_sentiment_spec
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh

seed = Path("src/hermes_escape_top/data/soft_history/aaii_sentiment.csv")
with TemporaryDirectory() as tmp:
    root = Path(tmp)
    target = root / "soft_history" / "aaii_sentiment.csv"
    target.parent.mkdir(parents=True)
    shutil.copy2(seed, target)
    run = run_external_source_refresh(aaii_sentiment_spec(target_path=target), AaiiSentimentAdapter(seed_path=target), root / "archive")
    print(run.status, run.latest_promoted_as_of, run.error_type, run.error_message)
PY
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

---

### Addendum: Refresh All External Sources

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/refresh_external.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/server.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/render.py`
- Tests: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_refresh_external_cli.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_phase15_integration.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Behavior:**
- `refresh_external.refresh_all_sources()` runs all registered `SOURCE_IDS` in stable order: `dollar`, `real_rate`, `fred_net_liquidity`, `naaim_exposure`, `aaii_sentiment`.
- Each source keeps its own runner/ledger/validation/promote semantics. One source exception is recorded as that source's `ERROR` result and does not stop the remaining sources.
- 8766 exposes `/api/refresh_external_sources` under the same loopback-only and pipeline-lock rules as single-source refresh.
- The external-source operations table adds a "刷新全部外部源" button. The response reports `ok_count`, `error_count`, and per-source statuses; partial failure still reloads the page so the ledger state is visible.

**Verification:**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_refresh_external_cli.py src/hermes_escape_top/tests/test_phase15_integration.py::Phase15IntegrationTest::test_external_source_refresh_all_endpoint_runs_bundle_once src/hermes_escape_top/tests/test_phase15_integration.py::Phase15IntegrationTest::test_external_source_refresh_all_returns_409_while_pipeline_lock_is_held src/hermes_escape_top/tests/test_dashboard_workbench.py::test_trust_zone_uses_external_source_ledger_status -q
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

---

### Addendum: 8766 Source-Operation UI

**Files:**
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/render.py`
- Test: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Behavior:**
- The existing collapsible data-trust zone includes an "外部源运维" table when `external_source_status` is present.
- The table renders registered external sources in stable order: `dollar`, `real_rate`, `fred_net_liquidity`, then source-specific additions such as `naaim_exposure`.
- Each row shows latest promoted data date, latest source-run timestamp, status/error note, and a per-source refresh button.
- Buttons reuse the existing `/api/refresh_external_source` endpoint and update their own per-row status text.
- Missing source-run ledger rows stay operationally visible in this table but are not merged into the data-trust table as `ExternalSourceRunner · MISSING`, avoiding a false "soft data missing" read when existing soft-history data is still usable.

**Verification:**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py::test_trust_zone_uses_external_source_ledger_status -q
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py src/hermes_escape_top/tests/test_phase15_integration.py src/hermes_escape_top/tests/test_health_truth.py src/hermes_escape_top/tests/test_refresh_external_cli.py -q
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

---

### Addendum: NAAIM ExternalSourceRunner

**Files:**
- Add: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/core/data/external_sources/naaim.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/refresh_external.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/web/render.py`
- Tests: `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_external_source_naaim.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_refresh_external_cli.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_run_daily_external_sources.py`, `/Users/liweishi/Documents/github/hermes/src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Behavior:**
- `naaim_exposure` joins `refresh_external.SOURCE_IDS` and refreshes `soft_history/naaim_exposure.csv` through `ExternalSourceRunner`.
- The adapter discovers the official NAAIM xlsx link from `https://www.naaim.org/programs/naaim-exposure-index/`, records the workbook URL in raw source-run evidence, validates output shape, and promotes only validated CSV.
- Output columns stay compatible with existing scoring: `date`, `publish_date`, `naaim_exposure`, `naaim_pctl`, `is_proxy`.
- PIT alignment uses survey date + 1 day for `publish_date`, matching the official Thursday posting convention and the older `backfill_pcr_naaim.py` note.
- The daily legacy soft-data block no longer runs `backfill_soft_data --only naaim`; NAAIM is owned by the external-source preflight to avoid a post-runner overwrite.
- 8766 external-source operations table renders `naaim_exposure` with its own refresh button.

**Source Risk:**
- The official NAAIM page currently remains public and exposes a since-inception xlsx, but it announces a subscription-based access model effective 2026-08-01. After that date, failures should surface as source-run `FETCH_ERROR`/`VALIDATION_ERROR` and health DEGRADED rather than silently reusing stale data.

**Verification:**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_naaim.py src/hermes_escape_top/tests/test_refresh_external_cli.py src/hermes_escape_top/tests/test_run_daily_external_sources.py src/hermes_escape_top/tests/test_dashboard_workbench.py -q
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import pandas as pd
from hermes_escape_top.core.data.external_sources.naaim import NaaimExposureAdapter, naaim_exposure_spec
from hermes_escape_top.core.data.external_sources.runner import run_external_source_refresh

with TemporaryDirectory() as tmp:
    root = Path(tmp)
    target = root / "soft_history" / "naaim_exposure.csv"
    run = run_external_source_refresh(naaim_exposure_spec(target_path=target), NaaimExposureAdapter(), root / "archive")
    print(run.status, run.latest_promoted_as_of)
    print(pd.read_csv(target).tail(3).to_dict("records"))
PY
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```
