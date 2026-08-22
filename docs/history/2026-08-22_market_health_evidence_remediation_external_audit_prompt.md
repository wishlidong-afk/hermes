# Hermes Market Health Evidence Remediation - External Audit Prompt

Date: 2026-08-22

Repository: `/Users/liweishi/Documents/github/hermes`

Branch: `hermes-docs`

Baseline commit: `2b91905`

Audit scope: `git diff HEAD` plus this untracked handoff document. The
implementation is intentionally uncommitted so the auditor reviews the exact
working tree before commit, push, or deployment.

## Auditor Role

Act as an independent, read-only reviewer. Do not modify repository files,
live data, runtime config, feature flags, IBKR state, or services. Do not run
`daily`, refresh market/external data, connect to IBKR, deploy, commit, or push.

Do not accept this handoff or generated reports as proof by themselves. Inspect
the implementation, tests, and comparator, then reproduce the evidence.

Report findings first in P0/P1/P2/P3 order with exact file and line references.
If there are no findings, state that explicitly and list residual risks.

## Incident Being Remediated

The 2026-08-22 morning acceptance failed even though the official scheduled run
was fresh and transactionally complete:

- Scheduled `as_of=2026-08-21`, receipt/audit/transaction all passed.
- Market admission quarantined one row: `KLAC 2026-08-21 VOLUME_MISMATCH`.
- Yahoo and Alpaca volume differed by 25.4565%; OHLC matched. A delayed third
  source was within policy of both sources.
- KLAC is used only by SOXL component-flow scoring, but the old health policy
  degraded the entire strategy chain.
- The SOXL component-flow explanation incorrectly counted the prior certified
  KLAC row as current coverage (`10/10`) after the new candidate was rejected.
- The 06:45 external precheck had successfully checked Dollar and classified it
  as a policy warning. The 07:05 retry-only run omitted Dollar, then overwrote
  latest readiness as blocking because it ignored the same-day successful row.

The remediation must preserve fail-closed market admission and historical
scoring while making health impact proportional to the rejected symbol's real
decision role.

## Required Behavior

### R1 - Retry-only precheck preserves same-day Dollar evidence

Inspect:

- `src/hermes_escape_top/scripts/refresh_external.py`
- `src/hermes_escape_top/tests/test_refresh_external_cli.py`

Required contract:

1. A 07:05 retry-only run may reuse a source row omitted from that retry only
   when the row was checked on the same Shanghai operating day and its latest
   attempt status is `OK`.
2. Publisher-policy stale Dollar remains `ready=true` and appears in
   `policy_warning_sources` after that reuse.
3. A current failed run, prior-day row, evidence drift, or non-OK attempt must
   remain blocking. The fix must not turn general stale data into a warning.

### R2 - Verified Dollar publication delay is operational, not strategic

Inspect:

- `src/hermes_escape_top/web/health.py`
- `src/hermes_escape_top/tests/test_health_truth.py`

Required contract:

Dollar stale data may move from the strategy layer to an operations warning
only when all of these are true:

- The source profile explicitly enables `warn_only_stale_after_refresh`.
- The latest attempt is `OK` and occurred on the current Shanghai day.
- Publisher calendar status is `VERIFIED`.
- Latest expected release status is `ADVANCED`.
- Expected-release grace status is `MATCHED`.

Ordinary stale data, failed refresh, missing evidence, or any absent condition
must continue to degrade the strategy layer.

### R3 - Market-admission evidence carries decision impact without admitting data

Inspect:

- `src/hermes_escape_top/core/data/market_admission.py`
- `src/hermes_escape_top/core/data/market_witness.py`
- `src/hermes_escape_top/scripts/backfill_history.py`
- `src/hermes_escape_top/scripts/run_daily_package.py`
- `src/hermes_escape_top/tests/test_market_admission.py`
- `src/hermes_escape_top/tests/test_backfill_guard.py`
- `src/hermes_escape_top/tests/test_run_daily_external_sources.py`

Required contract:

1. The existing `market_admission_field_inventory(config)` is the single role
   source. Daily and standalone backfill must both inject it into the admission
   session. No duplicate symbol-role list is allowed.
2. Evidence rows include `decision_roles` and `decision_impact` when an
   inventory is present.
3. Only a non-empty role set containing solely `component_flow` may be marked
   `COMPONENT_FLOW_ONLY`. Missing, unknown, mixed, or other roles must be
   `STRATEGY_BLOCKING`.
4. `strategy_blocking_rejected_rows` and
   `component_flow_rejected_rows` must reconcile exactly to rejected rows.
5. Both v1 and v2 evidence validation must fail closed as `EVIDENCE_DRIFT` when
   roles, impact, or counts are inconsistent.
6. A rejected KLAC row must remain rejected, global admission status must remain
   `BLOCKED`, and canonical history must remain frozen. This change must not
   lower the 25% policy threshold, use the third source as an automatic tie
   breaker, or silently promote any candidate row.
7. Legacy evidence without impact metadata remains strategy-blocking.

### R4 - Health impact is proportional and fail-closed

Inspect:

- `src/hermes_escape_top/web/health.py`
- `src/hermes_escape_top/tests/test_health_truth.py`

Required contract:

1. A `BLOCKED` payload is auxiliary-only only when:
   - rejected count is positive;
   - strategy rejection count is exactly zero;
   - component rejection count equals total rejected count;
   - every blocking rejected row has exact role set `{component_flow}` and
     impact `COMPONENT_FLOW_ONLY`.
2. That case renders `穿透成分行情候选已隔离` in the
   `auxiliary_flows` layer and does not degrade overall strategy health.
3. Core, mixed, malformed, or legacy rejection evidence continues to render
   `双源行情候选已隔离` in `strategy_data` and remains DEGRADED.
4. `EVIDENCE_DRIFT` remains CRITICAL.

### R5 - Component scoring excludes only the current explicit quarantine

Inspect:

- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/core/scoring/registry.py`
- `src/hermes_escape_top/core/scoring/scorer.py`
- `src/hermes_escape_top/core/scoring/module_d.py`
- `src/hermes_escape_top/tests/test_phase3_scoring.py`

Required contract:

1. The pipeline derives exclusions only from blocking, rejected rows whose
   date equals the resolved score `as_of`, role set is exactly
   `{component_flow}`, and impact is `COMPONENT_FLOW_ONLY`.
2. Explicitly quarantined KLAC is omitted from SOXL component-flow coverage,
   producing `9/10 obs` rather than `10/10 obs`.
3. An older rejection row, strategy-role rejection, admitted row, malformed
   row, or absent admission payload must not exclude a component.
4. Historical component observations are not generically discarded merely
   because their field date differs from the primary symbol date. Historical
   replay without current admission evidence must remain byte-identical.
5. Backtests call `score_symbol` without exclusions and retain prior behavior.

## Safety Invariants

Verify all of the following:

- `config/config.json` has zero diff.
- No feature flag, scoring threshold, route, module cap, or IBKR policy changed.
- `ibkr_readonly` remains true in governance evidence.
- No production order-submission path was introduced.
- No live/shared CSV, SQLite, DuckDB, Parquet, secret, token, or credential is
  part of the diff.
- No official daily, market refresh, external refresh, IBKR operation, or live
  deployment is required to reproduce the audit.

## Required Commands

Run from `/Users/liweishi/Documents/github/hermes`.

### Scope and diff

```bash
git status -sb
git diff --check
git diff --stat HEAD
git diff HEAD -- config/config.json
git diff HEAD --name-only
```

### Focused tests

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_market_admission.py \
  src/hermes_escape_top/tests/test_market_witness.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_refresh_external_cli.py \
  src/hermes_escape_top/tests/test_phase3_scoring.py \
  src/hermes_escape_top/tests/test_run_daily_external_sources.py \
  src/hermes_escape_top/tests/test_backfill_guard.py -q
```

Expected implementation-run result: `263 passed`.

### Full suite

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

Expected implementation-run result: `1382 passed`.

### Governance, compile, and severe static checks

```bash
PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q src scripts ops

git diff --name-only -- '*.py' | \
  xargs /Users/liweishi/.local/bin/uvx --offline ruff check \
  --select E9,F63,F7,F82
```

Expected results: governance `7/7 OK`, compile clean, Ruff clean.

### Independent four-date and seven-artifact equivalence

Inspect `scripts/compare_pipeline_persistence.py` before trusting it. Confirm it
uses fresh isolated data roots, compares full normalized payloads and seven
business persistence artifacts, and binds source/seed/interpreter fingerprints.

Then reproduce against baseline `2b91905`:

```bash
BASE=$(mktemp -d /tmp/hermes-audit-base.XXXXXX)
rmdir "$BASE"
git worktree add --detach "$BASE" 2b91905

/Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASE" \
  --candidate-source /Users/liweishi/Documents/github/hermes \
  --seed-data /Users/liweishi/Documents/github/hermes/src/hermes_escape_top/data \
  --as-of 2022-06-30 \
  --as-of 2024-06-28 \
  --as-of 2026-05-29 \
  --as-of 2026-07-10 \
  --python /Users/liweishi/.hermes-v3/.venv/bin/python \
  --output /tmp/hermes_2026_08_22_external_audit_equivalence.json \
  --baseline-label 2b91905 \
  --candidate-label external-audit-working-tree

git worktree remove "$BASE"
```

Expected result: `all_equal=true`; every date has `equal=true`, no differences,
identical `input_hash`, score status, and seven business artifacts.

The implementation author's final local evidence is available only as a
cross-check, not independent proof:

`/tmp/hermes_2026_08_22_health_remediation_equivalence_final.json`

## Independent Audit Questions

Answer every question explicitly:

1. Can a retry-only precheck reuse a prior-day or failed Dollar row?
2. Can a general stale source masquerade as a publisher-policy warning?
3. Can missing role metadata classify a rejection as auxiliary-only?
4. Can inconsistent impact counts pass either v1 or v2 validation?
5. Can a component-only rejection be admitted or rewrite canonical history?
6. Can a core-symbol, mixed-role, malformed, or legacy rejection avoid strategy
   degradation?
7. Can an older component rejection suppress the current component-flow score?
8. Can historical replay lose component observations merely because dates differ?
9. Does the current-day KLAC quarantine produce 9/10 coverage without changing
   the historical four-date score outputs?
10. Did any change touch config, thresholds, routing, flags, IBKR authority,
    order execution, secrets, or live data?
11. Do focused tests, full tests, governance, compile, static checks, and strict
    four-date equivalence all reproduce independently?
12. Is any generated report being treated as proof without inspecting its
    source data and comparator?

## Required Verdict

Return separate verdicts:

1. `APPROVE COMMIT/PUSH` or `BLOCK COMMIT/PUSH`.
2. `APPROVE R6 DEPLOY` or `BLOCK R6 DEPLOY`.

Deployment approval must additionally state this operational caveat:

- Deploying code alone will not rewrite the existing 2026-08-21 admission
  evidence. The dashboard may remain strategy-DEGRADED because legacy evidence
  intentionally fails closed. The new role metadata must come from the next
  natural scheduled admission run. Do not solve this by manually rerunning an
  official daily during audit or deployment.

If approved, recommend: commit and push first, perform one R6 deployment while
no writer is active and outside 07:00-07:20 Beijing time, preserve live config,
then wait for the natural 07:10 run and verify the 09:00 watchdog plus morning
acceptance. Dollar may remain an operations warning and IBKR may remain INFO;
neither alone should block strategy health.
