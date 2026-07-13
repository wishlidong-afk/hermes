# 2026-07-13 Data Quality Hardening Handoff

## 1. Scope And Safety Result

This batch hardens external data automation and evidence. It does not change
factor thresholds, hard valves, sizing, DEFCON routing, order behavior, or IBKR
read-only policy.

Safety boundaries:

- External soft data promotes only through `ExternalSourceRunner` after schema
  and semantic validation.
- Fetch, parse, validation, and witness failures preserve canonical bytes.
- Alpaca SIP OHLCV is a shadow witness only. It cannot promote history, enter
  score payloads, or change `input_hash`.
- Parked/disabled research feeds do not lower production decision coverage.
- No paid credentials, browser cookies, downloaded official files, or secrets
  are stored in git.
- This branch has not written or refreshed live data during verification.

## 2. Delivery Inventory

| Commit | Delivery |
|---|---|
| `e673483` | Config-backed source profile/SLO policy |
| `3f57b56` | Canonical SHA and source-ledger evidence binding |
| `f04fd9e` | Single writer plus 06:45 full / 07:05 selective retry / daily reuse |
| `4a31e73` | CBOE, CFTC COT, OCC and BTC micro adapters behind runner |
| `43ac7c8` | Decision-input coverage and four-dimension quality reporting |
| `29e261a` | Alpaca SIP OHLCV shadow witness |
| `05cd03d` | 30/90-day reliability and AAII/NAAIM migration states |
| `b018a9c` | FRED query-vintage evidence and stable source input hash |
| `42af440` | BTC validator separates historical proxy bounds from real exchange bounds |

## 3. Source Matrix

| Source | Automation | Canonical role | Remaining external dependency |
|---|---|---|---|
| Dollar / real rate / net liquidity | FRED API, Graph CSV fallback | Active soft inputs when flags are enabled | FRED availability; fallback lacks query realtime metadata |
| CBOE equity PCR | Official daily HTML | Active soft input when enabled | HTML schema and publication availability |
| CFTC NQ COT | Public API | Parked unless flag enabled | Weekly publication/API availability |
| OCC equity PCR | Official weekly report | Inactive replacement evidence | Report schema/availability |
| BTC funding/basis/DVOL | Deribit, OKX fallback | Active auxiliary input per config | Exchange API availability and provider field continuity |
| NAAIM exposure | Official XLSX/import | Weekly soft input | Official file/session/subscription; migration deadline 2026-08-01 |
| AAII sentiment | Official file/browser-assisted import | Weekly soft input | Imperva/member session; cannot guarantee unattended refresh |
| Yahoo/local OHLCV | Existing history transaction | Canonical market history | Yahoo availability/corporate-action semantics |
| Alpaca SIP OHLCV | Read-only shadow witness | No scoring role | Credentials, SIP entitlement and supported U.S. symbols |

AAII and NAAIM cannot honestly be described as guaranteed unattended sources.
The automation can discover, hash, validate and promote a newly downloaded
official file, but authentication/subscription renewal remains a human duty.
Unlicensed mirrors are comparison evidence only.

## 4. Evidence Semantics

Each successful external-source ledger record binds:

- stable source input hash;
- raw evidence path and retrieval metadata;
- canonical SHA-256 and latest normalized date;
- source URL and PIT rule;
- validation/promotion status.

`EVIDENCE_DRIFT` means current canonical bytes no longer match the latest
successful promotion. A failed fetch or a manually modified file cannot be
silently re-certified as OK.

FRED standard observations API `realtime_start/realtime_end` are query-vintage
metadata, not per-row first-release dates. Normalized rows continue to use the
conservative `observation_date + 1 day` convention. Building true historical
first-release data requires ALFRED vintages and a separate research gate.

Reliability is reduced to one result per `Asia/Shanghai` calendar day. A 06:45
failure followed by a 07:05 success counts as one successful day, not two
samples. Retrieval timestamps are retained in raw evidence but removed from the
stable content hash.

## 5. Quality Reporting

The dashboard and system-health report expose four independent dimensions:

1. market completeness;
2. provenance/real-data share;
3. timeliness;
4. active decision-input coverage.

Decision coverage is computed from actual scored
`confidence_missing_weight`, not from a parallel hand-maintained factor list.
IBKR holdings and SIP flow remain auxiliary evidence and do not reduce strategy
coverage.

## 6. Verification Commands

Run from the repository/worktree root. These commands must not point
`HERMES_DATA_DIR` at live.

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q

git diff --check

PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python \
  -m compileall -q src/hermes_escape_top
```

Four-date score and persistence equivalence is generated with
`scripts/compare_pipeline_persistence.py` against a detached pre-batch
worktree, using an isolated seed data root. The final report path is:

```text
building/reports/data_quality/final_data_quality_byte_identical_2026_07_13.json
```

The report must show `all_equal=true` for 2022-06-30, 2024-06-28,
2026-05-29 and 2026-06-04. The comparison covers payload/input hash and all six
business persistence artifacts; it normalizes only timestamps and temporary
paths.

Read-only environment evidence:

```bash
/usr/bin/python3 ops/morning_acceptance.py
```

This validates the currently deployed release, not the candidate branch. It
must not be presented as candidate-code proof. Candidate external-source status
may be inspected only against a cloned temporary `HERMES_DATA_DIR`; do not run
candidate refresh commands against live during review.

## 7. Verification Evidence

Candidate HEAD at final verification: `42af440` plus the documentation/report
commit that contains this handoff.

| Check | Result |
|---|---|
| Full pytest suite | `841 passed / 0 failed` in 93.05s |
| Focused external/health/WebUI regression | `196 passed / 0 failed` |
| Static/governance | compileall, `git diff --check`, bash syntax and all four governance checks PASS |
| Four-date behavior/persistence | `all_equal=true`; 2022-06-30, 2024-06-28, 2026-05-29, 2026-06-04 |
| Morning acceptance | PASS on deployed `feab9c5`; scheduled receipt/audit, six-artifact transaction, 8766 and 09:00 watchdog valid |
| Candidate external canary | isolated temp data root, `9/9 OK`, `ready=true`, no blocking sources |
| Alpaca witness canary | 31 supported symbols `MATCH`; 8 unsupported index/crypto symbols explicit `NO_WITNESS`; overall OK |

The first external canary intentionally exposed two real issues before this
final result:

- BTC validation applied real-exchange bounds to historical proxy rows. The
  deterministic regression failed before `42af440`, then passed; a second live
  endpoint canary promoted a temp canonical with `MATCH` evidence.
- AAII public HTTP remained Imperva-blocked, while the old live direct writer
  had advanced canonical beyond its ledger. The official browser download for
  issue 2026-07-09 was validated in a temporary runner and produced `MATCH`.
  Its verified copy is staged outside git at
  `~/.hermes/external_imports/sentiment_2026-07-09.xls` with mode `0600`. The
  candidate's automatic official-file fallback consumed it successfully after
  the expected public `FETCH_ERROR`.

No candidate canary wrote live. The witness cache path was resolved under its
temporary root, and no `market_witness*.json` appeared in live archive.

## 8. External Review Checklist

1. Trace every scheduled external writer. Confirm production soft-history
   promotion flows through `run_external_source_refresh` and no daily duplicate
   writer remains.
2. Inject fetch, parse and validation failures. Confirm target SHA-256 is
   unchanged and ledger records the true failure.
3. Modify a promoted canonical file. Confirm `source_status` reports
   `EVIDENCE_DRIFT` rather than OK.
4. Create same-day failed and successful ledger attempts. Confirm reliability
   has one sample and ends in success.
5. Reuse an already consumed AAII/NAAIM file. Confirm it is not returned as a
   pending official artifact.
6. Inspect FRED raw JSON. Confirm query realtime and retrieval metadata exist,
   normalized CSV remains `date + 1 day`, and a second identical fetch with a
   different retrieval time has the same source input hash.
7. Inject Alpaca mismatch/fetch error/unsupported index. Confirm only witness
   archive evidence changes and score payload/input hash does not.
8. With empty scores, confirm decision coverage is `UNKNOWN`, not fabricated
   100. With a missing weighted factor, confirm coverage falls by its actual
   confidence missing weight.
9. Confirm 06:45 is full, 07:05 retry-only, and 07:10 reuses complete same-day
   evidence instead of refetching all providers.
10. Search the diff and artifacts for tokens, API keys, downloaded member files,
    cookies and live paths. The result must be empty.

## 9. Deployment Gate And Residual Risks

Do not deploy unless all of the following are true:

- full suite passes;
- four-date equivalence is `all_equal=true`;
- focused source, scheduler, health and WebUI tests pass;
- read-only environment acceptance has no unexplained core failure;
- repo is clean, pushed, outside 07:00-07:20, no daily/refresh process is
  running, and live 8766 is HTTP 200;
- deployment uses the existing versioned release/symlink/rollback path and
  answers `N` to live config replacement unless config was separately reviewed.

The first post-deploy external precheck is also a migration step. It must run
under the normal pipeline lock and produce:

- AAII official-file fallback `OK`, latest `2026-07-09`, evidence `MATCH`;
- CBOE, BTC and other newly runner-owned sources with successful canonical SHA
  ledger rows;
- overall `ready=true` with no blocking sources. Publisher-lag warnings for
  still-valid Dollar/real-rate observations are allowed and must remain
  distinct from transport errors.

If this migration precheck fails, do not re-certify or edit canonical files by
hand. Keep the prior validated bytes, preserve the ledger error, and either
rollback code or correct the official artifact/provider path.

Residual risks that code cannot remove:

- AAII/NAAIM sessions, subscriptions and official publication timing require
  human ownership.
- Alpaca witness coverage excludes unsupported indices and depends on SIP
  entitlement; `NO_WITNESS` is evidence absence, not canonical failure.
- Yahoo remains canonical OHLCV until a separately approved provider-switch
  gate covers splits, dividends, adjustment semantics and historical parity.
- Provider HTML/API schemas can change. Validators preserve the last good data,
  but cannot guarantee a new issue will be available.
- The shadow witness is synchronous and bounded by provider timeout, so a slow
  Alpaca response can delay auxiliary completion even though it cannot alter
  scoring.
- Legacy standalone backfill CLIs remain diagnostic/manual tools. The scheduled
  production path is single-writer, while ledger drift detects any out-of-band
  canonical modification.
