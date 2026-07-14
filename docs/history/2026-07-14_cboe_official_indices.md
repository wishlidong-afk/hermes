# CBOE Official Volatility Indices Migration

Date: 2026-07-14

## Decision

Move `^VIX`, `^VIX3M`, `^VIX9D`, `^SKEW`, and `^VVIX` from Yahoo-written
history to five independent CBOE-official canonical writers. Yahoo becomes a
witness only. The repository default remains
`features.use_cboe_official_indices=false`; production activation requires the
controlled initial rebaseline described below.

## Source Verification

The official landing page is
`https://www.cboe.com/tradable-products/vix/vix-historical-data`. The files are
public, require no authentication, and were fetched successfully on 2026-07-14.

| Source ID | Symbol | Official file | Schema | Canary latest |
|---|---|---|---|---|
| `cboe_vix` | `^VIX` | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv` | DATE + OHLC | 2026-07-13 |
| `cboe_vix3m` | `^VIX3M` | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv` | DATE + OHLC | 2026-07-10 witness-certified |
| `cboe_vix9d` | `^VIX9D` | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv` | DATE + OHLC | 2026-07-10 witness-certified |
| `cboe_skew` | `^SKEW` | `https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv` | DATE + close | 2026-07-13 |
| `cboe_vvix` | `^VVIX` | `https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv` | DATE + close | 2026-07-13 |

CBOE publishes these files for visitor convenience and does not guarantee
accuracy. Hermes uses them internally, archives the exact response and SHA-256,
and does not treat the files as a redistribution license.

## Admission Contract

1. Only sessions at or before the latest completed US market session are
   considered.
2. The latest admitted CBOE row must have a Yahoo close witness. A mismatched
   row is rejected. A lagging witness trims the unconfirmed official tail.
3. VIX/VIX3M/VIX9D use official OHLC. Historical official rows with internally
   impossible OHLC are repaired from that same row's official close; the raw
   file and repair count remain in immutable evidence. SKEW/VVIX are close-only,
   so OHLC is deterministically set to close and volume to zero.
4. A normal refresh cannot shorten the canonical start, remove an existing
   date, reduce row count, recreate a missing canonical, or recertify a
   canonical whose dates are unreadable.
5. Initial source replacement is the only exception. It requires
   `allow_initial_rebaseline=True`, is not exposed by CLI or Web, and records
   `controlled_initial_rebaseline_then_daily_witness` in the ledger PIT rule.
6. With the flag ON, the ownership check is enforced inside `backfill()`;
   explicit CLI, Web, and direct Python calls cannot route these five symbols
   back through Yahoo. With the flag OFF, direct CBOE refresh is rejected before
   adapter construction or network access.

Each source uses ExternalSourceRunner raw/normalized/validation artifacts and
records official file SHA, canonical SHA, latest canonical date, URL, PIT rule,
attempt time, and 30/90-day reliability. A failed latest attempt remains visible
as DEGRADED even when the previous canonical is still fresh and `MATCH`.

## Verification

| Evidence | Result |
|---|---|
| Focused source/runner/daily/Web tests | 222 passed in independent review |
| Full repository suite | 935 passed |
| OFF payload + six persistence artifacts | Four dates, `all_equal=true` |
| Isolated real-network canary | Five sources OK; unconfirmed VIX3M/VIX9D tail stopped at 2026-07-10 |
| Four-date ON action comparison | Status, score, sizing and routing all equal; input hashes changed as expected |
| Full next-open replay, 2018-01-01 to 2026-07-10 | 2,141 sessions; 16.61% CAGR / -18.83% MaxDD / 1.120 Sharpe |
| Frozen baseline | 15.90% CAGR / -19.07% MaxDD / 1.069 Sharpe |
| Independent blocking review | PASS; P0/P1/P2 cleared after three review/fix rounds |

Evidence files:

- `building/reports/data_quality/cboe_official_indices_off_equivalence_2026_07_14.json`
- `building/reports/data_quality/cboe_official_indices_on_impact_2026_07_14.json`
- `building/reports/data_quality/cboe_official_indices_full_backtest_2026_07_14.json`

## Activation And Rollback

Activation must hold `.pipeline.lock` for the complete transaction:

1. Snapshot the five current Yahoo canonical files and live config.
2. Fetch all five official files and compare them with the pre-migration Yahoo
   canonical witness.
3. Run all five controlled initial rebaselines. On any failure, restore every
   snapshot and keep the flag OFF.
4. Verify five latest successful ledger rows have `MATCH` canonical evidence.
5. Set live `features.use_cboe_official_indices=true`, then render 8766 and run
   the non-official live verification path.

Rollback restores the five snapshots and sets the live flag false while holding
the same pipeline lock. No official daily run, receipt, order path, or IBKR write
is part of activation.

## Live Activation Result

The code-only release `d2ed608` was deployed first with the repository default
OFF while preserving live config. Its staged smoke and non-official
`verify_live` path passed before any canonical data changed.

The first controlled activation attempt at 2026-07-14 13:53 CST hit a 30-second
CBOE CDN timeout on VIX. It promoted no source, restored all five snapshots,
kept the flag OFF, and returned 8766 to service. The five official files were
then prefetched outside the lock with bounded transport retries and their exact
bytes were consumed inside one lock-held activation transaction.

The second attempt succeeded at 2026-07-14 13:55 CST:

| Source | Before rows/start | After rows/start | Latest | Canonical SHA-256 |
|---|---:|---:|---|---|
| VIX | 2,145 / 2018-01-02 | 9,227 / 1990-01-02 | 2026-07-13 | `29ca9f73edf7f574885227802076ed04f8889e197c4c9df734b8533fef9463ff` |
| VIX3M | 2,142 / 2018-01-02 | 4,228 / 2009-09-18 | 2026-07-13 | `b07b17f0685118f4d1d25bb5f726cfbac2d9c932fb66ba3e0a0343970e079c12` |
| VIX9D | 2,142 / 2018-01-02 | 3,902 / 2011-01-04 | 2026-07-13 | `9a1172e6d4b07b070c09e2a5d5157a32e0e61230830458072618f56d00a4f386` |
| SKEW | 2,091 / 2018-01-02 | 9,182 / 1990-01-02 | 2026-07-13 | `02745261b3e44228b1ea97b84bbd6c586ba37608a01266363217be27192202df` |
| VVIX | 2,134 / 2018-01-02 | 5,059 / 2006-03-06 | 2026-07-13 | `d8c59e507d2a4c0905b5519b2e03ddf32af978754a4a37755276f9ff9b8ce874` |

All five current source-status records are `OK`, canonical evidence is `MATCH`,
and 8766 returned HTTP 200 with no preview banner. The scheduled receipt and
official score audit retained identical byte counts and mtimes across the
activation, proving that activation did not manufacture another official run.
Live config now has `features.use_cboe_official_indices=true`; repository
default remains false for fail-safe deployment and isolated tests.
