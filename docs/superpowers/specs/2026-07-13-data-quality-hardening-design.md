# Hermes Data Quality Hardening Design

> Approved scope: implement the complete data-quality roadmap requested on
> 2026-07-13. Strategy-changing provider switches remain shadow-only until an
> explicit human gate. Paid credentials and licenses are never inferred.

## Goal

Make every active decision input answer five questions from one evidence chain:

1. Which provider supplied it?
2. When was it observable to Hermes?
3. Which validation admitted it to the canonical store?
4. Is the canonical file the same artifact recorded in the ledger?
5. How much current strategy weight depends on it?

The system must continue to score from local, validated data. Network refreshes
remain outside the scoring transaction and failure keeps the last known-good
artifact.

## Safety And Scope

- No automatic order path is added; IBKR remains auxiliary and read-only.
- No paid AAII/NAAIM access is assumed. Authenticated or manually downloaded
  official files enter through the same validation and ledger path.
- A second OHLCV provider is initially a shadow comparator. It cannot replace
  Yahoo/local canonical history or change `input_hash`, scores, valves, sizing,
  or routing until a separate human-approved gate.
- Disabled research feeds do not lower production health or decision coverage.
- Canonical CSVs have one writer: `ExternalSourceRunner` for external soft data
  and the existing history backfill transaction for OHLCV.
- Existing runtime data is never rewritten merely to migrate code.

## Architecture

### 1. Source Policy Registry

Deepen the existing external-source profile module into the single reporting
policy interface. A `SourcePolicy` describes:

- `source_id`, label, canonical filename and cadence;
- feature flag and current decision weight;
- expected publication schedule and grace period;
- automation mode (`api`, `official_file`, `browser_assisted`, `local_app`,
  `shadow_only`);
- PIT rule, primary provider, fallback and migration deadline;
- whether the source is production-active or parked.

Production max-age values come only from `config.soft_data_slo`; the registry
must not carry a conflicting threshold. `effective_source_policy(config,
source_id)` merges immutable metadata with that runtime threshold. Health,
precheck, WebUI and source adapters consume this interface.

### 2. One Canonical Writer

`ExternalSourceRunner` remains the only promotion interface for external soft
data. It gains:

- canonical output SHA256 in each successful ledger row;
- canonical latest date and SHA verification in status reads;
- `EVIDENCE_DRIFT` when canonical date/hash differs from the latest successful
  promotion;
- source-specific semantic validators;
- `UNCHANGED_AFTER_REFRESH` for a validated check that has no newer issue;
- immutable raw evidence metadata, including fetched time, source URL, official
  issue/file identity and PIT metadata when available.

The daily legacy block stops writing FRED and AAII files. CBOE PCR, CFTC COT,
OCC PCR and BTC microstructure move behind runner adapters before their direct
writers are removed from daily orchestration.

### 3. Refresh Scheduling

The 06:45 precheck performs a full refresh. The 07:05 invocation retries only
sources whose latest same-day attempt failed or whose canonical artifact is not
ready. The 07:10 daily consumes a recent precheck result and refreshes only if
no valid precheck exists. This prevents three unconditional requests to
rate-limited or anti-bot providers while preserving recovery.

### 4. Decision-Grade Quality

Keep the existing `DataQuality.overall_score` for compatibility, and add a
separate report-only `decision_input_coverage`:

```
100 * (active factor weight - unavailable active factor weight)
      / active factor weight
```

Coverage is computed from the actual scored factor/missing evidence, not a
parallel hand-maintained list. WebUI displays four independent dimensions:
market completeness, provenance, timeliness and active decision coverage.
Missing auxiliary IBKR/SIP data remains outside strategy coverage.

### 5. OHLCV Shadow Quorum

Create a small `MarketDataWitness` interface with two adapters:

- canonical local history (currently populated by Yahoo/yfinance);
- Alpaca SIP daily bars for supported U.S. stocks and ETFs.

The shadow comparator checks recent trading dates, split-adjusted close,
high/low bounds and volume. It writes an archive status only. It never promotes
history. Initial coverage includes strategy symbols, execution legs and their
major ETF underlyings. Unsupported indices are explicitly `NO_WITNESS`, not
silently treated as verified.

Promotion/failover is a later, separate gate requiring historical comparison,
corporate-action equivalence and byte-identical or approved score deltas.

### 6. AAII And NAAIM Migration

The existing official-file import path is authoritative when public fetches are
blocked. Add:

- issue date and file hash deduplication;
- migration deadline/status in source policy;
- authenticated artifact drop support through
  `~/.hermes/external_imports/` without storing credentials in the repo;
- a weekly `ACTION_REQUIRED` state when an official issue is expected but no
  validated artifact is available.

NAAIM is marked migration-due before 2026-08-01. AAII remains
`browser_assisted` until an official authenticated feed/export is configured.
Neither source may promote mirror data as official truth.

### 7. PIT And Reliability Evidence

Every successful ledger row records `fetched_at`, observation latest date,
official issue date when known, canonical hash and PIT rule. FRED raw evidence
also records query realtime/vintage parameters. Backtests continue using the
existing conservative publish-date convention until an ALFRED-vintage dataset
is separately built and gated.

Status output adds rolling 30/90-day success rates, consecutive failures, last
successful fetch, last promoted observation, canonical drift, migration state
and source rank. Transport health, freshness and decision impact remain
separate fields.

## Error Semantics

- `FETCH_ERROR`: provider could not be reached; preserve canonical data.
- `PARSE_ERROR`: provider response no longer satisfies adapter assumptions.
- `VALIDATION_ERROR`: normalized data failed structural or semantic checks.
- `EVIDENCE_DRIFT`: canonical data does not match the ledger promotion.
- `AUTH_REQUIRED`: official source now requires a session/subscription.
- `ACTION_REQUIRED`: a human official-file import is due.
- `NO_WITNESS`: no independent OHLCV provider covers the symbol.

Only stale or unavailable active strategy inputs affect decision coverage.
Transport failures with a still-fresh canonical artifact are warnings, not
fabricated scoring failures.

## Verification

- TDD for every new status, adapter and scheduler branch.
- Focused tests use temporary data roots and fake adapters; no test hits live
  providers or live data.
- Full pytest suite remains green.
- Four-date score replay proves governance, status and OHLCV shadow additions do
  not change score payloads or `input_hash`.
- A persistence check proves canonical target bytes are unchanged when a fetch,
  parse, validation or witness comparison fails.
- Live network canaries are read-only and write only staging/auxiliary status.

## Delivery Order

1. Source policy SSOT and canonical/ledger drift detection.
2. Remove duplicate FRED/AAII writes and make retries selective.
3. Migrate remaining external soft writers into runner adapters.
4. Add decision-input coverage and WebUI explanation.
5. Add OHLCV shadow witness and source reliability telemetry.
6. Add AAII/NAAIM migration states and PIT evidence.
7. Full verification, self-review and deployment decision.

