# Hermes Current Baseline

Generated: 2026-07-20

Status: **CURRENT EXECUTION EVIDENCE**

This baseline was rebuilt after code freeze from the effective live
configuration and an isolated clone of current live history/soft-history. It is
the eligible comparator for future pre-registered formal gates.

## Evidence Status

**CURRENT EXECUTION EVIDENCE**. This baseline is bound to committed code, the
effective live configuration, frozen history and soft-history fingerprints, and
an explicit execution convention. It is a comparator only; it does not
authorize a feature or routing flip and is not a candidate gate result.

| Field | Value |
|---|---|
| Gate-code commit | `02a19538c43f32dfeffa535922dd1a24c3a95ae6` |
| Cache schema | `flag-sweep-cache-v4` |
| Gate equity timing | `next_open` |
| Requested window | `2018-01-01` to `2026-07-14` |
| Effective window | `2018-01-02` to `2026-07-14` (2,143 trading days) |
| History manifest | `ea882f4bc91aaa91ab9f222f08c21f650a1282744cbb20e0e4e8122736cd7f9f` |
| Code SHA256 | `7910dc9dfa1fec7cf75e93511aef4a11e8bf57979da69e6cd457a5976c894b65` |
| Config SHA256 | `7de18c09ee2d245851fbf8dc682abc5eac521e5312508b09155307bdb26a6e56` |
| Soft-history SHA256 | `780bd54edf239e759ba0974e6021d98712629036fe488f0c79ffad56537811f4` |
| Authorization | `NO_CONFIG_FLIP` |

The evidence uses the effective live config as its explicit source. The proven
byte-identical indicator cache is enabled only for replay performance; all
other live feature states remain unchanged.

The normalized config is committed at
`building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json`. Candidate
sweeps and formal-gate freshness checks use this snapshot by default. The
`git_commit` field means the latest commit touching gate-affecting code or repo
config, so committing evidence documents cannot invalidate their own baseline.

## Headline

The current headline is **next-open**, not same-close.

| Scenario | Role | CAGR | MaxDD | Sharpe | Sortino | Final value |
|---|---|---:|---:|---:|---:|---:|
| `next_open` | **Current baseline headline** | **15.58%** | **-20.83%** | **1.064** | **1.336** | **$342,337** |
| `legacy_close` | Historical/theoretical upper-bound shadow | 16.61% | -18.83% | 1.121 | 1.443 | $368,899 |
| `next_close` | One-trading-day delay sensitivity | 16.71% | -16.05% | 1.128 | 1.468 | $371,937 |
| `next_open_stress` | Next-open plus 25 bps per unit turnover | 7.77% | -26.36% | 0.585 | 0.729 | $188,919 |

Relative to same-close, realistic next-open execution reduces CAGR by about
1.03 percentage points and deepens MaxDD by about 2.00 percentage points. The
delay scenario improving in this sample is path-dependent sensitivity, not an
instruction to delay trading.

## Open Coverage

- Observed opens: 19,248 / 21,430 rows (89.82%).
- Modeled opens: 2,182 rows, concentrated in pre-inception FNGU (1,793) and
  DBMF (387), plus two proxy-switch rows.
- Full-panel missing opens: 0.
- Execution-required opens: 10,033; missing: 0. Headline eligibility uses this
  stricter executable set, while the full-panel gap remains visible.
- Synthetic opens use an explicitly labeled geometric midpoint; they are not
  described as observed market prints.

During reconstruction, the old BTC quality rule was found to delete the real
2020-03-12 close of $4,970.79. Commit `98c4c79` replaced the fixed $5,000 floor
with a non-positive-price guard, and the full baseline was rerun afterward.

## Artifacts

- Full provenance source: `building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz`
- Human summary: `building/reports/current_baseline/CURRENT_BASELINE_FULL.md`
- Execution report: `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`
- Gate metrics: `building/reports/flag_sweep/baseline.json`
- Gate equity: `building/reports/flag_sweep/baseline_equity.json`
- Same-close shadow: `building/reports/flag_sweep/baseline_legacy_close_equity.json`
- Cost curve and turnover attribution: `building/reports/current_baseline/cost_robustness/COST_ROBUSTNESS.md`

`baseline.json` is explicitly `CURRENT_EXECUTION_EVIDENCE` with
`equity_timing=next_open`. Formal gates may use it as the comparator; all prior
v3, same-close, and mismatched-provenance reports remain historical.

The tracked gzip archive is deterministic (`mtime=0`). Governance decompresses
it and verifies the uncompressed SHA-256 recorded by the execution-timing
artifact, so a missing, truncated, or substituted source fails closed.

The cost report reuses these recorded next-open decisions without rescoring. It
shows 0/5/10/25/50 bps extra-slippage sensitivity and reconciles turnover by
leg and by route-set change versus within-route weight rebalance. It is
diagnostic evidence only and carries `NO_CONFIG_FLIP`.
