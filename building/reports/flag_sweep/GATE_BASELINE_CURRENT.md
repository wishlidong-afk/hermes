# Current Formal-Gate Baseline

Status: **CURRENT EXECUTION EVIDENCE**

This artifact is the provenance-bound next-open comparator for future
pre-registered formal gates. It grants no configuration authorization.

| Field | Value |
|---|---|
| Gate-code commit | `b23cf124b5b906d897884f2774d354b8cae23d1a` |
| Cache schema | `flag-sweep-cache-v4` |
| Equity timing | `next_open` |
| Window | `2018-01-01` to `2026-07-21` |
| Effective observations | 2,148 |
| CAGR | 15.56% |
| MaxDD | -20.83% |
| Sharpe | 1.064 |
| Sortino | 1.335 |
| Pre-registered route-set turnover | 103.466858 across 162 route-set events |

Machine freshness result: `CURRENT_EXECUTION_EVIDENCE`; source provenance is
`CURRENT_SOURCE`, legacy parity is `MATCH`, and execution-required open missing
rows are zero. A direct post-build `assess_artifact_freshness` check returned
`FRESH` with no mismatches using the committed baseline config snapshot.

The pre-registered turnover definition is
`full_portfolio_l1_on_nonrisk_nonboxx_route_set_change_days`. It is not the
same measure as the broader `ROUTE_SET_CHANGE` attribution in the cost report,
so their numeric totals must not be compared or substituted.

This is an eligible baseline input for future pre-registered formal gates. It
does not by itself authorize a feature or routing flip.

The same-close shadow is retained at
`building/reports/flag_sweep/baseline_legacy_close_equity.json`; it must not be
renamed to or substituted for `baseline_equity.json`.
