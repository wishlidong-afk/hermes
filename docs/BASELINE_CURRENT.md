# Hermes Current Baseline

Generated: 2026-07-22

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
| Gate-code commit | `b23cf124b5b906d897884f2774d354b8cae23d1a` |
| Cache schema | `flag-sweep-cache-v4` |
| Gate equity timing | `next_open` |
| Requested window | `2018-01-01` to `2026-07-21` |
| Effective window | `2018-01-02` to `2026-07-21` (2,148 trading days) |
| History manifest | `cf06acc7c2454c6fbbb7038f9ae8e56a6fa50ada5dd36a19e219ecec0f21b8e2` |
| Code SHA256 | `d71017e0c1c3ce8373485aa4757db4f9ef85383b17700af0708b3abac60305a6` |
| Config SHA256 | `fada27925c9e64a6aed00b9cd10d80e18449792994ed18a39bb7510bb554ea68` |
| Soft-history SHA256 | `837dab78e922cea360c2da8e769163733507fed579920a07ab4051c578de5721` |
| Approved live semantic SHA256 | `c6060e55825f85462e2a8d567d8a6c2b20a771c40884ea721b8f23f730b704f9` |
| Approved-live policy SHA256 | `8152c0d1a4adce45caceb413f9182f0de0b95918e70007b8140d16e9712a0aeb` |
| Normalized replay config SHA256 | `e528980ae9d029c50bde7536e9db427b211137ed887d594cbd510f7add49c82a` |
| Authorization | `NO_CONFIG_FLIP` |

The evidence uses the effective live config as its explicit source. The proven
byte-identical indicator cache is enabled only for replay performance; all
other live feature states remain unchanged.

The builder validates that config against the committed approved-live policy
before scoring. Repo defaults or an unapproved live/config drift fail closed
instead of silently becoming the deployment baseline.

The normalized config is committed at
`building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json`. Candidate
sweeps and formal-gate freshness checks use this snapshot by default. The
`git_commit` field means the latest commit touching gate-affecting code or repo
config, so committing evidence documents cannot invalidate their own baseline.

## Headline

The current headline is **next-open**, not same-close.

| Scenario | Role | CAGR | MaxDD | Sharpe | Sortino | Final value |
|---|---|---:|---:|---:|---:|---:|
| `next_open` | **Current baseline headline** | **15.56%** | **-20.83%** | **1.064** | **1.335** | **$342,742** |
| `legacy_close` | Historical/theoretical upper-bound shadow | 16.52% | -18.83% | 1.116 | 1.438 | $367,570 |
| `next_close` | One-trading-day delay sensitivity | 16.69% | -16.05% | 1.128 | 1.468 | $372,483 |
| `next_open_stress` | Next-open plus 25 bps per unit turnover | 7.75% | -26.36% | 0.584 | 0.728 | $188,893 |

Relative to same-close, realistic next-open execution reduces CAGR by about
0.97 percentage points and deepens MaxDD by about 2.00 percentage points. The
delay scenario improving in this sample is path-dependent sensitivity, not an
instruction to delay trading.

## Open Coverage

- Observed opens: 19,297 / 21,480 rows (89.84%).
- Modeled opens: 2,182 rows, concentrated in pre-inception FNGU (1,793) and
  DBMF (387), plus two proxy-switch rows.
- Full-panel missing opens: 1 (an unused BTC-USD row).
- Execution-required opens: 10,053; missing: 0; modeled: 1,343 (13.36%).
  Headline eligibility uses this stricter executable set, while the full-panel
  gap remains visible.
- Synthetic opens use an explicitly labeled geometric midpoint; they are not
  described as observed market prints.

During reconstruction, the old BTC quality rule was found to delete the real
2020-03-12 close of $4,970.79. Commit `98c4c79` replaced the fixed $5,000 floor
with a non-positive-price guard, and the full baseline was rerun afterward.

## Artifacts

- Full provenance source: `building/reports/current_baseline/CURRENT_BASELINE_FULL.json.gz`
- Human summary: `building/reports/current_baseline/CURRENT_BASELINE_FULL.md`
- Legacy-close source curve: `building/reports/current_baseline/CURRENT_BASELINE_EQUITY.json`
- Execution report: `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`
- Gate metrics: `building/reports/flag_sweep/baseline.json`
- Gate equity: `building/reports/flag_sweep/baseline_equity.json`
- Same-close shadow: `building/reports/flag_sweep/baseline_legacy_close_equity.json`
- Cost curve and turnover attribution: `building/reports/current_baseline/cost_robustness/COST_ROBUSTNESS.md`

`baseline.json` is explicitly `CURRENT_EXECUTION_EVIDENCE` with
`equity_timing=next_open`. Formal gates may use it as the comparator; all prior
v3, same-close, and mismatched-provenance reports remain historical.

Despite its historical filename, `CURRENT_BASELINE_EQUITY.json` is the
legacy-close curve embedded in the full provenance source. It is not the formal
gate curve; formal gates use `building/reports/flag_sweep/baseline_equity.json`.

The tracked gzip archive is the current `b23cf12` full-source evidence. It is
deterministic (`mtime=0`), decompresses byte-for-byte to payload SHA256
`84ba67caee68c090a15b48821aa49cdfdfff45dc882cea811681a8446dd2ed3e`,
and is the source for the timing, gate, and cost artifacts above.

The cost report reuses these recorded next-open decisions without rescoring. It
shows 0/5/10/25/50 bps extra-slippage sensitivity and reconciles turnover by
leg and by route-set change versus within-route weight rebalance. It is
diagnostic evidence only and carries `NO_CONFIG_FLIP`.
