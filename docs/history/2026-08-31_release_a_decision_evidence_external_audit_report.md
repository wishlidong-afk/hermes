# Release A Decision Evidence - Independent External Audit Report

Audit date: 2026-08-31

Repository: `/Users/liweishi/Documents/github/hermes`

Branch: `hermes-docs`

Baseline: `028817ac00a71a36cc24a362d20110059c7a3568`

Audit scope: the uncommitted working-tree implementation documented in
`docs/history/2026-08-31_release_a_decision_evidence_external_audit_handoff.md`.

## 1. Final disposition

| Decision | Result |
|---|---|
| P0 findings | None |
| P1 findings | None |
| P2 findings | None |
| P3 findings | None |
| Commit and push | **APPROVE** |
| Live deployment | **Not automatically approved by this report** |

All claimed evidence was independently reproduced. The reviewer answered all 15
audit questions successfully and found no blocking defect.

The separate live gate remains mandatory: after a standard R6 deployment, the
system must be observed through natural Saturday, Sunday, and Monday scheduled
runs. Manual daily, market refresh, or IBKR refresh must not be used to create
that evidence.

## 2. Scope confirmation

| Item | Independent result |
|---|---|
| Production files | 10, matching the handoff list, including new `decision_revision.py` |
| Test files | 9, matching the handoff list, including new `test_decision_revision.py` |
| Untracked scope | Three documentation files plus two evidence directories; all are documentation or generated evidence |
| Tracked diff | 17 files, `+589/-47` at audit time |
| Baseline | `028817ac00a71a36cc24a362d20110059c7a3568` |

No scope drift was found.

## 3. Independently reproduced evidence

| Check | Handoff claim | Independent result |
|---|---:|---:|
| Full test suite | 1417 passed | **1417 passed** in about 145 seconds |
| Nine changed test files | Not separately claimed | **179 passed** |
| Governance | 8/8 OK, `ibkr_readonly=true` | **8/8 OK**, invariant confirmed |
| CI mypy, four governed modules | PASS | **PASS** |
| mypy, two new core modules | PASS | **PASS** |
| Severe Ruff, whole project | PASS | **PASS** |
| Full Ruff, two new core modules | PASS | **PASS** |
| Compile | PASS | **PASS** |
| Runtime package compatibility | 32 packages compatible | **PASS** |
| `git diff --check` | PASS | **PASS** |
| Final equivalence SHA-256 | `73e09dc7...` | Exact byte match |
| Strict four-date equivalence | 4/4 equal | **4/4 equal**, zero strict differences |

Final equivalence artifact:

`building/reports/decision_revision/RELEASE_A_EQUIVALENCE_2026_08_31.json`

SHA-256:

`73e09dc7d15408c8faa0e817e88765c1bce30da360c45aad91c41cbab84d8b18`

The independent rerun used a frozen baseline worktree at `028817a`. The four
recorded input hashes matched the handoff table.

## 4. Core implementation review

### 4.1 Decision clock

**PASS**

- `resolve_decision_as_of("latest")` raises `DecisionClockUnavailable` when any
  required history is missing.
- The exception includes the missing-symbol list.
- The daily selector no longer falls back to `date.today()`.
- Web normalization no longer falls back to `2026-06-02`.
- Complete but unequal histories use the conservative minimum latest date.
- Explicit historical dates retain their existing behavior.
- `latest_common_history_date()` remains a non-throwing probe and returns `None`
  for an incomplete clock.

### 4.2 Composite decision identity

**PASS**

The reviewer verified the deterministic identity fields:

1. `as_of`;
2. `snapshot_hash`;
3. `soft_input_evidence_hash`;
4. `canonical_market_evidence_hash`;
5. `config_hash`;
6. `policy_hash`;
7. `scorer_release_hash`;
8. `market_admission_operation_id`;
9. `market_admission_completed_through`.

The resulting `decision_hash` uses stable, sorted JSON hashing. Tests demonstrate
that config or soft-data provenance changes alter `decision_hash` even when
`snapshot_hash` remains unchanged.

### 4.3 Same-as-of revision policy

**PASS**

- Revision budget is two.
- Saturday certification of Friday close produces r1 `PROVISIONAL`.
- Sunday finalization produces r2 with `BAR_FINALITY_ADVANCED` when evidence is
  unchanged.
- Changed evidence plus finalization produces
  `CANONICAL_EVIDENCE_CHANGED_AND_FINALIZED`.
- Monday identical certification preserves r2, its `decision_id`, supersession
  id, previous hash, and original revision reason.
- A third material change raises `DecisionRevisionConflict`.
- A `FINAL` decision cannot regress to non-final.
- A pre-Release-A official record is represented by a synthetic legacy decision
  id and is superseded without in-place editing.

### 4.4 Transaction and failure behavior

**PASS**

Certification occurs after `input_hash` is available and before the state
snapshot and audit write. It remains inside the existing score transaction and
pipeline lock.

Manifest, policy, release identity, prior-certification, and revision-budget
failures raise and roll back all seven business artifacts. No new unlocked writer
was added.

Only scheduled, non-shadow runs enter the official certification path.

### 4.5 Consumer binding

**PASS**

Dashboard selection ranks scheduled records by:

1. `as_of`;
2. `decision_revision`;
3. `run_ts`.

This keeps r2 current even when audit records are unordered. A manual preview
cannot outrank a scheduled decision.

The disclosure behavior was confirmed:

- r1 `PROVISIONAL`: amber banner;
- r2 or later: blue revision banner with reason and decision references;
- normal r1 `FINAL`: no extra banner.

System-health filenames prefer `decision_hash`, Markdown includes the hash, and
both Web attachment and morning acceptance require an exact decision match for a
certified payload.

IBKR overlays require an exact `base_decision_hash` for certified payloads. Tests
do not connect to IBKR. Legacy payloads retain input-hash fallback behavior.

### 4.6 Audit rotation

**PASS**

Rotation grouping changed from `(as_of, run_type)` to
`(as_of, run_type, scheduled revision)`. It preserves r1 and r2 while compacting
repeated records for the same revision. The append-only write path is unchanged,
and the gzip rotation archive remains lossless.

## 5. Fifteen audit questions

| # | Question | Independent answer |
|---:|---|---|
| 1 | Can missing gating history still produce implicit latest? | No. It raises `DecisionClockUnavailable`. |
| 2 | Can an empty data root fall back to wall clock or a fixed date? | No. Both former fallbacks were removed. |
| 3 | Can manual or shadow runs create official certification? | No. Certification requires scheduled and non-shadow. |
| 4 | Does decision identity react to config or soft provenance changes with unchanged snapshot hash? | Yes. |
| 5 | Can r2 overwrite or remove r1? | No. Audit chronology and rotation retain both revisions. |
| 6 | Can repeated r2 lose supersession id, previous hash, or reason? | No. Prior chain fields are preserved. |
| 7 | Can a third material revision pass? | No. It fails closed and rolls back. |
| 8 | Can certification failure leave partial business artifacts? | No. Transaction tests verify rollback. |
| 9 | Can unordered audit rows make r1 outrank r2? | No. Revision-aware ranking selects r2. |
| 10 | Can manual preview outrank official revision? | No. |
| 11 | Can equal input hash but unequal decision hash pass report binding or acceptance? | No. |
| 12 | Can an overlay with equal input hash but unequal decision identity attach? | No. |
| 13 | Are legacy records readable without becoming certified evidence for a new payload? | Yes. Legacy fallback is isolated from certified matching. |
| 14 | Did this batch modify config, scoring, routing, flags, IBKR policy, dependencies, or live data? | No. |
| 15 | Were tests, governance, static checks, dependencies, and strict equivalence independently reproducible? | Yes. |

## 6. Safety boundary

The external reviewer confirmed:

- zero diff in `config.json`, requirements files, `pyproject.toml`, and CI;
- no CSV, database, Parquet, environment, secret, token, key, or certificate file
  in the implementation diff;
- no new production order path;
- `ibkr_readonly=true` remains enforced;
- no daily run, market refresh, IBKR refresh, or live-state write was used;
- no backtest or formal alpha gate was run.

## 7. Residual risks

These are accepted design constraints, not audit findings.

1. **Narrow weekend finality rule.** Only Saturday certification of the immediately
   preceding Friday is provisional. The rule deliberately does not generalize to
   unusual exchange-holiday chronologies.
2. **Two-revision budget.** A decision-bearing config or release change during the
   same weekend may consume the remaining revision. A later material change then
   fails closed and requires investigation.
3. **64 MiB audit-tail lookup.** Prior same-date lookup reads the final 64 MiB. The
   code and current operating assumptions were verified, but actual future live
   volume remains an operational constraint.
4. **Release identity.** Live uses the hash recorded in `VERSION`; repository and
   test contexts use the source-tree fallback when VERSION is absent.
5. **Natural-run certification.** Unit, integration, static, and equivalence
   evidence cannot replace the first real Saturday/Sunday/Monday observation.

## 8. Release recommendation

### Commit and push

**APPROVED**

The implementation has no blocking audit finding and preserves historical scoring
and persistence behavior under the strict four-date comparator.

### R6 live deployment

**Not automatically approved by this report.**

Deployment requires a separate user decision and the normal R6 safety checks. It
must preserve live config, avoid the scheduled-run window, confirm no writer is
active, and must not create a manual official run as deployment proof.

After deployment, the release remains operationally provisional until natural
runs demonstrate:

1. Saturday r1 provisional;
2. Sunday r2 final superseding r1;
3. Monday identical certification retaining r2 and its chain;
4. dashboard selection and revision disclosure;
5. system-health and morning-acceptance decision-hash agreement.

No manual daily, market refresh, or IBKR refresh may be used to manufacture this
observation.
