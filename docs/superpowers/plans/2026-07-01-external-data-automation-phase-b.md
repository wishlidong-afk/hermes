# External Data Automation Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-agnostic external data refresh core: source registry objects, staging, validation, atomic promotion, and a source-run ledger.

**Architecture:** The first implementation is deliberately provider-free. A small `ExternalSourceSpec` describes where a source promotes data and how it should be validated. A runner accepts an adapter with `fetch_raw()` and `parse(raw)` methods, writes raw/normalized/validation artifacts under archive staging, promotes only after validation, and records every attempt in a JSONL ledger. Real FRED/Alpaca adapters come after this core is tested.

**Tech Stack:** Python 3.11, pandas, existing `atomic_write_csv`, pytest.

## Global Constraints

- Do not change scoring thresholds, flags, `pipeline.py`, or `config/config.json`.
- Do not make official scoring depend on live network calls.
- Do not overwrite a known-good CSV with unvalidated data.
- Keep source refresh independent from full `run_daily`.
- All new production behavior is covered by failing-first tests.
- Use ASCII in new code and docs.

---

## File Structure

- Create `src/hermes_escape_top/core/data/external_sources/__init__.py`: package exports.
- Create `src/hermes_escape_top/core/data/external_sources/registry.py`: `ExternalSourceSpec` and validation types.
- Create `src/hermes_escape_top/core/data/external_sources/ledger.py`: JSONL source-run ledger writer/reader.
- Create `src/hermes_escape_top/core/data/external_sources/runner.py`: staged refresh orchestration.
- Create `src/hermes_escape_top/tests/test_external_source_runner.py`: fake adapter tests for success and failure.

## Task 1: Fake Source Success Path

**Files:**
- Create: `src/hermes_escape_top/core/data/external_sources/__init__.py`
- Create: `src/hermes_escape_top/core/data/external_sources/registry.py`
- Create: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Create: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Produces: `ExternalSourceSpec(source_id, target_path, date_column="date", required_columns=("date",), min_rows=1)`
- Produces: `run_external_source_refresh(spec, adapter, archive_dir, now=None) -> ExternalSourceRun`
- Produces: `latest_source_run(archive_dir, source_id) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
class FakeAdapter:
    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30", "value": 1.2}]}

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])


def test_success_writes_staging_promotes_target_and_records_ledger(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, FakeAdapter(), tmp_path / "archive")

    assert run.status == "OK"
    assert target.read_text(encoding="utf-8").startswith("date,value")
    assert run.raw_path and Path(run.raw_path).exists()
    assert run.normalized_path and Path(run.normalized_path).exists()
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "OK"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_runner.py::test_success_writes_staging_promotes_target_and_records_ledger -q
```

Expected: fail because the external source package does not exist.

- [ ] **Step 3: Implement minimal code**

Create the four package files. Keep the runner provider-agnostic and use `atomic_write_csv` for target promotion.

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command. Expected: `1 passed`.

## Task 2: Validation Failure Preserves Target

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/registry.py`
- Modify: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Consumes: Task 1 interfaces.
- Produces: failure runs with `status="VALIDATION_ERROR"` and unchanged target CSV.

- [ ] **Step 1: Write the failing test**

```python
class MissingColumnAdapter:
    def fetch_raw(self):
        return {"rows": [{"date": "2026-06-30"}]}

    def parse(self, raw):
        return pd.DataFrame(raw["rows"])


def test_validation_failure_preserves_existing_target_and_records_error(tmp_path):
    target = tmp_path / "soft_history" / "dollar.csv"
    target.parent.mkdir(parents=True)
    target.write_text("date,value\n2026-06-29,9.9\n", encoding="utf-8")
    spec = ExternalSourceSpec(
        source_id="dollar",
        target_path=target,
        required_columns=("date", "value"),
    )

    run = run_external_source_refresh(spec, MissingColumnAdapter(), tmp_path / "archive")

    assert run.status == "VALIDATION_ERROR"
    assert "missing required columns" in run.error_message
    assert target.read_text(encoding="utf-8") == "date,value\n2026-06-29,9.9\n"
    assert latest_source_run(tmp_path / "archive", "dollar")["status"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_runner.py::test_validation_failure_preserves_existing_target_and_records_error -q
```

Expected: fail until validation and no-promotion behavior exists.

- [ ] **Step 3: Implement validation**

Validate required columns, minimum rows, parseable dates, monotonic increasing dates, and no duplicate dates.

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command. Expected: `1 passed`.

## Task 3: Fetch and Parse Errors Become Ledger Evidence

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/runner.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Consumes: Task 1 interfaces.
- Produces: `FETCH_ERROR` and `PARSE_ERROR` statuses with unchanged target CSV.

- [ ] **Step 1: Write failing tests**

```python
class FetchBoomAdapter:
    def fetch_raw(self):
        raise RuntimeError("network down")

    def parse(self, raw):
        raise AssertionError("parse should not run")


class ParseBoomAdapter:
    def fetch_raw(self):
        return {"rows": []}

    def parse(self, raw):
        raise ValueError("bad html")
```

Assert `FETCH_ERROR` and `PARSE_ERROR`, ledger rows, and unchanged target.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_runner.py -q
```

Expected: failures for missing error mapping.

- [ ] **Step 3: Implement error mapping**

Catch fetch and parse exceptions separately. Write raw artifact only when fetch succeeds. Never promote target on any error.

- [ ] **Step 4: Run tests and verify GREEN**

Run the same pytest file. Expected: all tests pass.

## Task 4: Status Reader

**Files:**
- Modify: `src/hermes_escape_top/core/data/external_sources/ledger.py`
- Test: `src/hermes_escape_top/tests/test_external_source_runner.py`

**Interfaces:**
- Produces: `source_status(archive_dir, specs) -> dict[str, dict]`

- [ ] **Step 1: Write failing test**

```python
def test_source_status_reports_latest_run_and_promoted_date(tmp_path):
    ...
    status = source_status(tmp_path / "archive", [spec])
    assert status["dollar"]["status"] == "OK"
    assert status["dollar"]["latest_promoted_as_of"] == "2026-06-30"
```

- [ ] **Step 2: Run test and verify RED**

Expected: fail because `source_status` does not exist.

- [ ] **Step 3: Implement status reader**

Read the latest JSONL row per source and return a dictionary keyed by `source_id`.

- [ ] **Step 4: Run tests and verify GREEN**

Expected: all external source tests pass.

## Task 5: Whole-Suite Guard

**Files:**
- No new files.

- [ ] **Step 1: Run external source tests**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests/test_external_source_runner.py -q
```

- [ ] **Step 2: Run full suite**

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-01-external-data-automation-phase-b.md \
  src/hermes_escape_top/core/data/external_sources \
  src/hermes_escape_top/tests/test_external_source_runner.py
git commit -m "feat: add external source refresh core"
```

## Self-Review

- Spec coverage: Phase B registry, staging, validation, promotion, and ledger are covered.
- Completeness scan: no unfinished requirements are intentionally left in this plan.
- Type consistency: the public names are `ExternalSourceSpec`, `ExternalSourceRun`, `run_external_source_refresh`, `latest_source_run`, and `source_status`.
