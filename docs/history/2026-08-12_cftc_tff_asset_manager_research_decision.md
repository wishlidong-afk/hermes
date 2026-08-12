# CFTC TFF Asset Manager Research Decision

**Date:** 2026-08-12
**Decision:** Admit as offline research only; do not wire production.

## Source Finding

The free CFTC Traders in Financial Futures futures-only dataset (`gpe5-46if`)
separates Asset Manager/Institutional positions from Dealer/Intermediary,
Leveraged Funds, Other Reportables, and Non-Reportables. The official category
includes pension funds, endowments, insurers, mutual funds, and portfolio or
investment managers.

The candidate uses exact CFTC contract codes:

| Market | CFTC code | Field family |
|---|---:|---|
| E-mini S&P 500 | `13874A` | Asset Manager long / short / spread |
| Nasdaq Mini | `209742` | Asset Manager long / short / spread |

It computes `(Asset Manager long - Asset Manager short) / open interest`, then
aggregates ES and NQ by open interest. Exact release-date evidence is required;
the normal Tuesday-to-Friday schedule alone is not sufficient for a formal
candidate row.

## Why This Is Not NAAIM

NAAIM is a survey of active investment managers' reported equity exposure.
CFTC TFF is observed futures positioning for reportable Asset Manager/
Institutional accounts. The series have different populations, instruments,
and timing. Therefore CFTC data may test a related hypothesis but cannot be
written into `naaim_exposure.csv` or presented as the same datum.

## Weight Ownership

The A module is cap-saturated. If this candidate survives offline screening and
one formal gate, it must replace `A2_NAAIM`'s two points. It must not be added on
top of A2 and must not reuse the four-point `A20_COT_NQ` slot.

## Separation From Rejected Work

`data_cot_nq` combined Asset Manager and Leveraged Funds net positions and
failed its prior in-system experiment. This candidate deliberately excludes
Leveraged Funds and uses a stable ES+NQ market basket. It is a new prior, not a
retune or revival of the rejected experiment.

## Gate Prerequisites

1. Immutable raw CFTC artifacts and exact release-date manifest.
2. Stable ES+NQ market-code coverage.
3. Event lead-time/precision screen against labeled tops.
4. Correlation matrix versus AAII, PCR, existing A factors, and historical
   NAAIM overlap.
5. Preregistered two-point displacement mapping and one formal gate budget.

No source registration, factor registration, config key, or live flag is
authorized by this decision.
