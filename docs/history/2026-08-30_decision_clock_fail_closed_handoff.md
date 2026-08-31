# Decision Clock Fail-Closed Remediation Handoff

> Historical sub-batch note: this document records the decision-clock slice
> before the rest of Release A was implemented. The statement below that the
> same-`as_of` revision work remained open is superseded by
> `docs/history/2026-08-31_release_a_decision_evidence_external_audit_handoff.md`.
> Keep this file only as the TDD/equivalence record for the clock slice.

Date: 2026-08-30 (Asia/Shanghai)

Repository: `/Users/liweishi/Documents/github/hermes`

Baseline commit: `028817ac00a71a36cc24a362d20110059c7a3568`

Scope: working tree changes after the strict ten-pass review. No commit, push,
deployment, live refresh, daily run, IBKR connection, config change, feature-flag
change, backtest, or formal gate was performed.

## 1. Disposition

This batch closes only P2-2 from
`docs/history/2026-08-30_strict_ten_pass_20_dimension_review.md`:

> An implicit `latest` decision date could previously ignore a missing gating
> history, and could fall back to the wall-clock date when every gating history
> was absent.

The remediation is **complete in the working tree and independently testable**.
The larger P1 same-`as_of` revision/supersession contract remains open and is not
claimed as fixed by this batch.

## 2. Behavioral contract

The required decision symbols remain the configured trade symbols plus `QQQ` and
`SPY`.

1. `latest_common_history_date(...)` is a non-throwing availability probe. It
   returns a common date only when every required history is present and nonempty;
   otherwise it returns `None`.
2. `resolve_decision_as_of("latest", ...)` is the scoring boundary. It raises
   `DecisionClockUnavailable` when any required history is absent.
3. The exception exposes a sorted `missing_symbols` tuple and names the missing
   histories in its message.
4. The daily automatic selector delegates to the same strict resolver. It no
   longer falls back to `date.today()`.
5. The Web refresh normalizer delegates to the same strict resolver. It no longer
   falls back to the hard-coded historical date `2026-06-02`.
6. Explicit historical dates such as `2020-03-12` remain independent of current
   history availability and are not rewritten.
7. A complete but lagging required symbol remains conservative: the common date is
   the minimum latest date across all required symbols.

This split preserves the recovery path: Web code may probe and discover that the
current cache is incomplete, perform its normal backfill, and only then encounter
the strict decision boundary if the repair did not restore every required history.

## 3. Changed files

### Production

- `src/hermes_escape_top/core/data/decision_as_of.py`
  - adds `DecisionClockUnavailable`;
  - centralizes complete-clock state calculation;
  - removes the wall-clock fallback from implicit `latest` resolution.
- `src/hermes_escape_top/scripts/run_daily_package.py`
  - routes `_latest_available_as_of()` through the strict shared resolver.
- `src/hermes_escape_top/web/refresh.py`
  - routes non-explicit Web date normalization through the strict shared resolver;
  - removes the hard-coded fallback date.

### Tests

- `src/hermes_escape_top/tests/test_decision_as_of.py`
  - one missing required history;
  - every required history missing;
  - complete histories with one required symbol lagging;
  - explicit historical date unchanged;
  - daily selector fail-closed;
  - Web normalizer fail-closed;
  - existing auxiliary-index and daily/Web agreement coverage retained.

## 4. TDD evidence

The tests were written before the behavior change.

Observed RED state:

- one missing `SOXL` returned `2026-07-14` instead of unavailable;
- all required histories missing returned the wall-clock date instead of raising;
- daily selection did not raise;
- Web normalization did not raise.

Observed GREEN state:

```text
8 passed in 0.22s
```

Adjacent recovery, daily, receipt, and Web regression suite:

```text
52 passed in 8.20s
```

Full suite:

```text
1397 passed in 118.82s
```

## 5. Governance and static checks

Governance consistency:

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
```

Additional checks:

```text
git diff --check: PASS
compileall for the three changed production modules: PASS
Ruff E9,F63,F7,F82 for all changed Python files: PASS
```

`config/config.json` was not changed. Governance continued to report
`ibkr_readonly=true`.

## 6. Four-date score and persistence equivalence

Comparator:

`scripts/compare_pipeline_persistence.py`

Contract: `strict`

Baseline source: clean archive of commit `028817a`

Candidate source: current working tree

Seed: `src/hermes_escape_top/data`, cloned independently for each source/date

Evidence report:

`building/reports/decision_clock/DECISION_CLOCK_FAIL_CLOSED_EQUIVALENCE_2026_08_30.json`

Report SHA-256:

`3e11501dd4f03eefcd8347046bc42c3050112b37808f8e966369785441a8d7e5`

| Date | Equal | Candidate input hash | Statuses |
|---|---|---|---|
| 2022-06-30 | yes | `e3963e7e55e74cf0fc96e5e762e5ba9e9324ad72dae372ef60a5fe31011a44bf` | FNGU EXIT, MSTR EXIT, SOXL EXIT |
| 2024-06-28 | yes | `e46bec705d06acf81be6e77767c1bb0be555b7586d31354f87481dbffe519515` | FNGU REDUCE, MSTR REDUCE, SOXL REDUCE |
| 2026-05-29 | yes | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` | FNGU REDUCE, MSTR EXIT, SOXL REDUCE |
| 2026-07-10 | yes | `fd73b0345b89915f4e1f7e6a43cc072b8ec9ffcc474e0d589d13420464468185` | FNGU REDUCE, MSTR EXIT, SOXL DEFENSIVE_EXIT |

For every date:

- `differences=[]`;
- `strict_differences=[]`;
- normalized payloads are equal;
- all seven business artifacts are equal:
  `audit_log.jsonl`, `flow_reference.sqlite`, `hermes_state.sqlite`,
  `mirror_reference.sqlite`, `reentry_state.sqlite`, `signal_journal.jsonl`, and
  the dated soft-adapter snapshot.

## 7. External review checklist

An independent reviewer should answer these questions directly from code and
re-run evidence:

1. Can one missing gating history still produce an implicit latest date?
2. Can all missing histories still produce the wall-clock date?
3. Does the daily selector use the strict resolver rather than its own fallback?
4. Does Web normalization retain any hard-coded fallback date?
5. Can the non-throwing pre-refresh probe still permit a repair attempt?
6. Does an explicit historical date remain unchanged without current histories?
7. Does a complete lagging required symbol hold the common date back?
8. Did any config, feature flag, routing threshold, scoring factor, IBKR policy, or
   live data change?
9. Can the focused, adjacent, full-suite, governance, static, and strict four-date
   results be reproduced?
10. Is the open same-`as_of` revision/supersession P1 still represented honestly as
    unresolved?

## 8. Residual risks and next step

1. `_last_bar_dates()` remains a tolerant diagnostic/self-heal helper. It may return
   a partial map, but it no longer has authority to select the daily scoring date.
2. A completely absent symbol is repaired by the normal batch refresh, not by the
   laggard-only self-heal loop. If batch refresh cannot restore it, scoring now stops
   as intended.
3. Explicit historical scoring remains allowed by design and depends on the normal
   snapshot/data-quality guards for that requested date.
4. This batch does not add decision revision identity, canonical-row revision
   archives, finality, or supersession. Those are the next Release A work item and
   require one explicit policy choice before implementation.

Recommended next policy: keep the first weekend decision as `PROVISIONAL`, allow at
most one explicit same-`as_of` recertification when certified vendor evidence
changes, preserve both decisions, and mark exactly one current with
`supersedes_decision_id` plus a machine-readable revision reason. Do not silently
overwrite or silently choose a newer payload.
