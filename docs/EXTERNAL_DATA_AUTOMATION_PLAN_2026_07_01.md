# External Data Automation Plan - 2026-07-01

> Historical implementation plan, updated 2026-07-13 to remove a dangerous PIT
> ambiguity. The implemented architecture is documented in `context.md`,
> `docs/PRODUCTION_RUNBOOK.md`, and
> `docs/history/2026-07-13_data_quality_hardening_handoff.md`.

> Scope: make Hermes external data boring, auditable, and source-specific. This plan does not change scoring thresholds or enable new alpha flags. It changes how external data is fetched, validated, promoted, observed, and refreshed.

## 1. Why This Matters

Hermes is now strong on scoring safety, deployment safety, and auditability, but external data still has too much implicit behavior:

- A stale source can make the dashboard noisy without clearly saying whether the data is unpublished, fetch-failed, parse-failed, or manually required.
- Some fixes still use a heavy "run the whole daily" path when the operator only wants one data source refreshed.
- Official scoring and web refresh historically sat too close to online fetching, which made rate limits and source outages harder to isolate.
- The trust zone needs a machine-readable ledger, not hand-derived freshness labels.

The desired end state: every external source has its own small lifecycle:

```text
due? -> fetch raw -> parse normalized rows -> validate -> atomic promote -> source_run ledger -> dashboard trust zone
```

Scoring consumes only promoted data. Failed fetches write evidence, not bad CSV.

## 2. Non-Negotiables

- Never place trades. This work is data-only.
- Do not make official scoring depend on live network calls.
- Do not overwrite a known-good CSV with unvalidated data.
- Keep source refresh independent from full `run_daily`.
- Preserve current scoring behavior unless a source produces the same promoted rows.
- All new production behavior must have tests for success, stale, parse error, validation error, and no-promotion-on-failure.

## 3. Target Architecture

### 3.1 Source Registry

Create a single registry describing each external source:

```python
ExternalSourceSpec(
    source_id="dollar",
    target_file="soft_history/dollar.csv",
    cadence="weekly",
    release_calendar="FRED_BUSINESS_DAILY_WITH_LAG",
    expected_lag_days=1,
    slo_days=13,
    credential="FRED_API_KEY",
    fetcher="fred_series",
    parser="fred_observations",
    validator="monotonic_daily_series",
)
```

The registry should answer:

- Is this source enabled?
- Is it due today?
- What is the latest promoted data date?
- What is the expected latest available date?
- Is the current state OK, NOT_DUE, STALE, FETCH_ERROR, PARSE_ERROR, VALIDATION_ERROR, MANUAL_REQUIRED, or DISABLED?

### 3.2 Staging Then Promote

Each refresh writes into staging first:

```text
data/archive/external_sources/<source_id>/
  raw/<run_id>.json or .csv
  normalized/<run_id>.csv
  validation/<run_id>.json
```

Promotion rules:

- The normalized CSV must pass schema checks.
- Dates must be monotonic and not future-dated relative to point-in-time rules.
- The latest row must not move backwards unless the source explicitly supports revisions.
- Value sanity checks must pass source-specific bounds.
- Promotion uses temp file + `os.replace`.
- On failure, the prior promoted CSV remains unchanged.

### 3.3 Source Run Ledger

Add a small SQLite table or JSONL ledger under archive:

```text
external_source_runs
  run_id
  source_id
  started_at
  finished_at
  status
  latest_promoted_as_of
  expected_as_of
  stale_days
  raw_path
  normalized_path
  target_path
  error_type
  error_message
  input_hash
  output_hash
```

Dashboard trust zone reads this ledger instead of reconstructing source truth from CSV files alone.

### 3.4 CLI and Web Interface

Add source-specific commands:

```bash
python -m hermes_escape_top.scripts.refresh_external --source dollar
python -m hermes_escape_top.scripts.refresh_external --source alpaca_sip_flow --as-of latest-trading-day
python -m hermes_escape_top.scripts.refresh_external --all-due
python -m hermes_escape_top.scripts.refresh_external --status
```

WebUI buttons should call source-specific refresh endpoints, not full `run_daily`.

```text
POST /api/refresh_external_source {"source_id":"dollar"}
GET  /api/external_source_status
```

These are loopback-only, use the existing pipeline lock, and return HTTP 409 if another writer is active.

## 4. Source-Specific Plan

### 4.1 FRED Sources

Sources:

- `dollar`
- `real_rate`
- `fred_net_liquidity`
- later: `nfci`, `hy_oas`, yield curve sources if re-enabled

Plan:

- Use the FRED API when credentials exist.
- Record the standard observations API's top-level `realtime_start` and
  `realtime_end` as query-vintage evidence only. They are not per-observation
  first-release dates and must not become normalized `publish_date`.
- Keep normalized `publish_date = observation_date + 1 day` for the current
  conservative production convention. A true first-release timeline requires
  a separately built ALFRED-vintage dataset and its own gate.
- Treat Graph CSV fallback as lower confidence because it lacks full realtime metadata.
- Add validators for date monotonicity, numeric value, and revision policy.

Priority: first implementation batch, because this is the easiest high-value automation and dollar has produced real alerts.

### 4.2 Alpaca SIP Daily Flow

Source:

- `alpaca_sip_flow`

Plan:

- Fetch the previous completed US trading session after the close.
- Store raw minute bars by source run.
- Promote a daily aggregate containing `buy_est`, `sell_est`, `net_est`, `coverage`, `confidence`, and component rows.
- Keep copy honest: this is estimated trade-direction flow from bars, not exchange-reported true net fund flow.
- Health should degrade if the previous completed session is missing after the expected availability window, but not mark core scoring failed.

Priority: second batch, because it supports the user's most important operating view: underlying stock money flow.

### 4.3 AAII and NAAIM

Sources:

- `aaii_sentiment`
- `naaim_exposure`

Plan:

- Prefer official/member CSV or stable HTML endpoint if available.
- If a browser session or manual login is required, represent the state explicitly as `MANUAL_REQUIRED`.
- Add `manual_import` support:

```bash
python -m hermes_escape_top.scripts.refresh_external --source aaii_sentiment --import-file ~/Downloads/aaii.csv
```

- Dashboard should say "manual required" rather than pretending the system can always auto-fetch it.

Priority: third batch.

### 4.4 CBOE, OCC, COT

Sources:

- `cboe_equity_pcr`
- `occ_equity_pcr`
- `cot_nq`

Plan:

- Keep each adapter isolated, with schema checks pinned to current known columns.
- If a provider changes HTML/CSV layout, quarantine the failed run and keep old promoted data.
- The trust zone must distinguish "not published yet" from "published but parser failed".

Priority: third batch, after FRED and Alpaca.

## 5. Dashboard Trust Zone

Replace the current trust display with source-run-backed rows:

| Column | Meaning |
|---|---|
| Source | Canonical `source_id` |
| Latest | Latest promoted data date |
| Expected | Latest date the source should have by now |
| State | OK / NOT_DUE / STALE / ERROR / MANUAL_REQUIRED / DISABLED |
| Freshness | Trading/calendar-day aware countdown |
| Authenticity | real / proxy / manual / fallback |
| Last Run | Last refresh attempt timestamp |
| Error | Short failure reason, if any |
| Action | Source-specific refresh/import link |

This row should be the same data used by `/api/external_source_status`, `/api/health_status`, and the 8766 dashboard.

## 6. Implementation Phases

### Phase A - Fix Current State Consistency

Already started in R7.0:

- Hydrate cached payloads with IBKR overlay before health computation.
- Refresh action context after an IBKR overlay changes `ibkr`.
- Add regression tests for both.

### Phase B - Registry and Ledger Skeleton

Files to add:

- `src/hermes_escape_top/core/data/external_sources/registry.py`
- `src/hermes_escape_top/core/data/external_sources/runner.py`
- `src/hermes_escape_top/core/data/external_sources/ledger.py`
- `src/hermes_escape_top/tests/test_external_source_registry.py`
- `src/hermes_escape_top/tests/test_external_source_runner.py`

Deliverable:

- In-memory fake source can fetch, validate, promote, and write ledger rows.
- Failed validation does not modify target CSV.

### Phase C - FRED Adapter Migration

Files to modify:

- `src/hermes_escape_top/core/data/risk_signals.py`
- existing FRED backfill script, or a new `external_sources/fred.py`

Deliverable:

- `dollar`, `real_rate`, and `fred_net_liquidity` can be refreshed independently.
- Existing soft history outputs are byte-equivalent for the same source response.

### Phase D - Web/API Integration

Files to modify:

- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/health.py`

Deliverable:

- `/api/external_source_status` returns registry + ledger status.
- `/api/refresh_external_source` refreshes one source under lock.
- Trust zone uses the same status object as health.

### Phase E - Alpaca SIP Daily Flow Adapter

Files to modify:

- `src/hermes_escape_top/core/data/alpaca_flow.py`
- `src/hermes_escape_top/web/render.py`

Deliverable:

- Previous completed trading session is fetched independently.
- Flow rows show coverage/confidence and are clearly labeled as estimates.

### Phase F - Manual/Authenticated Sources

Deliverable:

- AAII/NAAIM support explicit `MANUAL_REQUIRED` and manual import.
- Dashboard stops treating manual-only gaps as mysterious system failures.

## 7. Verification Plan

Minimum tests:

- Registry computes due/not-due correctly for daily and weekly sources.
- Failing fetch writes `FETCH_ERROR` ledger row and preserves existing CSV.
- Failing parse writes `PARSE_ERROR` and preserves existing CSV.
- Failing validation writes `VALIDATION_ERROR` and preserves existing CSV.
- Successful refresh writes raw, normalized, validation, target CSV, and ledger row.
- Web source refresh returns 409 under pipeline lock contention.
- Health and trust zone read the same status object.
- FRED raw evidence preserves query `realtime_start`/`realtime_end`, retrieval
  time and PIT rule; normalized rows retain the conservative `date + 1 day`
  publish date. Retrieval timestamps do not change the stable source input hash.
- Alpaca SIP flow handles partial coverage and marks confidence lower.

Runtime checks:

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
python -m hermes_escape_top.scripts.refresh_external --status
python -m hermes_escape_top.scripts.refresh_external --source dollar --dry-run
```

## 8. Recommended Next Task

Implement Phase B first. Do not start with FRED directly. The registry + staging + ledger runner is the deep module; adapters should be small.

The first code task should be:

> Build a fake external source runner that proves staging, validation, atomic promotion, and ledger evidence work without touching any real provider.

After that, migrate FRED dollar as the first real adapter.
