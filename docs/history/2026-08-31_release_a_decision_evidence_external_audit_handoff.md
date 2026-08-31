# Release A Decision Evidence - External Audit Handoff

Date: 2026-08-31 (Asia/Shanghai)

Repository: `/Users/liweishi/Documents/github/hermes`

Branch: `hermes-docs`

Baseline commit: `028817ac00a71a36cc24a362d20110059c7a3568`

Scope: current uncommitted working tree. This batch has not been committed,
pushed, deployed, or run against live data.

## 1. Requested audit disposition

The implementation claims to close Release A from
`docs/history/2026-08-30_strict_ten_pass_20_dimension_review.md`:

1. implicit `latest` selection fails closed when any required market history is
   absent;
2. a scheduled decision has a stable composite identity in addition to the
   legacy snapshot-only `input_hash`;
3. a Friday-close weekend decision can move from provisional r1 to final r2
   without silently overwriting r1;
4. repeated r2 certification preserves the r1 -> r2 supersession chain;
5. the dashboard, health report, morning acceptance, and IBKR overlay bind to
   `decision_hash` for certified payloads;
6. explicit historical/manual scoring remains behaviorally unchanged.

Requested independent decision:

- `APPROVE COMMIT/PUSH`, or
- `REJECT` with P0/P1/P2/P3 findings and exact file/line evidence.

Do not infer live deployment approval from commit approval. A first natural
weekend observation remains a separate release gate.

## 2. Safety boundaries

This batch intentionally does not:

- change `config/config.json`;
- flip a feature flag;
- change a factor, module cap, status threshold, route, target weight, or order
  behavior;
- add an IBKR connection or order path;
- run daily, refresh market/external data, or write live state;
- run a backtest or formal alpha gate;
- alter the `ibkr.readonly=true` governance invariant.

Manual previews and shadow runs do not receive official decision certification.
Only `run_type=scheduled` and `shadow=false` enter the revision contract.

## 3. Decision clock contract

Required symbols are still the configured trade symbols plus `QQQ` and `SPY`.

1. `latest_common_history_date()` remains a non-throwing availability probe.
2. It returns a date only when every required history exists and is nonempty.
3. `resolve_decision_as_of("latest", ...)` raises
   `DecisionClockUnavailable` when any required history is missing.
4. The daily selector and Web refresh normalizer delegate to the same resolver.
5. There is no wall-clock fallback and no hard-coded fallback date.
6. Explicit dates remain unchanged.
7. Complete but unequal histories resolve conservatively to their minimum latest
   date.

## 4. Composite decision identity

The old `input_hash` remains for compatibility. It still represents the
normalized snapshots and is exposed as `snapshot_hash` inside
`decision_evidence`.

`decision_hash` is SHA-256 over this deterministic identity:

| Field | Meaning |
|---|---|
| `as_of` | certified market date |
| `snapshot_hash` | legacy snapshot/input hash |
| `soft_input_evidence_hash` | full deterministic soft records, including source, reason, field provenance, values, latency, and quality metadata |
| `canonical_market_evidence_hash` | certified market manifest id |
| `config_hash` | effective full config content |
| `policy_hash` | SHA-256 of `approved_live_config.json` |
| `scorer_release_hash` | live `VERSION` release hash; source-tree hash only when no VERSION exists |
| `market_admission_operation_id` | market-admission operation identity |
| `market_admission_completed_through` | admitted evidence cutoff |

Changing a decision-bearing config value or soft-data provenance changes the
decision hash even when `snapshot_hash` is unchanged.

## 5. Same-as-of revision policy

Schema: `hermes-decision-certification-v1`

Revision budget: two material revisions per `as_of`.

Expected Friday/weekend chronology:

| Natural run | Result |
|---|---|
| Saturday, certifying Friday close | r1 `PROVISIONAL`, `INITIAL_CERTIFICATION` |
| Sunday, same evidence | r2 `FINAL`, `BAR_FINALITY_ADVANCED`, supersedes r1 |
| Sunday, changed certified evidence | r2 `FINAL`, `CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED`, supersedes r1 |
| Monday repeat with identical final identity | remains r2 with the same `decision_id`, original supersession id, previous hash, and revision reason |
| Any third material identity change | `DecisionRevisionConflict`, score transaction rolls back |

A pre-Release-A official record can be superseded once as a synthetic legacy
decision id. It is never edited in place.

The audit log remains append-only during normal writes. Rotation preserves one
record for each scheduled revision and only compacts repeats of the same
revision. Its timestamped gzip archive remains lossless.

## 6. Transaction and failure semantics

Certification happens inside the existing seven-artifact score transaction,
after `input_hash` exists and before the state snapshot and audit write.

If manifest, policy, release identity, prior certification, or revision budget is
invalid, certification raises. The transaction test verifies that all business
artifacts return to their pre-run bytes and no partial official record survives.

The legal scheduled path uses the same process-wide pipeline lease as the rest of
the score transaction. No new unlocked writer was added.

## 7. Consumer binding

### Official dashboard selection

For scheduled records, selection order is:

1. `as_of`;
2. `decision_revision`;
3. `run_ts` for repeats of the same revision.

This makes r2 current even if supplied audit records are not ordered. Manual
previews never outrank a scheduled record.

The dashboard shows:

- an amber provisional banner for r1 `PROVISIONAL`;
- a blue revised banner for r2 with reason, current decision id, and superseded
  decision id;
- no extra banner for an ordinary r1 `FINAL` decision.

### System-health evidence

Scheduled reports persist `decision_hash`, use it in immutable report filenames,
and render it in Markdown. The Web loader and morning acceptance require an exact
decision-hash match when the official payload is certified.

A certified payload cannot attach a legacy report that only matches
`input_hash`. Legacy payloads without `decision_evidence` retain the old
input-hash fallback.

### IBKR overlay

The lightweight position refresh writes `base_decision_hash`. A certified
official payload accepts the overlay only when that hash matches exactly. Equal
`as_of` and equal legacy `input_hash` are insufficient if revisions differ.

Legacy payloads without decision evidence retain the old input-hash check. This
change does not connect to IBKR during tests and does not make IBKR strategy
blocking.

## 8. Production files changed

| File | Purpose |
|---|---|
| `src/hermes_escape_top/core/data/decision_as_of.py` | complete implicit-clock contract and fail-closed exception |
| `src/hermes_escape_top/core/data/decision_revision.py` | deterministic decision identity, finality, revision allocation, supersession, and budget |
| `src/hermes_escape_top/core/data/audit.py` | retain distinct scheduled revisions during rotation |
| `src/hermes_escape_top/pipeline.py` | certify scheduled non-shadow payload inside the score transaction |
| `src/hermes_escape_top/scripts/run_daily_package.py` | shared strict clock and decision-bound system-health report |
| `src/hermes_escape_top/core/reporting/system_health.py` | decision-bound immutable filename and Markdown evidence |
| `src/hermes_escape_top/web/server.py` | r2-aware official selection and decision-bound health loading |
| `src/hermes_escape_top/web/render.py` | revision disclosure and decision-hash evidence copy |
| `src/hermes_escape_top/web/refresh.py` | strict Web clock and decision-bound IBKR overlay |
| `ops/morning_acceptance.py` | prefer and require matching decision-bound health evidence |

## 9. Test files changed or added

- `test_decision_as_of.py`
- `test_decision_revision.py`
- `test_pipeline_transaction.py`
- `test_audit_rotation.py`
- `test_dashboard_official_only.py`
- `test_dashboard_workbench.py`
- `test_refresh_as_of_gating.py`
- `test_run_receipt_writer.py`
- `test_morning_acceptance.py`

The new tests cover:

- one/all missing decision histories;
- unequal complete histories and explicit historical dates;
- provisional r1, final r2, changed-evidence r2, legacy supersession, identical
  repeat, and third-material-revision rejection;
- preservation of the supersession chain after repeat certification;
- config and soft-provenance sensitivity with identical snapshot hashes;
- full transaction rollback on certification failure;
- absence of certification on manual previews;
- audit rotation preserving r1 and r2;
- unordered dashboard records selecting r2;
- report and overlay rejection when only snapshot hash matches;
- legacy report/overlay compatibility;
- morning acceptance failure on decision-hash mismatch.

## 10. TDD evidence

Tests were added before their corresponding behavior.

Observed RED examples:

- missing required histories still selected a date;
- every history missing fell back to the wall clock;
- an r1 health report attached to an r2 payload when snapshot hash matched;
- an r1 IBKR overlay attached to r2 when snapshot hash matched;
- morning acceptance passed a decision-hash mismatch;
- repeated r2 certification erased its supersession id;
- changing soft provenance did not change decision identity.

Each failure was then made green with a scoped implementation change.

## 11. Verification evidence

### Full suite

```text
1417 passed in 149.26s
```

### Governance

```text
ok=true
baseline_metadata=OK
config_invariants=OK
context_snapshot=OK
current_facts_docs=OK
execution_open_quality=OK
factor_capacity=OK
flag_registry=OK
live_config_policy=OK
ibkr_readonly=true
```

### Static and dependency checks

```text
CI severe Ruff over src/scripts/ops: PASS
CI mypy command over its four governed modules: PASS
full Ruff for decision_as_of.py and decision_revision.py: PASS
mypy for decision_as_of.py and decision_revision.py: PASS
compileall for every changed production module: PASS
uv pip check against the 32-package runtime: PASS
git diff --check: PASS
```

The runtime virtual environment intentionally has no `pip` module, so dependency
compatibility was checked with `uv pip check --python <runtime-python>` without
installing or upgrading anything.

### Strict four-date persistence equivalence

Comparator: `scripts/compare_pipeline_persistence.py`

Contract: `strict`

Baseline: clean source tree at `028817a`

Candidate: current working tree

Evidence:

`building/reports/decision_revision/RELEASE_A_EQUIVALENCE_2026_08_31.json`

SHA-256:

`73e09dc7d15408c8faa0e817e88765c1bce30da360c45aad91c41cbab84d8b18`

| Date | Equal | Differences | Strict differences | Input hash |
|---|---:|---:|---:|---|
| 2022-06-30 | yes | 0 | 0 | `e3963e7e55e74cf0fc96e5e762e5ba9e9324ad72dae372ef60a5fe31011a44bf` |
| 2024-06-28 | yes | 0 | 0 | `e46bec705d06acf81be6e77767c1bb0be555b7586d31354f87481dbffe519515` |
| 2026-05-29 | yes | 0 | 0 | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` |
| 2026-07-10 | yes | 0 | 0 | `fd73b0345b89915f4e1f7e6a43cc072b8ec9ffcc474e0d589d13420464468185` |

For every date, the normalized payload and all seven business artifacts are
strictly equal: audit JSONL, signal journal JSONL, four SQLite stores, and the
dated soft-adapter snapshot.

## 12. Independent audit questions

The reviewer should answer each question from source and reproduced evidence.

1. Can any missing gating history still yield an implicit latest date?
2. Can an all-missing data root still fall back to the wall clock or a fixed
   historical date?
3. Can a manual or shadow run create official certification?
4. Does `decision_hash` change when config or soft provenance changes but
   snapshot hash does not?
5. Can r2 overwrite or remove r1 from the main audit chronology?
6. Can a repeated r2 erase its supersession id, previous hash, or original
   revision reason?
7. Can a third material same-date change pass instead of rolling back?
8. Does a certification exception leave any of the seven business artifacts
   changed?
9. Can unordered audit records make r1 outrank r2?
10. Can a manual preview outrank an official revision?
11. Can a health report with equal `input_hash` but different `decision_hash`
    attach or pass morning acceptance?
12. Can an IBKR overlay with equal `input_hash` but different decision identity
    attach?
13. Are legacy records without decision evidence still readable without being
    treated as certified evidence for a new payload?
14. Did this batch change config, scoring, routing, feature flags, IBKR policy,
    dependencies, or live data?
15. Can all tests, governance checks, static checks, dependency checks, and the
    strict equivalence artifact be independently reproduced?

## 13. Residual risks and release gate

1. Weekend finality is deliberately narrow: a Friday decision first certified on
   Saturday is provisional. Unusual exchange holidays outside that chronology
   remain final according to the current rule and should be reviewed before
   generalizing the policy.
2. The revision budget is intentionally two. A deployment or decision-bearing
   config change during the same weekend can consume the remaining revision and
   then fail closed on another material change. This is safer than silently
   creating r3, but requires an operator investigation.
3. The prior same-date lookup reads the final 64 MiB of the audit log. Current
   operating volume keeps the weekend chain inside that tail; audit rotation also
   bounds the main file. An independent reviewer should confirm this assumption.
4. Live `scorer_release_hash` uses the release hash recorded in `VERSION`. The
   source-tree fallback is used only in repo/test contexts.
5. Deployment should not manufacture an official run. After an externally
   approved commit and standard R6 deployment, observe natural Saturday, Sunday,
   and Monday runs before declaring the revision policy operationally certified.

Recommended deployment observation:

- Saturday: one scheduled r1 provisional;
- Sunday: one scheduled r2 final, superseding Saturday;
- Monday: identical identity remains r2 and preserves the chain;
- dashboard selects r2 and shows the revision banner;
- health report and morning acceptance match the selected decision hash;
- no manual daily, market refresh, or IBKR refresh is used to manufacture proof.
