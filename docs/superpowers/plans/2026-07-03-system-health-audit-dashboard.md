# System Health Audit Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the daily 20-dimension system health audit report inside the 8766 dashboard.

**Architecture:** `server.py` attaches the best matching report JSON to the payload. `render.py` stays pure and renders only the attached data inside the existing System Health section.

**Tech Stack:** Python stdlib, existing server-side HTML rendering, pytest.

## Global Constraints

- Do not touch `config/config.json`, `pipeline.py`, or scoring behavior.
- Do not trigger daily, refresh, score, or any official write path.
- Keep the panel default-collapsed.
- Mark stale report evidence explicitly when report `as_of` differs from payload `as_of`.

---

### Task 1: Render Attached Audit Report

**Files:**
- Modify: `src/hermes_escape_top/web/render.py`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Consumes: `payload["system_health_report"]` as a dict with keys `as_of`, `generated_at`, `health`, `audit_dimensions`, optional `stale`, optional `source_path`.
- Produces: `_render_system_health_audit(payload: Dict[str, Any]) -> str`.

- [ ] **Step 1: Write failing render test**

Add a test that injects `system_health_report` into the dashboard payload and asserts the collapsed panel, PASS/WARN/FAIL counts, and one dimension row render.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py::test_system_health_section_renders_20_dimension_report -q
```

Expected: FAIL because the new panel does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add `_render_system_health_audit(payload)` and call it from `_render_trust_section` below `_render_data_trust_zone(payload)`.

- [ ] **Step 4: Run render test**

Run the same pytest command. Expected: PASS.

### Task 2: Load Best Matching Report In Server

**Files:**
- Modify: `src/hermes_escape_top/web/server.py`
- Test: `src/hermes_escape_top/tests/test_dashboard_workbench.py`

**Interfaces:**
- Produces: `_attach_system_health_report(payload: dict) -> dict`.

- [ ] **Step 1: Write failing loader tests**

Add tests that monkeypatch report roots to a temp reports directory:

- exact `system_health_<as_of>.json` wins over newer mismatched reports;
- newest report attaches with `stale=True` when exact is absent.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py -q
```

Expected: FAIL because `_attach_system_health_report` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Implement `_system_health_report_roots`, `_read_system_health_report`, and `_attach_system_health_report`. Call the attach helper on dashboard GET after the read-only payload attachments and before rendering.

- [ ] **Step 4: Run focused tests**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py -q
```

Expected: PASS.

### Task 3: Verify End To End

**Files:**
- No new files.

**Interfaces:**
- Confirms 8766 dashboard HTML contains the new collapsed evidence panel after live deploy or local server render.

- [ ] **Step 1: Run health/render related tests**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_dashboard_workbench.py src/hermes_escape_top/tests/test_health_truth.py src/hermes_escape_top/tests/test_run_receipt_writer.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

Expected: PASS.
