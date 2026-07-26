# VIX3M Historical Revision Quarantine - External Audit Handoff

Date: 2026-07-26

Repository: `/Users/liweishi/Documents/github/hermes`

Branch: `hermes-docs`

Baseline commit: `8066d23d8c107e1c699c15b28b40ce9467e3fcdc`

## 1. Decision

Candidate implementation status: **READY FOR INDEPENDENT REVIEW**.

Release status: **HOLD**.

The implementation, focused tests, offline failure drill, four-date behavior
equivalence, full test suite, compile check, and governance check are green.
The release is intentionally held because the current live market-admission
evidence is only `1/3` consecutive OK observations. The live-seeded VIX3M
canary also cannot advance beyond `2026-07-22` yet because Yahoo's witness is
currently behind the already certified tail.

No commit, push, deployment, official daily rerun, live refresh, config change,
factor change, routing change, WebUI change, or order-path change was made by
this batch.

## 2. Root Cause Evidence

The currently deployed code treats any historical difference in a CBOE full
history file as fatal. CBOE revised three non-close cells for VIX3M on
`2013-10-30`:

| Field | Certified canonical | Current official file |
|---|---:|---:|
| open | 15.13 | 14.68 |
| high | 15.13 | 15.45 |
| low | 15.13 | 14.68 |
| close | 15.13 | 15.13 |

The revision does not alter the certified close, but the deployed continuity
validator blocks the whole source at the first `open` difference. The
2026-07-26 read-only morning acceptance therefore reports:

```text
cboe_vix3m: VALIDATION_ERROR
history continuity: changed existing row 2013-10-30 column open
```

Current source state observed by a read-only, live-seeded isolated canary:

| Evidence | Value |
|---|---|
| Live canonical rows/latest | 4,235 / 2026-07-22 |
| CBOE official rows/latest | 4,237 / 2026-07-24 |
| Yahoo witness latest | 2026-07-17 |
| Live canonical SHA256 | `f62ae4a444166225c0224f87e22d77e2644303f0b1f7f09ef209e43fd63ed778` |
| Revision fingerprint | `318e907fdcd50844f026a807cca4212a7eedce52b119a1a41f4c2089e665a82d` |

Because the secondary witness is behind the already certified `2026-07-22`
tail, the candidate correctly preserves that certified tail, trims the
unconfirmed official tail, records the historical OHLC revision, and returns
`OK / UNCHANGED`. It does not rewrite live or the temporary canonical.

## 3. Required Behavior

The candidate implements this contract for normal daily CBOE index refreshes:

1. Archive the complete fetched official file as immutable raw evidence.
2. Treat the existing canonical rows as certified and keep their values.
3. Record historical non-close differences as revision evidence.
4. Append only strictly newer dates that survive the existing Yahoo tail
   witness.
5. Block if the official file removes an existing date.
6. Block if it adds an unreviewed date inside the certified historical range.
7. Block if it changes an existing `close` or `adj_close`.
8. Block if the latest-row Yahoo witness is absent or mismatched.
9. Do not rewrite the canonical when there is no newer certified date.
10. Keep controlled initial rebaseline behavior explicit and unchanged.

Revision evidence contains:

- policy and schema version;
- `NONE`, `QUARANTINED`, or `BLOCKED` status;
- changed dates and changed cells with canonical/official values;
- newly appendable dates;
- a stable fingerprint that identifies the historical revision independently
  of the moving tail;
- a summary in the external-source ledger and the complete detail in the
  per-run validation artifact.

## 4. Changed Files

| File | Purpose |
|---|---|
| `src/hermes_escape_top/core/data/external_sources/cboe_indices.py` | Reconcile full official history against certified canonical rows, quarantine historical OHLC revisions, and append only witnessed new dates. |
| `src/hermes_escape_top/core/data/external_sources/runner.py` | Persist revision status/count/fingerprint in the ledger and complete evidence in `validation.json`. |
| `src/hermes_escape_top/tests/test_external_source_cboe_indices.py` | Cover the five required revision/witness cases and ledger evidence. |
| `ops/external_source_failure_drill.py` | Extend the isolated production-runner drill from 8 AAII/NAAIM cases to 13 total cases. |
| `src/hermes_escape_top/tests/test_external_source_failure_drill.py` | Assert all five CBOE scenarios preserve or advance canonical state exactly as specified. |
| `building/reports/data_quality/vix3m_revision_quarantine_equivalence_2026_07_26.json` | Four-date payload and seven-artifact persistence equivalence evidence. |

## 5. Test-First Evidence

Before production implementation, the new CBOE tests produced the expected
red result:

```text
3 failed, 21 passed
```

After implementation:

```text
test_external_source_cboe_indices.py: 25 passed
```

The five required cases are:

| Case | Expected result | Verified result |
|---|---|---|
| Historical OHLC revision plus new witnessed tail | Preserve old rows, append tail, `QUARANTINED` | PASS |
| Historical certified close revision | Freeze canonical, `VALIDATION_ERROR/BLOCKED` | PASS |
| Official file missing an old certified date | Freeze canonical, `VALIDATION_ERROR/BLOCKED` | PASS |
| Latest tail witness mismatch | Freeze canonical, `VALIDATION_ERROR` | PASS |
| Official history completely unchanged | No rewrite, `OK/UNCHANGED/NONE` | PASS |

A sixth regression reproduces the current live-shaped condition: a historical
OHLC revision is present, Yahoo has regressed behind the already certified
tail, and there is no appendable date. It verifies
`OK/UNCHANGED/QUARANTINED`, three recorded changed cells, and a byte-identical
canonical file.

## 6. Failure Drill

Command:

```bash
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  ops/external_source_failure_drill.py \
  --output /tmp/hermes_external_failure_drill_2026_07_26.json
```

Result:

```text
status=PASS
scenarios=13
passed=13
network_used=false
live_data_touched=false
```

The drill uses the production `ExternalSourceRunner` against isolated temporary
data roots. It covers the original eight AAII/NAAIM failure/recovery cases and
the five new CBOE revision cases.

## 7. Real-Network Canaries

Both canaries copied the live VIX3M canonical into a temporary directory and
used candidate source code with the managed production dependency runtime.
They did not write live data.

### 7.1 Positive functional canary

A controlled copy ending at `2026-07-16` was used so the currently available
Yahoo witness could certify one genuinely new session.

```text
source inputs: real CBOE + real Yahoo
before: 4,231 rows, latest 2026-07-16
after:  4,232 rows, latest 2026-07-17
status: OK
promotion_status: OK
advanced: true
revision_status: QUARANTINED
revision_count: 3
2013-10-30 certified OHLC: preserved
live SHA256: unchanged
```

This proves the real transport, parser, witness, quarantine, and append path can
complete a positive promotion.

### 7.2 Current-state canary

The unmodified live canonical copy ends at `2026-07-22`, while the current
Yahoo witness ends at `2026-07-17`.

```text
status: OK
promotion_status: UNCHANGED
advanced: false
before/after: 4,235 rows, latest 2026-07-22
revision_status: QUARANTINED
revision_count: 3
unconfirmed CBOE 2026-07-23/24 tail: not promoted
live SHA256: unchanged
```

This result is not a candidate defect and must not be relabeled as an
advancement. It shows the fail-closed witness policy remains intact.

## 8. Behavior and Persistence Equivalence

Baseline: clean source archive of `HEAD` (`8066d23`).

Candidate: current working tree.

Seed: separate clones of the same read-only live `history` and `soft_history`.

Result: `all_equal=true`.

| as_of | input_hash | Payload | Seven artifacts |
|---|---|---|---|
| 2022-06-30 | `cec545d25b63688c07d2536214c0be4daef1c8b5547766dd83b3c4e1c7e98428` | equal | equal |
| 2024-06-28 | `68f631b24b6b9c3cd15196fed0b54c787ea0b061ebcceccb0749f3c52a5e620f` | equal | equal |
| 2026-05-29 | `0f910bfaa76b27a558a1a23820578ba0b695c5f82f841900635aff790c94e9a3` | equal | equal |
| 2026-07-10 | `18ffe225053fc71844fcdd06408478aabe25d9da279c19805b854aceb0c5ef9c` | equal | equal |

The comparator is strict on payload/status/input hash and seven persisted
business artifacts. It normalizes only documented volatile timestamps,
temporary paths, and the recoverable transaction envelope.

## 9. Final Verification

| Check | Result |
|---|---|
| Focused external-source/governance regressions | `109 passed` |
| Full suite | `1192 passed in 124.02s` |
| Governance | `7/7 OK`, no errors |
| Python compile | `python -m compileall -q src scripts ops` PASS |
| Whitespace | `git diff --check` PASS |
| Config diff | none |
| Scoring/routing/WebUI diff | none |
| Live data mutation | none |

## 10. Current Release Gates

| Gate | Current state | Decision |
|---|---|---|
| Independent external audit | Pending | HOLD |
| Real-network positive VIX3M promotion | PASS on controlled lagged seed | PASS |
| Current live-seeded VIX3M advancement | Yahoo witness behind certified tail | OBSERVE; do not weaken witness |
| Market admission | `1/3` consecutive OK; five-day target still observing | HOLD |
| Local full suite/governance | Green | PASS |
| Remote CI | Not run for uncommitted work | PENDING |
| No daily/refresh writer | Must be checked immediately before deployment | PENDING |

The 2026-07-26 read-only morning acceptance is `FAIL` on the deployed release,
not on the candidate. Its strategy-health failure is the VIX3M revision that
this candidate addresses. It also reports the old live release is missing the
approved-live-config policy artifact. Scheduled receipt, scheduled audit,
six-artifact transaction, and watchdog are PASS.

## 11. Independent Review Checklist

The reviewer should answer each question with file/line evidence and an actual
test or artifact where applicable:

1. Is the complete CBOE official payload still archived before parsing and
   promotion decisions?
2. Can any historical official OHLC revision overwrite a certified canonical
   value?
3. Does any existing close or adjusted-close change remain fail closed?
4. Does deletion of an old date or insertion inside the certified range remain
   fail closed?
5. Is the existing Yahoo latest-tail witness unchanged in strictness and still
   required before any new date is appended?
6. Does a same-date run avoid rewriting the canonical while still recording
   raw, normalized, validation, and ledger evidence?
7. Are revision details complete in `validation.json` and summaries durable in
   `external_source_runs.jsonl`?
8. Is the revision fingerprint stable as new tails advance but sensitive to a
   changed revision set or blocked reason?
9. Does controlled initial rebaseline retain its explicit behavior?
10. Does the 13-scenario drill use only isolated temporary data and report
    `network_used=false` and `live_data_touched=false`?
11. Does the four-date report independently prove zero score/persistence
    behavior change on already certified data?
12. Are `config/config.json`, scoring, routing, WebUI, IBKR policy, and order
    paths untouched?
13. Is the release still held until market admission reaches at least `3/3`,
    CI/governance are green, and no writer is active?
14. Does any report incorrectly call the current live-seeded `UNCHANGED`
    canary an advancement? The correct answer must be no.

## 12. Recommended External Audit Commands

```bash
cd /Users/liweishi/Documents/github/hermes

git status -sb
git diff --check
git diff -- config/config.json src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/core/scoring src/hermes_escape_top/core/routing \
  src/hermes_escape_top/web

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_external_source_cboe_indices.py \
  src/hermes_escape_top/tests/test_external_source_failure_drill.py \
  src/hermes_escape_top/tests/test_external_source_runner.py \
  src/hermes_escape_top/tests/test_external_source_profiles.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_governance_consistency.py -q

PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  ops/external_source_failure_drill.py \
  --output /tmp/hermes_external_failure_drill_external_audit.json

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q src scripts ops
```

Any real-network canary must copy the live canonical into an isolated temporary
root first. It must never point candidate refresh code at live shared data.

## 13. Post-Audit Release Sequence

After an independent PASS, do not deploy immediately unless all release gates
are satisfied:

1. Observe daily market admission until it reaches at least `3/3` consecutive
   OK.
2. Re-run the live-seeded isolated VIX3M canary. If Yahoo still trails the
   certified tail, record `UNCHANGED`; do not relax the witness.
3. Commit and push the reviewed candidate, then require remote CI and governance
   green.
4. Verify no daily, refresh, external-source, or score writer is active.
5. Run one R6 deployment while preserving live config.
6. Verify VERSION, `/livez`, `/readyz`, official receipt, scheduled audit,
   six-artifact transaction, default dashboard, and morning acceptance.
7. Do not run an official daily as part of deployment verification.
8. Observe five trading days without manual repeat refreshes: 06:45 external
   precheck, 07:05 failed-source retry, 07:10 daily, 09:00 watchdog, and 09:06
   acceptance.

Dollar may remain a documented WARN and is not a code-deployment blocker.
