# BTC Spot Witness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate Yahoo `BTC-USD` canonical updates with a public Coinbase Exchange completed-day close witness.

**Architecture:** A focused Coinbase adapter normalizes public UTC daily candles and emits provenance. The existing market-admission transaction consumes those rows only when `use_btc_spot_witness` is enabled; all mismatch and fetch failures preserve the prior canonical.

**Tech Stack:** Python 3.9, pandas, urllib, pytest, existing Hermes market-admission and atomic evidence APIs.

## Global Constraints

- New flag defaults OFF and must pass four-date payload plus persistence equality.
- Coinbase is witness-only; Yahoo remains the sole BTC canonical candidate writer.
- Compare UTC date and close only; never use volume to admit or reject.
- No official daily run is used for activation or verification.
- Every code task follows red-green-refactor and ends with focused tests.

---

### Task 1: Coinbase Daily Witness Adapter

**Files:**
- Create: `src/hermes_escape_top/core/data/coinbase_witness.py`
- Create: `src/hermes_escape_top/tests/test_coinbase_witness.py`

**Interfaces:**
- Produces: `latest_completed_utc_day(now=None) -> date`
- Produces: `fetch_coinbase_daily_bar_range(start, end, request_json=None) -> dict`
- Produces: `compare_btc_spot_close(local, witness) -> dict`

- [ ] Write tests for reverse-order Coinbase arrays, date filtering, chunking at 300 candles, UTC completion, close warning/mismatch bands, and provenance SHA.
- [ ] Run the new test file and confirm failures are due to the missing module.
- [ ] Implement the minimum public unauthenticated adapter and stable response hashing.
- [ ] Run the new test file and confirm all cases pass.

### Task 2: Market Admission Integration

**Files:**
- Modify: `src/hermes_escape_top/core/data/market_admission.py`
- Modify: `src/hermes_escape_top/tests/test_market_admission.py`

**Interfaces:**
- Consumes: Coinbase adapter interfaces from Task 1.
- Produces: `prepare_market_admission_session(..., btc_spot_witness_enabled=False, coinbase_request_json=None)`.
- Produces: BTC-specific evidence rows and provenance in `MarketAdmissionSession.payload()` only while enabled.

- [ ] Write failing tests for BTC match, warning, mismatch, missing witness, independent fetch failure, deferred current UTC day, and exact legacy payload while OFF.
- [ ] Run the admission tests and confirm the new assertions fail.
- [ ] Implement the opt-in BTC branch without changing the existing Alpaca branch when OFF.
- [ ] Run admission and market-witness tests to green.

### Task 3: Backfill Calendar And Config Wiring

**Files:**
- Modify: `src/hermes_escape_top/scripts/backfill_history.py`
- Modify: `src/hermes_escape_top/scripts/run_daily_package.py`
- Modify: `src/hermes_escape_top/config/config.json`
- Modify: `src/hermes_escape_top/tests/test_backfill_guard.py`

**Interfaces:**
- Consumes: `MarketAdmissionSession` BTC applicability and calendar-day policy.
- Produces: weekend BTC candidate evaluation only when the new flag is ON.

- [ ] Write failing tests proving Saturday/Sunday BTC intervals are fetched and mismatches preserve the old canonical while flag OFF keeps the NYSE shortcut.
- [ ] Run the focused backfill tests and verify red.
- [ ] Pass the flag through automatic and daily session construction and add the repo-default-false config key.
- [ ] Run backfill, admission, config, and daily focused tests to green.

### Task 4: Evidence, Governance, And Deployment

**Files:**
- Modify: `docs/FLAG_REGISTRY.md`
- Modify: `context.md`
- Create: `docs/history/2026-07-14_btc_spot_witness.md`
- Create: `building/reports/data_quality/btc_spot_witness_off_equivalence_2026_07_14.json`
- Create: `building/reports/data_quality/btc_spot_witness_live_canary_2026_07_14.json`

**Interfaces:**
- Consumes: tested code from Tasks 1-3.
- Produces: reviewable OFF proof, live canary, activation, and rollback evidence.

- [ ] Run four-date OFF payload and six-artifact equality proof.
- [ ] Run a real Coinbase-vs-Yahoo tail canary in an isolated data root.
- [ ] Run the full suite and governance consistency check.
- [ ] Obtain independent blocking review and fix all P0/P1/P2 findings.
- [ ] Merge and deploy with repo flag OFF, then enable live under `.pipeline.lock`, verify manifest/8766/evidence, and record the activation.
