# Hermes Market Admission Independent Audit Prompt

Copy the prompt below into a fresh agent session. The audit must be independent and read-only.

---

You are an independent reviewer for the Hermes escape-top system. Audit the current uncommitted
working tree in `/Users/liweishi/Documents/github/hermes` on branch `hermes-docs`.

## Audit Base And Scope

- Base commit: `cb9c99a fix: quarantine CBOE historical revisions`.
- This is a working-tree audit, not a commit-range audit. Inspect both `git diff HEAD` and
  `git ls-files --others --exclude-standard`; untracked evidence files are part of scope.
- Treat this prompt file as review instructions, not as implementation evidence.
- Do not trust handoff documents or generated reports as independent proof. Recompute their
  important claims from code and source artifacts.

Implementation and tests:

- `src/hermes_escape_top/core/data/market_witness.py`
- `src/hermes_escape_top/core/data/market_admission.py`
- `src/hermes_escape_top/tests/test_market_witness.py`
- `src/hermes_escape_top/tests/test_market_admission.py`

Thirty-session reliability study:

- `scripts/analyze_market_admission_history.py`
- `src/hermes_escape_top/tests/test_market_admission_history_analysis.py`
- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_07_28.json`
- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_07_28.md`
- `docs/history/2026-07-28_market_admission_reliability_review.md`

Raw mismatch evidence:

- `building/reports/data_quality/MARKET_ADMISSION_RAW_EVIDENCE_EQUIVALENCE_2026_07_28.json`
- `docs/history/2026-07-28_market_admission_raw_mismatch_evidence.md`

## Safety Rules

1. Read-only audit. Do not edit, format, commit, push, deploy, or clean the worktree.
2. Do not run official daily, manual rerun, refresh endpoints, backfill, external-source fetches,
   market refreshes, or IBKR code.
3. Do not modify live/shared data. Live may be read only where explicitly needed for artifact
   verification; put all regenerated output under `/tmp`.
4. Do not change config or flags. Do not authorize a source-role, threshold, or policy change.
5. Do not expose secrets in the report. Report only whether credential-shaped values survive.
6. Findings lead the report, ordered P0/P1/P2/P3 with exact file and line references.

## Required Audit Area A: Reliability Study

Verify from code and archived artifacts, not from the generated Markdown:

1. The script is genuinely read-only: no network calls, canonical promotion, scoring, live write,
   IBKR access, threshold change, or config mutation.
2. Dated artifacts are selected correctly and `market_admission_latest.json` is excluded.
3. Independent sessions are keyed by `completed_through`; duplicate artifacts do not inflate the
   session denominator.
4. Explain and validate the choice to use the first artifact for each completed session when
   calculating blocked-session rate. Identify any bias this creates.
5. Unique blocking events are deduplicated by `(symbol, session date)` and nonblocking/deferred
   rows are excluded.
6. A recovery is counted only after later evidence admits the same `(symbol, session date)`.
   `runs_to_recovery` must count artifact runs, not merely re-observations of that symbol/date.
7. Events with no later artifact remain pending and are not included in the matured recovery-rate
   denominator.
8. The source manifest covers every input artifact with SHA256. Note whether including absolute
   paths makes the manifest machine-specific and whether that affects the stated claim.
9. Recompute the expected current results:
   - `11/30` independent completed sessions;
   - 15 dated artifacts;
   - 5 blocked sessions, `45.45%`;
   - 7 unique blocking events: 6 volume, 1 price;
   - 5 matured, 5 recovered, all on the next observed run;
   - 2 pending;
   - 7/7 blocking events with close difference at or below `0.5%`;
   - policy remains `HOLD_FAIL_CLOSED_POLICY`.
10. Check for look-ahead, date-window leakage, stale report claims, denominator errors, and weak
    synthetic coverage. Do not recommend weakening fail-closed policy from an 11-session sample.

## Required Audit Area B: Raw Mismatch Evidence

Verify the implementation directly:

1. Existing admission outcomes, reason strings, warning bands, thresholds, and canonical promotion
   behavior are unchanged for identical inputs.
2. `MATCH` rows retain their prior shape and do not get `raw_comparison`.
3. Every non-match path (`NO_WITNESS`, `DATE_MISMATCH`, `PRICE_MISMATCH`, and
   `VOLUME_MISMATCH`) attaches sufficient normalized evidence. Identify missing test coverage even
   if the implementation appears correct.
4. Candidate fields are limited to `date/open/high/low/close/volume`; Alpaca fields are limited to
   `date/timestamp/open/high/low/close/volume`.
5. Independently recompute close, maximum OHLC, and volume differences from the stored bars and
   compare them with the decision row.
6. Recompute candidate/witness normalized SHA256 values using deterministic sorted compact JSON.
7. Verify source metadata accurately states Yahoo candidate semantics and Alpaca
   `1Day/feed=sip/adjustment=raw`, requested range, fetch time, completed-session cutoff, source
   URL, symbol/row counts, and normalized-bars hash.
8. Distinguish a hash of normalized bars from a raw HTTP response/blob hash. Flag any document or
   field name that overclaims stronger provenance than the code retains.
9. Inject credential-shaped keys and nested metadata at both bar and session-provenance boundaries.
   Confirm API key, secret, authorization header, arbitrary response fields, and nested caller
   metadata cannot survive final JSON serialization.
10. Review the legacy `local_sha256`/`witness_sha256` behavior separately from the new normalized
    hashes. Flag any material credential-derived-hash or semantic ambiguity risk.
11. Confirm the additive `equity_witness` field does not break v1/v2 validation, old artifact reads,
    or BTC/Coinbase partial-failure behavior.
12. Confirm no config, feature flag, score calculation, routing, action intent, input hash, official
    receipt, or production persistence path changed.

## Required Audit Area C: Equivalence And Repository Hygiene

1. Independently inspect the equivalence comparator before trusting its result. Confirm it compares
   score payloads plus the four SQLite files, two JSONL ledgers, and dated soft-adapter snapshot,
   with only documented volatile normalization.
2. Verify the committed report has `all_equal=true` for:
   - `2022-06-30`
   - `2024-06-28`
   - `2026-05-29`
   - `2026-07-10`
3. Confirm baseline and candidate `input_hash`, payload SHA256, statuses, and every artifact SHA are
   equal on each date.
4. Confirm the report SHA256 is
   `ced57d929fab5159a59e166fa0df1f0e4db51bf959dd6589a4936e9fd7a68588`.
5. Confirm `config/config.json`, `pipeline.py`, feature flags, governance baseline, live config,
   and production data are absent from the diff.
6. Scan tracked and untracked files for accidental secrets, credentials, live CSV/SQLite data,
   temporary paths presented as portable evidence, and generated artifact bloat.
7. Confirm the worktree has not been committed, pushed, or deployed and live VERSION remains
   `cb9c99a`.

## Commands To Run

Use the repository virtualenv and isolated test fixtures:

```bash
cd /Users/liweishi/Documents/github/hermes
git status --short --branch
git diff --check
git diff HEAD -- src/hermes_escape_top/core/data/market_witness.py \
  src/hermes_escape_top/core/data/market_admission.py \
  src/hermes_escape_top/tests/test_market_witness.py \
  src/hermes_escape_top/tests/test_market_admission.py
git ls-files --others --exclude-standard

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_market_witness.py \
  src/hermes_escape_top/tests/test_market_admission.py \
  src/hermes_escape_top/tests/test_market_admission_history_analysis.py \
  src/hermes_escape_top/tests/test_backfill_guard.py -q

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

/Users/liweishi/.cache/uv/archive-v0/HtqEdntYf1Uma1Jn4YJWM/bin/ruff check \
  src/hermes_escape_top/core/data/market_witness.py \
  src/hermes_escape_top/core/data/market_admission.py \
  src/hermes_escape_top/tests/test_market_witness.py \
  src/hermes_escape_top/tests/test_market_admission.py \
  scripts/analyze_market_admission_history.py \
  src/hermes_escape_top/tests/test_market_admission_history_analysis.py

/Users/liweishi/.hermes-v3/.venv/bin/python -m compileall -q src scripts ops

shasum -a 256 \
  building/reports/data_quality/MARKET_ADMISSION_RAW_EVIDENCE_EQUIVALENCE_2026_07_28.json
jq '.all_equal, .dates' \
  building/reports/data_quality/MARKET_ADMISSION_RAW_EVIDENCE_EQUIVALENCE_2026_07_28.json

/Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/analyze_market_admission_history.py \
  --archive /Users/liweishi/.hermes/skills/investment/escape-top/current/hermes_escape_top/data/archive \
  --target-sessions 30 > /tmp/hermes-market-admission-study-audit.json
```

The last command is read-only with respect to live; it writes only `/tmp`. Normalize or ignore
`generated_at` when comparing regenerated study output.

You may independently rerun `scripts/compare_pipeline_persistence.py`, but extract the baseline
from `git archive HEAD` into a new `/tmp` directory and use the live data root strictly as a
read-only seed. Do not write comparator output into live or replace the supplied report.

Expected local test baseline for this worktree:

- focused suite: `92 passed`;
- full suite: `1204 passed`;
- governance: `7/7 OK`;
- four-date seven-artifact equivalence: `all_equal=true`.

## Required Report Format

1. Findings first, ordered P0/P1/P2/P3, each with file and line reference, impact, reproduction,
   and smallest safe fix.
2. Explicit verdict for each required audit area: PASS / PASS WITH FINDINGS / FAIL.
3. A table answering every numbered question in Areas A, B, and C.
4. Commands actually run with exit codes and observed counts. Separate inspected claims from
   independently reproduced claims.
5. Residual risks and missing tests, even if nonblocking.
6. Final release recommendation must be exactly one of:
   - `BLOCK`
   - `APPROVE COMMIT/PUSH ONLY; WAIT FOR NATURAL RUN`
   - `APPROVE COMMIT/PUSH AND LATER DEPLOY AFTER NATURAL-RUN GATE`

Do not approve an immediate deployment. The required next gate is the first natural 07:10
scheduled run under live `cb9c99a`, followed by read-only morning acceptance. Deployment must not
be used to create a second official daily run.

---
