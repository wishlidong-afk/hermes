# Current Formal-Gate Baseline

Status: **CURRENT EXECUTION EVIDENCE**

This artifact is the provenance-bound next-open comparator for future
pre-registered formal gates. It grants no configuration authorization.

| Field | Value |
|---|---|
| Gate-code commit | `148c8752b5558f59d560db288a9eb155b2096e77` |
| Cache schema | `flag-sweep-cache-v4` |
| Equity timing | `next_open` |
| Window | `2018-01-01` to `2026-07-17` |
| Effective observations | 2,146 |
| CAGR | 15.46% |
| MaxDD | -20.83% |
| Sharpe | 1.058 |
| Sortino | 1.329 |
| Route-set turnover | 103.466858 across 162 route-set events |

Machine freshness result: `CURRENT_EXECUTION_EVIDENCE`; source provenance is
`CURRENT_SOURCE`, legacy parity is `MATCH`, and execution-required open missing
rows are zero. A direct post-build `assess_artifact_freshness` check returned
`FRESH` with no mismatches using the committed baseline config snapshot.

This is an eligible baseline input for future pre-registered formal gates. It
does not by itself authorize a feature or routing flip.

The same-close shadow is retained at
`building/reports/flag_sweep/baseline_legacy_close_equity.json`; it must not be
renamed to or substituted for `baseline_equity.json`.
