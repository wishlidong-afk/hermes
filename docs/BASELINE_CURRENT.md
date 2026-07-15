# Hermes Current Baseline

Generated: 2026-07-11

Status: **STALE**

The figures below remain a historical next-open reference. They are not valid
evidence for the current deployment because code, effective live data-source
flags, history and soft-history have advanced beyond commit `517043c`. No new
formal gate may use these artifacts until the final current-state rebuild.

## Evidence Status

**HISTORICAL EXECUTION EVIDENCE**. This baseline was bound to committed code, the
effective live configuration, frozen history and soft-history fingerprints, and
an explicit execution convention. It is a reference baseline only; it does not
authorize a feature or routing flip and is not a candidate gate result.

| Field | Value |
|---|---|
| Commit | `517043c2659de4a5d6d263ffd9f6b15e0a1c2ed9` |
| Cache schema | `flag-sweep-cache-v4` |
| Gate equity timing | `next_open` |
| Requested window | `2018-01-01` to `2026-07-10` |
| Effective window | `2018-01-02` to `2026-07-10` (2,141 trading days) |
| History manifest | `38525f67be5d4beb6c353b8313551ae53c476f566a75a79ede8a9e590e73653c` |
| Code SHA256 | `a04ba61e041bf6ca9b5efffd3acc5acd854eb6062dc41a238f2e37ac2e654a07` |
| Config SHA256 | `a7770b049c4b90bf88cd74fb1eab66841258921d40235f4cbce6f278828e90ea` |
| Soft-history SHA256 | `a30cf53c426656ca133f9dafe52cb4360984fafa919d1ecf3abf304fe4575e2f` |
| Authorization | `NO_CONFIG_FLIP` |

The live config and repo config differ only by an explicit versus missing
`use_indicator_cache=false`; both normalize to the same effective backtest
config after the proven byte-identical cache is enabled.

## Headline

The current headline is **next-open**, not same-close.

| Scenario | Role | CAGR | MaxDD | Sharpe | Sortino | Final value |
|---|---|---:|---:|---:|---:|---:|
| `next_open` | **Current baseline headline** | **15.90%** | **-19.07%** | **1.069** | **1.358** | **$350,116** |
| `legacy_close` | Historical/theoretical upper-bound shadow | 17.13% | -16.76% | 1.135 | 1.477 | $382,473 |
| `next_close` | One-trading-day delay sensitivity | 17.59% | -16.80% | 1.164 | 1.521 | $395,937 |
| `next_open_stress` | Next-open plus 25 bps per unit turnover | 8.12% | -24.78% | 0.601 | 0.758 | $194,091 |

Relative to same-close, realistic next-open execution reduces CAGR by about
1.23 percentage points and deepens MaxDD by about 2.31 percentage points. The
delay scenario improving in this sample is path-dependent sensitivity, not an
instruction to delay trading.

## Open Coverage

- Observed opens: 19,228 / 21,410 rows (89.81%).
- Modeled opens: 2,182 rows, concentrated in pre-inception FNGU (1,793) and
  DBMF (387), plus two proxy-switch rows.
- Missing opens: 0.
- Synthetic opens use an explicitly labeled geometric midpoint; they are not
  described as observed market prints.

During reconstruction, the old BTC quality rule was found to delete the real
2020-03-12 close of $4,970.79. Commit `98c4c79` replaced the fixed $5,000 floor
with a non-positive-price guard, and the full baseline was rerun afterward.

## Artifacts

- Full provenance source: `building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- Human summary: `building/reports/current_baseline/CURRENT_BASELINE_FULL.md`
- Execution report: `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`
- Gate metrics: `building/reports/flag_sweep/baseline.json`
- Gate equity: `building/reports/flag_sweep/baseline_equity.json`
- Same-close shadow: `building/reports/flag_sweep/baseline_legacy_close_equity.json`

`baseline.json` is explicitly `STALE`. Formal gates must refuse it until a new
cache v4 artifact is rebuilt from the current effective live configuration with
`equity_timing=next_open`; all prior v3 and same-close reports remain historical.
