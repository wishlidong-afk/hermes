# Current Formal-Gate Baseline

Status: **CURRENT EXECUTION EVIDENCE**

This artifact is the provenance-bound next-open comparator for future
pre-registered formal gates. It grants no configuration authorization.

| Field | Value |
|---|---|
| Gate-code commit | `360aceda45087216124565fbcfaceca6f9d7dca2` |
| Cache schema | `flag-sweep-cache-v4` |
| Equity timing | `next_open` |
| Window | `2018-01-01` to `2026-07-14` |
| Effective observations | 2,143 |
| CAGR | 15.58% |
| MaxDD | -20.83% |
| Sharpe | 1.064 |
| Sortino | 1.336 |
| Turnover | 237.534782 |

Machine freshness result: `CURRENT_EXECUTION_EVIDENCE`; source provenance is
`CURRENT_SOURCE`, legacy parity is `MATCH`, and execution-required open missing
rows are zero. A direct post-build `assess_artifact_freshness` check returned
`FRESH` with no mismatches using the committed baseline config snapshot.

This is an eligible baseline input for future pre-registered formal gates. It
does not by itself authorize a feature or routing flip.

The same-close shadow is retained at
`building/reports/flag_sweep/baseline_legacy_close_equity.json`; it must not be
renamed to or substituted for `baseline_equity.json`.
