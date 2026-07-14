# ADR-001: PIT Data-Correctness Migrations

Status: Accepted  
Date: 2026-07-14  
Scope: Historical and live data inputs used by Hermes scoring

## Context

Hermes has historically used one formal gate for every behavior-affecting
change. That gate is intentionally strict for alpha research: a candidate must
show fresh out-of-sample benefit, bounded drawdown damage, and acceptable
overfitting evidence before a human may flip it live.

That rule is correct for a new signal, threshold, route, or sizing mechanism.
It is incomplete for a data-correctness migration. Replacing an approximate
publication rule with the source's actual point-in-time event history may lower
backtested returns precisely because the old data contained accidental
look-ahead. Rejecting the more truthful data solely because it lowers CAGR
would preserve a known measurement defect.

The two cases therefore need different decision gates while sharing the same
requirements for reproducibility, impact disclosure, human approval, and
rollback.

## Decision

Hermes has two mutually exclusive governance lanes.

### Alpha Experiment Gate

Use this lane for a new factor, transformation, threshold, routing rule,
position-sizing rule, or any change whose justification is improved investment
performance.

- Pre-register one hypothesis and one candidate set.
- Run the formal WF/CPCV/PBO/DSR gate once.
- Require the configured positive out-of-sample and drawdown criteria.
- PASS creates a candidate pending human flip; it never flips production
  automatically.
- FAIL is recorded as Rejected and is not retuned under the same hypothesis.

### Data-Correctness Migration Gate

Use this lane only when the purpose is to replace a demonstrably approximate,
incorrect, or non-PIT source contract with a more authoritative representation
of the same economic datum. Positive alpha is not a pass criterion.

Entry requires a new, pre-registered migration ID and evidence that:

1. The old and new inputs represent the same economic concept. A new feature
   disguised as a data fix belongs in the Alpha Experiment Gate.
2. The new source is authoritative or contractually approved, and its license,
   URL, retrieval time, immutable raw artifact, and SHA-256 are recorded.
3. Schema, semantic bounds, issue identity, publication time, timezone, and PIT
   visibility rules are explicit and executable.
4. Historical replay is deterministic and uses only information available at
   each as-of date. A latest-value backfill is insufficient.
5. Canonical promotion has one writer, validation before atomic replacement,
   ledger binding, evidence-drift detection, and freeze-on-failure behavior.
6. If the migration is flag-gated, flag OFF is byte-identical for four
   historical dates, including payload/input hash and the six scored
   persistence artifacts.
7. Full-window, WF, CPCV, PBO, DSR, turnover, drawdown, action-flip, and factor
   attribution deltas are reported as impact and model-risk evidence. They may
   block an operationally dangerous migration, but lack of positive alpha alone
   does not.
8. A shadow/current-date canary, rollback procedure, runtime interpreter check,
   and source outage drill pass before any live flip.
9. A human explicitly approves the truth migration and the resulting metric
   restatement. Code, a passing test, or a data owner cannot self-authorize it.

The declaration is machine-enforced. Legacy `hermes-formal-gate-v1` manifests
are permanently interpreted as `alpha_experiment`. New work uses
`hermes-formal-gate-v2` and must set `governance_lane` to either
`alpha_experiment` or `data_correctness_migration` before the committed one-shot
run. A migration-lane formal run emits `MIGRATION_IMPACT_RECORDED / NO_FLIP`;
performance output alone cannot authorize the migration.

Allowed outcomes are:

- `MIGRATION_APPROVED`: correctness evidence is complete, operational risk is
  accepted, and a human has approved the baseline restatement.
- `MIGRATION_BLOCKED`: authority, PIT, deterministic replay, validation,
  persistence, or rollback evidence is incomplete or contradictory.
- `MIGRATION_DEFERRED`: the representation is preferable but credentials,
  licensing, coverage, or operations are not ready.

The term `Rejected` remains reserved for alpha hypotheses and for migrations
that are proved incorrect. A truthful migration is not labeled Rejected merely
because historical performance falls.

## Baseline And Deployment

An approved migration is deployed OFF first, then shadowed where possible, and
flipped only through the normal human config ceremony. The first live run must
verify source evidence, canonical hash, input hash, official receipt, and
dashboard health without changing unrelated runtime state.

After acceptance, rebuild the full baseline and formal-gate baseline exactly
once from the new production data contract. Mark the previous baseline as a
historical reference, publish all metric deterioration as prominently as any
improvement, and update `context.md`, `FLAG_REGISTRY.md`, and the runbook in the
same change.

Rollback may restore the previous reader/flag while preserving both immutable
raw histories. It must never delete or rewrite the evidence that motivated the
migration.

## Existing FRED Decision

This ADR does not retroactively authorize `fred-vintage-pit-v1`. That experiment
was correctly evaluated under its pre-registered Alpha Experiment Gate and
remains `Rejected / NO_FLIP`; it must not be retuned or rerun under the same ID.

A future exact FRED/ALFRED production migration would require a new migration
ID, a manifest explicitly declaring `data_correctness_migration`, the complete
evidence above, and a separate human decision. The existing exact event store
may remain research and audit evidence until then.

## Consequences

- Hermes will not preserve accidental look-ahead merely to protect headline
  backtest metrics.
- Data migrations carry a higher provenance and persistence burden than alpha
  experiments.
- Performance evidence remains mandatory and visible, but its interpretation
  depends on the declared lane.
- Reviewers can reject lane-shopping: a change cannot switch gates after seeing
  its result.
