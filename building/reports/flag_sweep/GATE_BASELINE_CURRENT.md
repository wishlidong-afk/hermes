# Current Formal-Gate Baseline

Status: **FRESH**

| Field | Value |
|---|---|
| Commit | `517043c2659de4a5d6d263ffd9f6b15e0a1c2ed9` |
| Cache schema | `flag-sweep-cache-v4` |
| Equity timing | `next_open` |
| Window | `2018-01-01` to `2026-07-10` |
| Effective observations | 2,141 |
| CAGR | 15.90% |
| MaxDD | -19.07% |
| Sharpe | 1.069 |
| Sortino | 1.358 |
| Turnover | 235.720287 |

Machine freshness result: `FRESH`, mismatches `[]`.

This is the baseline input for future pre-registered formal gates. It is not a
candidate PASS and grants no configuration authorization. Candidate artifacts
must use the same cache v4 provenance dimensions and next-open execution timing.

The same-close shadow is retained at
`building/reports/flag_sweep/baseline_legacy_close_equity.json`; it must not be
renamed to or substituted for `baseline_equity.json`.
