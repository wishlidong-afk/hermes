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
| Gate-code commit | `b78e13e21b57e3b9553ab6ec86f320c613d5337b` |
| Cache schema | `flag-sweep-cache-v4` |
| Gate equity timing | `next_open` |
| Requested window | `2018-01-01` to `2026-07-17` |
| Effective window | `2018-01-02` to `2026-07-17` (2,146 trading days) |
| History manifest | `ea882f4bc91aaa91ab9f222f08c21f650a1282744cbb20e0e4e8122736cd7f9f` |
| Code SHA256 | `34b6fe4379f781fdfad5ee8ba602678ee5ee693b04ca3b9b55c4b14fb354df59` |
| Config SHA256 | `fada27925c9e64a6aed00b9cd10d80e18449792994ed18a39bb7510bb554ea68` |
| Soft-history SHA256 | `780bd54edf239e759ba0974e6021d98712629036fe488f0c79ffad56537811f4` |
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
| `next_open` | **Current baseline headline** | **15.46%** | **-20.83%** | **1.058** | **1.329** | **$340,054** |
| `legacy_close` | Historical/theoretical upper-bound shadow | 16.49% | -18.83% | 1.114 | 1.435 | $366,178 |
| `next_close` | One-trading-day delay sensitivity | 16.55% | -16.05% | 1.119 | 1.457 | $368,296 |
| `next_open_stress` | Next-open plus 25 bps per unit turnover | 7.66% | -26.36% | 0.578 | 0.721 | $187,475 |

Relative to same-close, realistic next-open execution reduces CAGR by about
1.03 percentage points and deepens MaxDD by about 2.00 percentage points. The
delay scenario improving in this sample is path-dependent sensitivity, not an
instruction to delay trading.

## Open Coverage

- Observed opens: 19,278 / 21,460 rows (89.83%).
- Modeled opens: 2,182 rows, concentrated in pre-inception FNGU (1,793) and
  DBMF (387), plus two proxy-switch rows.
- Full-panel missing opens: 0.
- Execution-required opens: 10,045; missing: 0. Headline eligibility uses this
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

The tracked gzip archive is the current `b78e13e` full-source evidence. It is
deterministic (`mtime=0`), decompresses byte-for-byte to payload SHA256
`36183fceecae60fffc35d53a171d312d88e15520d45104c4b16e551565262a20`,
and is the source for the timing, gate, and cost artifacts above.

The cost report reuses these recorded next-open decisions without rescoring. It
shows 0/5/10/25/50 bps extra-slippage sensitivity and reconciles turnover by
leg and by route-set change versus within-route weight rebalance. It is
diagnostic evidence only and carries `NO_CONFIG_FLIP`.
