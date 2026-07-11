# Execution Timing Sensitivity - Step 3 Handoff

Date: 2026-07-11

## Scope

This step adds a research-only execution timing layer. It does not change live scoring,
routing, position advice, production config, or IBKR behavior. It also does not run or
consume a formal experiment gate budget.

The executable scenarios are fixed as:

| Scenario | Meaning | Research role |
|---|---|---|
| `legacy_close` | A close-generated target is treated as filled at that same close | Historical/theoretical upper-bound convention only |
| `next_open` | Old holdings receive the close-to-next-open gap; the pending target fills at the next open | Primary realistic convention for the next baseline |
| `next_close` | The pending target fills at the following close | One-trading-day delay sensitivity |
| `next_open_stress` | `next_open` plus 25 bps extra cost per unit of executed turnover | Execution stress |

The last signal in a replay remains pending when no following trading day exists. Missing
required Open or Close values fail closed with an error; they never fall back silently.

## Synthetic Open Policy

Historical synthetic leveraged rows store flat OHLC and zero volume, so their `Open` is not
an observed print. The research frame replaces that placeholder with the geometric midpoint
between the prior and current normalized close and labels it
`MODELED_SYNTHETIC_MIDPOINT`. A proxy source switch is flattened for one day and labeled
`MODELED_PROXY_SWITCH`. Original history files are not modified.

Every report exposes observed, modeled, and missing open counts globally and by leg. A future
baseline must disclose this coverage; modeled values must not be described as market prints.

## Read-Only Methodology Run

Source: `building/reports/Backtest_FULL_2018_2026.json`

Output:

- `building/reports/execution_timing/EXECUTION_TIMING_SENSITIVITY.json`
- `building/reports/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`

The source is an old artifact without the required commit/code/config/data provenance, so the
result is correctly locked to `METHODOLOGY_ONLY` and `NO_CONFIG_FLIP`.

Legacy parity is `MATCH`: final value, CAGR, MaxDD, Sharpe, Sortino, and turnover are exactly
equal to the source artifact. Open coverage is 14,722 observed rows (87.09%), 2,182 modeled
rows, and zero missing rows. Modeled rows are concentrated in pre-inception FNGU and DBMF
history.

The old-source numbers below validate mechanics only and are not a current baseline:

| Scenario | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|
| `legacy_close` | 18.13% | -27.60% | 0.882 |
| `next_open` | 18.75% | -25.02% | 0.900 |
| `next_close` | 20.68% | -23.50% | 0.967 |
| `next_open_stress` | 7.71% | -33.56% | 0.450 |

Delayed execution improving this old replay is not evidence that delay is beneficial. Gap
attribution is path-dependent in both directions, and this source is stale. Step 4 must rerun
the current deployment state before interpreting any scenario delta.

## Verification

- Synthetic gap attribution tests prove old holdings retain the post-signal overnight gap.
- Synthetic intraday tests prove new holdings begin earning only after the selected execution point.
- Next-close and extra-slippage behavior have direct tests.
- Missing Open values fail closed.
- Legacy mode is byte-equivalent to the existing simulator.
- Source provenance and legacy parity are machine fields, not report prose only.

## Step 4 Entry Conditions

1. Generate one current full-backtest source with commit, code hash, config hash, history
   manifest, soft-history hash, and window provenance embedded.
2. Run `scripts/execution_timing_sensitivity.py` against that exact source.
3. Require `legacy_source_parity=MATCH`, zero missing required opens, and
   `evidence_status=CURRENT_EXECUTION_EVIDENCE`.
4. Use `next_open` as the baseline headline; retain `legacy_close` only as a historical upper
   bound and publish modeled-open coverage next to the metrics.
5. Keep the 25 bps stress scenario as sensitivity, not as a tuned model parameter.

Residual limitations remain: no partial fills, intraday VWAP, bid/ask depth, taxes, or actual
IBKR execution replay. Those are execution-quality extensions, not blockers for replacing the
same-close assumption.
