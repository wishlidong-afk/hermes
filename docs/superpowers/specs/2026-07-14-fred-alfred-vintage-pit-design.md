# FRED / ALFRED Vintage PIT Design

Date: 2026-07-14

## Goal

Replace the current `observation_date + 1 day` approximation with an exact,
auditable ALFRED event store and as-of replay path. The new path is gated by
`features.use_fred_vintage_pit`, defaults OFF, and must leave the existing FRED
collectors byte-identical while OFF.

The scope is the five series that feed live decisions:

- `DTWEXBGS` -> Dollar / A11
- `DFII10` -> 10Y real rate / A10
- `WALCL`, `WTREGEN`, `RRPONTSYD` -> net liquidity / A15

## Source Verification

The official `fred/series/observations` API supports:

- `output_type=3`: observations grouped by vintage date, containing only new
  or revised observations;
- `output_type=4`: initial releases only;
- `vintage_dates`: explicit historical snapshots;
- JSON requests with at most 2,000 vintage dates.

Official documentation:

- `https://fred.stlouisfed.org/docs/api/fred/series_observations.html`
- `https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html`
- `https://fred.stlouisfed.org/docs/api/fred/realtime_period.html`
- `https://fred.stlouisfed.org/docs/api/terms_of_use.html`

The live key was verified without exposing it. Real API probes confirmed that
`output_type=3` returns dynamic fields such as `DFII10_20260713`, while
`output_type=4` returns row-level `realtime_start`. The earliest available
vintage dates reported by the official API are:

| Series | Earliest vintage | Latest checked | Vintage count |
|---|---|---|---:|
| DTWEXBGS | 2019-02-04 | 2026-07-13 | 389 |
| DFII10 | 2005-10-12 | 2026-07-13 | 5,046 |
| WALCL | 2011-07-07 | 2026-07-09 | 783 |
| WTREGEN | 2008-12-18 | 2026-07-09 | 914 |
| RRPONTSYD | 2016-03-28 | 2026-07-13 | 2,557 |

Therefore Dollar is genuinely unavailable to a 2018 replay. The implementation
must expose that missing period; it may not backfill today's revised Dollar
history into a date before the series' first ALFRED vintage.

The API terms require the notice: "This product uses the FRED(R) API but is not
endorsed or certified by the Federal Reserve Bank of St. Louis." The dashboard
data-trust detail and runbook will carry that notice. Raw data remains local and
must respect third-party series restrictions.

## Event Store

`soft_history/fred_vintages.csv` is the canonical event log. Only
`ExternalSourceRunner` may promote it. Each row contains:

- `series_id`
- `observation_date`
- `realtime_start`
- `vintage_date`
- `value`
- `is_missing`
- `fetched_at`
- `source_url`
- `response_sha256`

The primary key is `(series_id, observation_date, vintage_date)`. Conflicting
values for an existing key fail closed. Identical overlap rows preserve their
original `fetched_at`; new events record the current fetch time.

The adapter first checks each series' latest official vintage. With no seed it
bootstraps in inclusive, non-overlapping real-time windows no longer than four
years, staying below the 2,000-vintage JSON limit. With a seed it re-fetches
from the last stored vintage through the latest official vintage and merges the
overlap. Every request archives parameters without the API key, exact response
SHA256, row count, and payload in the runner's immutable `raw.json`.

No-key operation is forbidden on the exact path. Fredgraph CSV remains the
legacy OFF-path fallback only.

## As-Of Replay

For an as-of date `T`, an event is visible only when
`vintage_date <= T`. Events are applied in vintage order; a newer event replaces
the value for its observation date, while a missing-value event removes it.

### Dollar And Real Rate

At each vintage event date:

1. apply all events released that day;
2. select the latest visible observation;
3. recompute its trailing percentile from the values visible on that date;
4. emit a release-time row only when the decision-facing output changes.

The derived canonical keeps `date` as the latest observation date and uses
`publish_date` / `realtime_start` / `vintage_date` as the release event date.
Duplicate observation dates are allowed; publish dates are unique and drive
`asof_pick`.

### Net Liquidity

Maintain independent vintage states for `WALCL`, `WTREGEN`, and `RRPONTSYD`.
After each event day, use the latest observation date present in all three
states, recompute the full common-date net-liquidity history, its 10-observation
change, and trailing percentile, then emit only when that decision-facing
output changes. Component realtime-start dates are retained in the derived row.

## Dependency And Failure Policy

With the flag ON, refresh order is:

1. `fred_vintages`
2. `dollar`
3. `real_rate`
4. `fred_net_liquidity`

If the vintage source fails, a refresh-all run does not regenerate the three
derived canonicals from unverified input. The previous certified files remain
in place and the failed vintage ledger row explains the degradation. An
individual derived refresh verifies the vintage-store SHA before reading it.

`fred_vintages` is added to the Source Policy Registry with zero direct score
weight; the three decision sources retain their weights but switch their PIT
rule to `alfred_latest_vintage_at_or_before_as_of` while ON.

## Rollout

1. Implement and deploy default OFF.
2. Prove four-date payload and six-artifact equality while OFF.
3. Bootstrap a full isolated vintage store and validate raw hashes, uniqueness,
   coverage, and deterministic rebuilds.
4. Generate isolated Dollar, real-rate, and net-liquidity canonicals.
5. Measure score/backtest impact. Because true vintages change historical
   inputs, this is a data-baseline migration, not a silent live flip.
6. Only after the formal evidence passes, promote all four files and flip the
   flag in one lock-held transaction; otherwise leave the exact dataset parked
   for research and keep production on the documented approximation.

Rollback sets the flag false and restores the three pre-activation derived
canonicals. The immutable vintage event store may remain as non-scoring
evidence.
