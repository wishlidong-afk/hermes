# FRED / ALFRED Vintage PIT Implementation Plan

Date: 2026-07-14

## 1. Event Adapter

- Add `core/data/external_sources/fred_vintage.py`.
- Test output-type-3 dynamic-field parsing, four-year windows, key redaction,
  response hashes, incremental merge, missing events, and conflict rejection.
- Add a `fred_vintages` runner spec whose duplicate policy is the composite
  event key and whose latest date is `vintage_date`.

Verify: focused adapter tests red then green; real API bootstrap canary has five
series, unique event keys, and no secret in raw evidence.

## 2. Exact Replay Builders

- Add exact single-series percentile and three-series net-liquidity builders.
- Retain observation date, vintage date, realtime start, fetched time, and
  component release dates.
- Emit release rows only when the decision-facing output changes.

Verify: synthetic revision fixtures prove a replay before a revision sees the
old value and a replay after it sees the revision; future vintages never leak.

## 3. Runner And Policy Wiring

- Add `use_fred_vintage_pit=false`.
- OFF keeps the existing FRED adapters and source order.
- ON prepends `fred_vintages` and makes the three derived adapters consume its
  SHA-bound canonical event store.
- Skip derived regeneration during refresh-all if the vintage refresh fails.
- Update Source Policy Registry, health/trust display, FRED attribution, and
  predeploy smoke semantics.

Verify: source-factory, dependency, profile, dashboard, and smoke tests.

## 4. Evidence

- Run focused tests, full suite, governance checks, and `git diff --check`.
- Run four-date OFF persistence equivalence.
- Bootstrap isolated real vintages and generate all three derived files twice;
  require deterministic business columns and report coverage gaps.
- Compare current live values and historical score decisions.

Verify: reports under `building/reports/data_quality/` and a history handoff.

## 5. Deploy And Decision

- Independent blocking review before merge.
- Merge and deploy with repo flag OFF.
- If the historical migration evidence passes, perform one lock-held backup,
  four-file promotion, flag flip, manifest refreeze, dashboard restart, and
  health validation while proving official receipt/audit unchanged.
- If evidence fails, leave the flag OFF and register the exact dataset as
  research-ready rather than weakening thresholds or hiding missing history.
