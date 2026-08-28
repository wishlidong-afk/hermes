# Hermes Five-Item Stabilization - Independent External Audit Prompt

You are an independent read-only auditor for Hermes. Audit the current working tree in:

`/Users/liweishi/Documents/github/hermes`

Baseline commit:

`ce96de01526dbb5a7bed84a2b9272b5c1c48da88`

The implementation is intentionally uncommitted. Audit `git diff HEAD` plus this prompt file. Do not trust the handoff, prior test counts, generated JSON, or author conclusions until you have inspected the producing code and independently reproduced the evidence.

## 0. Batch background and author claim

This batch follows repeated 20-dimension system and technical-debt reviews. New factors, WebUI features, and strategy experiments were deliberately paused. The narrow objective is to make existing system truth easier to verify without changing trading decisions:

1. Reconcile mutable current-fact documentation with code, baseline evidence, and the NAAIM runtime ledger.
2. Make decision-quality reporting distinguish disabled/research inputs from strategy-bearing inputs while keeping unknown inputs fail closed.
3. Decompose the monolithic Web health evaluator without changing its output.
4. Decompose market-admission rejection explanations without changing evidence classification.
5. Decompose morning-acceptance migration and health policies without changing their result ordering or severity.

Author-side self-review found no P0/P1/P2 issue. That is only a claim for this audit to challenge. The author has not committed, pushed, deployed, run daily, refreshed data, or touched live state.

Current expected working-tree state before the auditor starts:

- branch: `hermes-docs`
- baseline HEAD: `ce96de01526dbb5a7bed84a2b9272b5c1c48da88`
- 13 modified tracked files listed below
- this one untracked audit document
- tracked diff size before counting this untracked document: approximately `+1329/-528`

## 1. Hard safety restrictions

- Read-only audit only.
- Do not run daily or any official/manual scoring run against live data.
- Do not refresh market data or external sources.
- Do not connect to or refresh IBKR.
- Do not modify repo files, live files, shared runtime data, config, flags, or credentials.
- Do not commit, push, deploy, or install LaunchAgents.
- Use isolated temporary data roots for any replay/comparator work.

## 2. Declared implementation scope

Production/governance/docs:

- `context.md`
- `docs/FLAG_REGISTRY.md`
- `docs/PRODUCTION_RUNBOOK.md`
- `ops/morning_acceptance.py`
- `scripts/check_governance_consistency.py`
- `src/hermes_escape_top/core/data/source_relevance.py`
- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/web/health.py`

Tests:

- `src/hermes_escape_top/tests/test_governance_consistency.py`
- `src/hermes_escape_top/tests/test_health_truth.py`
- `src/hermes_escape_top/tests/test_morning_acceptance.py`
- `src/hermes_escape_top/tests/test_phase1_data_flow.py`
- `src/hermes_escape_top/tests/test_source_relevance.py`

This prompt is the only expected untracked documentation file. Any other changed or untracked file is scope drift and must be reported.

## 2.1 Implementation summary

### Item 1 - current facts and source relevance

- `source_relevance.py` adds `soft_record_is_decision_bearing()`.
- Effective source profiles remain the authority for registered records.
- `gex` uses its explicit `data_gex` feature flag because it has no active production source profile.
- Unknown records remain strategy-bearing to prevent a new unregistered source from silently escaping quality penalties.
- `pipeline.py` consumes this resolver only in quality-breakdown reporting.
- Governance now includes current baseline metrics and checks baseline/NAAIM prose against current evidence.

### Item 2 - health evaluator

- `compute_health()` delegates to `_HealthEvaluator.evaluate()`.
- The evaluator preserves the former rule order and public payload shape.
- Health layers remain `strategy_data`, `position_reconciliation`, `operations`, and `auxiliary_flows`.
- Top-level health remains the strategy-data level, so stale IBKR does not make the strategy unavailable.

### Item 3 - market-admission detail

- Rejected-row text was split into a shadow-support index, row formatter, and volume formatter.
- Component-only classification still requires all aggregate counts and every rejected row's role/impact metadata to agree.

### Item 4 - external migration observation

- AAII/NAAIM trusted automatic channels are centralized in one constant.
- Evidence validity, lifecycle policy, migration deadline, and summary construction are separate helpers.
- A missing or malformed precheck remains visible and does not become a pass.

### Item 5 - morning health policy

- Strategy, position, operations, and auxiliary policy are separate functions.
- Dollar's publisher-lag warning remains the only allowed strategy warning.
- IBKR stale/unavailable remains nonblocking INFO.
- Operations CRITICAL remains a failure; auxiliary degradation remains a warning.

## 3. Claimed changes to verify independently

### A. Current-facts governance

Verify all of the following:

- Disabled GEX is not decision-bearing in data-quality reporting.
- Enabled GEX is decision-bearing.
- Known research/auxiliary records are excluded from decision quality only when their effective source profile says so.
- Unknown records remain decision-bearing as a fail-closed default.
- The governance snapshot binds current baseline metrics.
- `current_facts_docs` rejects stale deployment-baseline facts and retirement-only NAAIM prose.
- NAAIM lifecycle documentation reflects runtime ledger authority and all four states: `ACTIVE_PUBLIC`, `ACTIVE_SUBSCRIBER`, `RETIRED_PAYWALL`, `PUBLIC_OFFICIAL_STABLE`.

### B. `compute_health` decomposition

Compare the pre-change implementation at HEAD with the working tree. Verify exact preservation of:

- rule evaluation order;
- check ordering;
- labels and details;
- strategy/position/operations/auxiliary layer assignment;
- receipt, IBKR, SIP, external-source, market-admission, and certification semantics;
- top-level output keys and overall strategy-level calculation.

Do not accept a complexity test as proof of behavioral equivalence.

### C. Market-admission explanation decomposition

Verify that rejected-row filtering, row order, shadow lookup key, price text, volume text, third-source text, truncation, and malformed-row behavior are unchanged. Confirm legacy or malformed evidence cannot be classified as component-only without all counts and row metadata agreeing.

### D. External migration observation decomposition

Verify exact old/new output for at least these scenarios:

- automatic AAII + public NAAIM success;
- missing precheck;
- manual/non-automatic channel;
- malformed issue date or SHA-256;
- NAAIM pre-deadline `MIGRATION_DUE`;
- post-deadline `MIGRATION_DUE`;
- certified `RETIRED_PAYWALL` history.

Confirm the centralized channel map did not broaden accepted channels.

### E. Morning health-policy decomposition

Verify exact failure/warning lists and order for:

- strategy OK;
- permitted Dollar-only strategy warning;
- non-Dollar strategy degradation;
- IBKR INFO;
- position degradation;
- operations CRITICAL/DEGRADED/INFO;
- auxiliary degradation with and without explicit check rows;
- duplicate warnings.

## 4. Mandatory safety sweep

Confirm with independent commands:

- branch is `hermes-docs` and baseline is the declared HEAD;
- diff contains only the declared files plus this prompt;
- `config/config.json`, dependency pins, and CI have no diff;
- no CSV/DB/DuckDB/SQLite/Parquet or secret/key/token/env file is present;
- no feature flag, scoring threshold, factor, routing, order path, or IBKR readonly policy changed;
- no live/shared runtime path was added to the diff.

## 5. Mandatory commands

Use the managed test interpreter and a synthetic FRED key so ambient credentials cannot influence identity tests:

```bash
cd /Users/liweishi/Documents/github/hermes
git status --short
git diff --check HEAD
git diff --stat HEAD
git diff HEAD -- src/hermes_escape_top/config/config.json requirements.txt requirements.lock pyproject.toml .github/workflows/ci.yml

FRED_API_KEY=external-audit-synthetic-key \
PYTHONPATH=src:src/hermes_escape_top/tests \
/Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_source_relevance.py \
  src/hermes_escape_top/tests/test_phase1_data_flow.py \
  src/hermes_escape_top/tests/test_governance_consistency.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py -q

FRED_API_KEY=external-audit-synthetic-key \
PYTHONPATH=src:src/hermes_escape_top/tests \
/Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q \
  src scripts ops

/Users/liweishi/.local/bin/uvx --offline ruff check \
  --select E9,F63,F7,F82 \
  ops/morning_acceptance.py scripts/check_governance_consistency.py \
  src/hermes_escape_top/core/data/source_relevance.py \
  src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/web/health.py \
  src/hermes_escape_top/tests/test_governance_consistency.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_phase1_data_flow.py \
  src/hermes_escape_top/tests/test_source_relevance.py
```

Expected author-side results are `1392 passed`, governance `8/8 OK`, compile clean, severe Ruff clean, and `git diff --check` clean. Treat any mismatch as a finding; do not explain it away as environment noise without reproducing it on baseline HEAD.

Author-side focused result: `111 passed` for the five changed test files listed above.

## 5.1 Author-side evidence inventory

The following files are ephemeral author evidence, not trusted audit conclusions:

| Evidence | Contract | SHA-256 | Author claim |
|---|---|---|---|
| `/tmp/hermes_current_facts_equivalence.json` | `decision-quality-v1` | `2ef6bedf30b81fff5cb01ef4b4ccf3cb6af65163eb94af9a4e81be5f0ecdf8b7` | four dates equal |
| `/tmp/hermes-item2-health-equivalence.json` | `strict` | `a952e02f33d025ea84f393f4c8a61f5b92131ecd772dd5aa0dd3b288080e79df` | four dates equal |
| `/tmp/hermes-item3-health-equivalence.json` | `strict` | `833e77e3bba04df700f9dab83e4f0ff2daaaf2380874d4742dec676d4faeb5c6` | four dates equal |
| `/tmp/hermes-item4-equivalence.json` | `strict` | `5b352d786a919b82dfeb0f7d301aef0aec46c52f76d7f9f44bbfc02d600ed925` | four dates equal |
| `/tmp/hermes-item5-equivalence.json` | `strict` | `b40700fba9ba84a8e5bb73d7e81dd83e42dc0a22c22d189703b1aceb5dfaa04d` | four dates equal |
| `/tmp/hermes-item5-final-verification.json` | `strict` | `add4ade2abb1b554b941d3b4ebb13c26fd777acd60244ba58aaeea2d707f3287` | fresh final rerun; all four `strict_differences=[]` |

The final Item 5 rerun used:

- baseline source: `/tmp/hermes-item5-baseline.D2tg0T`
- candidate source: `/Users/liweishi/Documents/github/hermes`
- seed data: `/tmp/hermes-item5-baseline.D2tg0T/src/hermes_escape_top/data`
- interpreter: `/Users/liweishi/.hermes-v3/.venv/bin/python`

The auditor must verify these paths and hashes still exist before relying on them. Missing ephemeral evidence is not itself a code failure; in that case rebuild equivalent isolated evidence.

## 6. Equivalence review

The author reports a sequential evidence chain under `/tmp`:

- `/tmp/hermes_current_facts_equivalence.json`: `decision-quality-v1`, four dates, `all_equal=true`
- `/tmp/hermes-item2-health-equivalence.json`: strict, four dates, `all_equal=true`
- `/tmp/hermes-item3-health-equivalence.json`: strict, four dates, `all_equal=true`
- `/tmp/hermes-item4-equivalence.json`: strict, four dates, `all_equal=true`
- `/tmp/hermes-item5-equivalence.json`: strict, four dates, `all_equal=true`

Required dates are `2022-06-30`, `2024-06-28`, `2026-05-29`, and `2026-07-10`.

Before relying on these files:

1. Inspect `scripts/compare_pipeline_persistence.py` and confirm source, seed, interpreter, payload, `input_hash`, status, and seven business artifacts are bound.
2. Verify each report's source hashes and per-date differences.
3. Independently rerun at least the final strict comparison from its frozen baseline source and seed evidence, or construct an equivalent isolated replay.
4. Explain why Item 1 uses `decision-quality-v1` rather than strict, and confirm its strict differences are confined to intended reporting metadata rather than decisions, factor scores, status, `input_hash`, or decision-quality persistence fields.

Do not call the reports independent proof merely because they say `all_equal=true`.

## 6.1 Known residual technical debt

The author intentionally did not expand this batch to fix three pre-existing C901 findings in `ops/morning_acceptance.py`:

- `_collect_release`: complexity 14
- `_collect_bound_health`: complexity 14
- `_market_admission_observation`: complexity 12

Verify they were not changed in this batch. Report them as residual debt, not as a newly introduced finding, unless the diff actually touches their behavior.

Additional declared residuals:

- Current-fact prose checks are intentionally line-oriented and fail closed. A future documentation table redesign must update checker and tests together.
- `_HealthEvaluator` remains policy-dense even though the public facade and individual rules are smaller.
- `/tmp` equivalence evidence is ephemeral and is not a durable audit archive.

## 7. Questions the final report must answer

1. Can any disabled known source still reduce strategy decision quality?
2. Can an unknown soft record be silently treated as nondecision?
3. Can stale baseline facts or an obsolete NAAIM lifecycle pass governance?
4. Did `compute_health` change any branch result, ordering, layer, or schema?
5. Can malformed market-admission data gain component-only treatment?
6. Did migration refactoring broaden trusted channels or weaken evidence freshness/fingerprint checks?
7. Did health-policy refactoring alter failure/warning ordering or allowed exceptions?
8. Are all claimed tests and governance results independently reproducible?
9. Did config, flags, scoring, routing, dependencies, IBKR policy, order paths, live data, or secrets change?
10. Is there any reason to block commit/push or R6 deployment?

Also state whether each declared residual risk is accurately scoped, understated, or masking a more serious issue.

## 8. Required report format

Report findings first, ordered P0 to P3, with exact absolute file and line references. Then provide:

- scope and drift verdict;
- five-area verdict;
- command/results table;
- equivalence verdict;
- safety-boundary verdict;
- residual risks;
- one final disposition:
  - `BLOCK`
  - `APPROVE COMMIT/PUSH ONLY`
  - `APPROVE R6 DEPLOY`

Commit approval and deployment approval are separate. A clean code audit does not itself authorize live deployment.

## 9. Disposition criteria

Use `BLOCK` when any of the following is true:

- a strategy decision, factor score, status, `input_hash`, or business persistence artifact changes unexpectedly;
- malformed/legacy evidence is treated more permissively;
- configuration, feature flags, routing, scoring, IBKR readonly policy, or an order path changes;
- tests/governance cannot be reproduced and the mismatch is introduced by this batch;
- scope contains live data, secrets, or undeclared implementation files.

Use `APPROVE COMMIT/PUSH ONLY` when the code is clean but deployment evidence or operational prerequisites are not independently established.

Use `APPROVE R6 DEPLOY` only when both code review and deployment safety review pass. Deployment, if later authorized by the user, must still:

- avoid the Beijing `07:00-07:20` window;
- confirm no daily/refresh writer is active;
- preserve live config;
- use the standard R6 release/symlink atomic path;
- avoid manually rerunning official daily as deployment validation;
- wait for the next natural scheduled run and morning acceptance for runtime certification.
