# NAAIM Retirement and CFTC TFF Research Handoff

Date: 2026-08-12  
Baseline commit: `54081d8af439ef2b56559922aa85d2f872cf07ad`  
State: implementation complete, not committed, not pushed, not deployed

## 1. Objective

Hermes will not purchase the NAAIM subscriber workbook. This change makes that
choice explicit without inventing replacement values or weakening evidence
checks:

1. NAAIM public access is `RETIRED_PAYWALL` from 2026-08-01.
2. The last certified canonical history remains immutable.
3. Stale NAAIM continues through the existing max-age and missing-weight path.
4. Automatic access is probed only on Friday Shanghai time. A verified
   subscriber or restored public official channel may reactivate the source.
5. Canonical/ledger mismatch, missing certified history, and evidence drift
   remain fail-closed.
6. A distinct CFTC TFF Asset Manager ES/NQ candidate is added under
   `core/research/` only. It is not registered in production and has zero
   production weight.

## 2. Production Behavior

### NAAIM lifecycle

- `ExternalSourceProfile` now carries lifecycle policy, effective date, reason,
  and probe weekdays.
- The NAAIM profile retires public access on 2026-08-01 and probes on Friday.
- A verified automatic subscriber channel becomes `ACTIVE_SUBSCRIBER`.
- A fresh verified public official channel observed after retirement becomes
  `ACTIVE_PUBLIC`.
- Otherwise the status remains `RETIRED_PAYWALL`.

### Morning request schedule

- 06:45 skips retired NAAIM except on Friday or when a subscriber URL is
  configured.
- 07:05 retries a failed Friday probe, but skips NAAIM on other days.
- 07:10 reuses the same-day Friday result and does not issue a third request.
- Explicit controlled single-source import remains technically available, but
  the retired WebUI state no longer asks the operator to import or buy NAAIM.

### Health and acceptance semantics

- Matching frozen NAAIM evidence is informational and does not block strategy
  health, daily readiness, or morning acceptance.
- A same-day Friday probe failure degrades only the operations layer.
- An older failed probe is informational, preventing a permanent daily warning.
- `EVIDENCE_DRIFT` is evaluated before retirement handling and still blocks.
- WebUI labels the source `RETIRED_PAYWALL`, shows the Friday probe, and removes
  the NAAIM manual-import prompt.

## 3. Research-Only Candidate

`src/hermes_escape_top/core/research/cftc_tff_asset_manager.py` normalizes the
official CFTC TFF Futures Only dataset using exact contract market codes:

- ES: `13874A`
- NQ: `209742`

It requires an exact release-date map, rejects inferred PIT dates, requires
stable ES+NQ coverage, and aggregates Asset Manager/Institutional net position
over open interest. The candidate contract is:

- ID: `CFTC_TFF_ASSET_MANAGER_EQUITY_EXPOSURE`
- status: `OFFLINE_RESEARCH_ONLY`
- production source: none
- production weight: 0
- possible future budget: 2 points, displacing `A2_NAAIM`
- explicitly distinct from rejected `data_cot_nq`

No config key, feature flag, factor registration, runner source, or scoring path
was added. Further research requires an immutable raw archive plus exact CFTC
release evidence, then an event/correlation screen. It is not gate-ready.

## 4. Changed Areas

- Lifecycle and scheduling:
  `core/data/external_sources/profiles.py`, `scripts/refresh_external.py`
- Truthful reporting:
  `web/health.py`, `web/render.py`, `core/reporting/system_health.py`,
  `ops/morning_acceptance.py`, `ops/refresh_external_precheck.sh`
- Research only:
  `core/research/cftc_tff_asset_manager.py`
- Governance and operations:
  `context.md`, `docs/PRODUCTION_RUNBOOK.md`, `docs/FLAG_REGISTRY.md`,
  `ops/README.md`
- Tests cover lifecycle boundaries, weekday selection, Friday retry and daily
  reuse, evidence drift, health severity, acceptance, WebUI, and CFTC PIT rules.

## 5. Verification Evidence

### Full suite

```text
1264 passed in 114.03s
```

### Governance

`scripts/check_governance_consistency.py` returned `ok=true`, 7/7 checks OK:

- baseline metadata
- config invariants
- context snapshot
- execution-open quality
- factor capacity
- flag registry
- live config policy

The snapshot confirms `data_naaim=true`, `use_soft_data_max_age=true`,
`data_cot_nq=false`, and `ibkr_readonly=true`.

### Four-date scoring and persistence equivalence

Evidence:
`building/reports/data_quality/NAAIM_RETIREMENT_CFTC_TFF_EQUIVALENCE_2026_08_12.json`

Result: `all_equal=true` for 2022-06-30, 2024-06-28, 2026-05-29, and
2026-07-10. Each date has identical payload, input hash, symbol states, and all
seven score-transaction business artifacts. Differences are empty.

### Static checks

- `python -m compileall -q src scripts ops`: PASS
- shell syntax for precheck/deploy/daily/dashboard entry scripts: PASS
- Ruff severe rules `E9,F63,F7,F82` on changed Python files: PASS
- full Ruff on the new CFTC module and its test: PASS
- `git diff --check`: PASS

## 6. Safety Boundaries

- No `config/config.json` change.
- No scoring, routing, decision threshold, or module-cap change.
- No feature flip.
- No official daily run, market refresh, IBKR connection, live write, commit,
  push, or deployment was performed.
- NAAIM retirement does not certify stale data as fresh. It only distinguishes
  structural source retirement from an operational outage.
- CFTC research code cannot enter production through the current registry.

## 7. Residual Risks and Release Gate

1. The first natural Friday probe still needs observation. Expected behavior is
   one 06:45 attempt, at most one 07:05 retry after failure, and no 07:10 third
   request.
2. NAAIM will become missing for scoring after its configured SLO. This is the
   intended conservative behavior, not a data repair.
3. A future subscriber URL must prove automatic official evidence before the
   lifecycle can reactivate.
4. The CFTC candidate has no historical exact-release manifest yet and must not
   be gated or wired before that evidence exists.
5. Deployment should follow independent review, clean status, pushed HEAD, no
   active writer, and the normal R6 single deployment path while preserving live
   config.

## 8. Independent Review Checklist

1. Confirm retirement never bypasses `canonical_evidence_issue`.
2. Confirm non-Friday 06:45/07:05/07:10 paths do not request NAAIM.
3. Confirm Friday failure is operations-only and the strategy layer remains
   usable when frozen evidence still matches.
4. Confirm the dashboard does not offer a retired NAAIM refresh/import action.
5. Confirm morning acceptance passes retired matching evidence but rejects bad
   SHA, missing canonical, or migration/lifecycle inconsistency.
6. Confirm CFTC exact market codes and exact release dates are mandatory.
7. Confirm the CFTC module has no production profile, factory, factor, config,
   or flag registration.
8. Re-run full tests, governance, equivalence artifact inspection, config diff,
   scoring/routing diff, and secret/live-data checks before approving deploy.
