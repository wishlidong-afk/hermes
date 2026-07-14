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
