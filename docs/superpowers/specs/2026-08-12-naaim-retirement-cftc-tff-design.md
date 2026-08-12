# NAAIM Retirement and CFTC TFF Research Design

**Date:** 2026-08-12
**Status:** Approved for implementation

## Problem

NAAIM stopped publishing its public workbook after moving current data behind a
paid subscription on 2026-08-01. Hermes correctly ages the last certified row
out of scoring, but still treats the unavailable public channel as a migration
failure every morning. That creates a permanent operational warning for a
condition that cannot recover without purchasing access.

The system needs to preserve two different truths:

1. The NAAIM input is unavailable and must remain missing in scoring.
2. The retired public channel is not a daily pipeline failure.

Separately, the free CFTC Traders in Financial Futures report offers official
weekly Asset Manager/Institutional positioning. It is not equivalent to NAAIM,
so it may only be evaluated as a distinct research candidate.

## NAAIM Lifecycle Contract

- Add lifecycle state `RETIRED_PAYWALL`, effective 2026-08-01.
- Keep `data_naaim` and all scoring/configuration unchanged.
- Keep the certified canonical CSV and ledger immutable.
- Continue applying the existing stale-data SLO. Once stale, A2 NAAIM remains
  missing and follows the existing `missing_weight` path.
- Do not synthesize, proxy, forward-fill, or manually fabricate a new NAAIM row.
- Probe the official public channel once per week on Friday Shanghai time.
- A successful subscriber channel may supersede retirement in the future, but
  no subscriber configuration is added by this change.
- Staleness caused by retirement is a nonblocking lifecycle warning.
- `EVIDENCE_DRIFT`, a missing canonical, an invalid ledger binding, or a failed
  weekly probe that invalidates certified evidence remains fail-closed.

## Scheduling Contract

- The 06:45 full refresh excludes a retired source except on its configured
  probe weekday.
- The 07:05 retry may retry a retired source only when that day's scheduled
  probe actually ran and failed, or when canonical evidence is invalid.
- The 07:10 daily consumes the certified canonical and existing SLO result; it
  does not make a third request merely because a retired source was not probed.

## Health and Acceptance Contract

- Status and WebUI expose `lifecycle_status=RETIRED_PAYWALL`, retirement date,
  reason, and weekly-probe policy.
- Morning acceptance records the retirement as an explicit nonblocking
  observation instead of `ACTION_REQUIRED`.
- Source freshness remains visible. The strategy factor can still be missing,
  but retirement alone does not turn the overall strategy health red or amber.
- Canonical evidence errors always take precedence over lifecycle retirement.

## CFTC TFF Candidate Contract

Candidate ID: `CFTC_TFF_ASSET_MANAGER_EQUITY_EXPOSURE`.

- Use only the official CFTC TFF schema.
- Keep Asset Manager/Institutional positioning separate from the rejected
  `data_cot_nq` combined Asset Manager plus Leveraged Funds signal.
- Parse report date, market identity/code, open interest, Asset Manager long,
  short, and spread positions.
- Derive net contracts and net/open-interest ratio with explicit publication
  dates for PIT alignment.
- Produce research artifacts only; do not register a production source, factor,
  config key, feature flag, or pipeline payload field.
- If later promoted to a formal experiment, it must displace A2 NAAIM's two
  points rather than add weight to the already saturated A module.
- One preregistered formal gate is allowed only after offline event/correlation
  evidence is complete. Failure retires the candidate without retuning.

## Out of Scope

- Buying NAAIM access.
- Using social media, mirrors, news summaries, AAII, or PCR as a fake NAAIM row.
- Re-enabling the rejected `data_cot_nq` experiment.
- Changing scoring, route selection, feature flags, production config, or live
  data during this implementation.

## Acceptance Criteria

1. Non-probe days make no NAAIM network call.
2. Probe-day failures are visible but retirement staleness is nonblocking.
3. Canonical evidence drift remains blocking/critical.
4. Existing dates produce byte-identical scoring payloads and input hashes.
5. The CFTC module is importable and tested but unreachable from production.
6. Focused tests, the full suite, governance checks, and four-date equivalence
   all pass before deployment is considered.
