# 2026-07-11 Research Evidence External Audit Handoff

## Status

Steps 1-4 of the 2026-07-10 single-agent review remediation are implemented and
verified in the repository. They are not deployed to live.

- Repository branch: `hermes-docs`
- Evidence source commit: `517043c2659de4a5d6d263ffd9f6b15e0a1c2ed9`
- Live version at handoff time: `4a0c20c`
- Full suite at the evidence source commit: `743 passed`
- Research data directory: isolated clone of the live shared data root
- Headline equity convention: decision at close, execution at next available open

The generated baseline files are deliberately bound to the source commit above.
Committing this handoff or later operational code changes moves repository `HEAD`
without changing the research result. Auditors must validate the recorded source
commit and content fingerprints, rather than silently treating a later `HEAD` as
the code that produced the evidence.

## Audit Scope

Review these three commits in order:

1. `e2b6dab research: harden gate and execution baseline evidence`
2. `98c4c79 fix: preserve the real 2020 btc crash bar`
3. `517043c research: gate on next-open equity`

The intended outcomes are:

1. The misleading single-configuration pseudo-PBO path is no longer presented as
   formal PBO evidence.
2. Formal gate evidence uses pre-registered in-sample selection and untouched
   out-of-sample evaluation, with CPCV/PBO and DSR reported separately.
3. Cache identity includes the equity timing convention; next-open and legacy
   close curves cannot collide.
4. Headline gate and baseline metrics use next-open execution, while legacy-close
   output remains an explicitly labeled comparison artifact.
5. Execution timing sensitivity covers next open, next close, and stressed costs.
6. The BTC history loader preserves the real 2020-03-12 close of `4970.79` instead
   of deleting it with a fixed post-2020 price floor.

## Evidence Files

Current baseline:

- `building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- `building/reports/current_baseline/CURRENT_BASELINE_FULL.md`
- `building/reports/current_baseline/CURRENT_BASELINE_EQUITY.json`
- `docs/BASELINE_CURRENT.md`
- `building/reports/flag_sweep/GATE_BASELINE_CURRENT.md`

Execution sensitivity:

- `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.json`
- `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`
- `docs/history/2026-07-11_execution_timing_sensitivity.md`

Legacy comparison:

- `building/reports/flag_sweep/baseline_legacy_close_equity.json`
- `docs/history/BASELINE_2026_06_11.md`

Implementation and tests:

- `src/hermes_escape_top/core/backtest/formal_gate.py`
- `src/hermes_escape_top/core/backtest/execution.py`
- `src/hermes_escape_top/core/backtest/gate_policy.py`
- `scripts/formal_gate.py`
- `scripts/build_current_baseline.py`
- `scripts/execution_timing_sensitivity.py`
- `scripts/flag_gate.py`
- `scripts/backtest_flag_sweep.py`
- `src/hermes_escape_top/tests/test_formal_gate.py`
- `src/hermes_escape_top/tests/test_execution_timing.py`
- `src/hermes_escape_top/tests/test_flag_sweep_cache.py`
- `src/hermes_escape_top/tests/test_research_evidence_freeze.py`

## Recorded Evidence

The machine-readable baseline records:

- Requested window: `2018-01-01` through `2026-07-10`
- Effective window: `2018-01-02` through `2026-07-10`
- Trading days: `2141`
- History manifest SHA-256:
  `38525f67be5d4beb6c353b8313551ae53c476f566a75a79ede8a9e590e73653c`
- Code SHA-256:
  `a04ba61e041bf6ca9b5efffd3acc5acd854eb6062dc41a238f2e37ac2e654a07`
- Config SHA-256:
  `a7770b049c4b90bf88cd74fb1eab66841258921d40235f4cbce6f278828e90ea`
- Soft-history SHA-256:
  `a30cf53c426656ca133f9dafe52cb4360984fafa919d1ecf3abf304fe4575e2f`
- Cache schema: `flag-sweep-cache-v4`
- Equity timing: `next_open`
- Freshness status: `FRESH`
- Execution evidence status: `CURRENT_EXECUTION_EVIDENCE`
- Legacy parity status: `MATCH`
- Observed next-open coverage: `0.89808501`
- Modeled open rows: `2182`
- Missing execution rows: `0`

Headline next-open metrics:

| Metric | Value |
|---|---:|
| CAGR | 15.9004% |
| Final equity | 350,116.13 |
| Max drawdown | -19.0659% |
| Sharpe | 1.069482 |
| Sortino | 1.358219 |
| Turnover | 235.720287 |

Sensitivity anchors:

| Convention | CAGR | Max drawdown | Sharpe |
|---|---:|---:|---:|
| Legacy same-close | 17.1269% | -16.7591% | 1.135009 |
| Next close | 17.5911% | -16.8018% | 1.164233 |
| Next open + 25 bps | 8.1221% | -24.7800% | 0.600812 |

## Required Audit Questions

1. Does any formal report still derive PBO from a single configuration reshaped
   into a matrix?
2. Is model selection performed only on the in-sample side of each split before
   evaluating the selected candidate out of sample?
3. Are PBO/CPCV, DSR, walk-forward performance, and execution sensitivity kept as
   distinct claims rather than collapsed into one pass number?
4. Can a legacy-close cache entry be reused by a next-open run?
5. Do gate reports and `variant_equity.json` use next-open equity by default?
6. Is legacy-close equity still available only as a clearly labeled comparison?
7. Does the BTC loader retain `2020-03-12 = 4970.79` and still reject nonpositive
   observations?
8. Do the baseline JSON fingerprints match the files actually used in the audit?
9. Does rebuilding from the recorded source commit and isolated data reproduce the
   headline metrics within the report's numeric precision?
10. Are any uncommitted workspace files being mistaken for part of the three-commit
    implementation scope?

## Recommended Commands

```bash
cd /Users/liweishi/Documents/github/hermes

git show --stat e2b6dab
git show --stat 98c4c79
git show --stat 517043c
git diff --check 4a0c20c..517043c

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_formal_gate.py \
  src/hermes_escape_top/tests/test_formal_gate_cli.py \
  src/hermes_escape_top/tests/test_execution_timing.py \
  src/hermes_escape_top/tests/test_execution_timing_cli.py \
  src/hermes_escape_top/tests/test_flag_sweep_cache.py \
  src/hermes_escape_top/tests/test_current_baseline_builder.py \
  src/hermes_escape_top/tests/test_research_evidence_freeze.py -q

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

For an exact baseline rebuild, check out source commit `517043c` in a clean
worktree and set `HERMES_DATA_DIR` to an isolated clone of the live shared data
root. Do not point research runs at the writable live data directory.

## Explicit Exclusions

- No live deployment is part of this handoff.
- No production flag is flipped.
- No full-window gate should be rerun against the package data directory.
- The unrelated dirty deploy/watchdog work present in the main workspace is not
  part of these three commits and must not be staged, reverted, or audited as
  research evidence.
- Steps 5-7 from the 20-dimension remediation remain separate implementation
  batches: cross-store crash recovery, confidence separation, and governance
  cleanup.

## Pass Condition

External audit may mark Steps 1-4 `PASS` only if the source commit, four content
fingerprints, next-open curve, legacy parity, BTC crash-bar regression, focused
tests, and full suite all agree. A document that merely says `FRESH` is not
sufficient evidence.
