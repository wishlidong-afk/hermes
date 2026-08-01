# NAAIM Media Discovery + Health Severity Remediation Handoff

Date: 2026-08-01

## Scope

This working-tree change addresses two observed failure modes without changing
configuration, scoring, routing, feature flags, market-admission thresholds, or
live runtime data:

1. NAAIM's public index page no longer exposes a direct workbook link.
2. A failed refresh attempt blocked strategy health even when the certified
   canonical file was current and its promotion evidence still matched.

No deployment or official daily run was performed as part of this work.

## Changes

### 1. Official NAAIM media discovery fallback

- The existing direct-link discovery remains the first choice.
- If the index page has no workbook link, the adapter queries NAAIM's official
  WordPress Media API.
- A candidate is accepted only when all of the following hold:
  - host is `naaim.org` or an `naaim.org` subdomain;
  - transport is HTTPS;
  - path ends in `.xlsx`;
  - WordPress MIME is the official XLSX MIME;
  - the newest dated candidate wins under the existing workbook ranking rule.
- Existing parsing, validation, ledger writing, atomic promotion, subscriber,
  and manual-import paths are unchanged.

Read-only real-network canary:

- channel: `wordpress_media_api`
- workbook: `USE_Data-since-Inception_2026-07-29.xlsx`
- parsed rows: 1,047
- latest observation: 2026-07-29
- live writes: none

### 2. Certified-cache health semantics

The shared predicate `certified_canonical_is_current()` requires:

- canonical status `OK`;
- freshness `OK` or `DUE_SOON`;
- evidence status exactly `MATCH`.

Only when all three conditions hold does a failed latest refresh become a
nonblocking operations warning. The failure remains visible in the health
check list and morning acceptance output.

If the canonical is stale, missing, unbound, or drifted, the existing strategy
degradation/fail-closed behavior remains in force.

### 3. WebUI and morning acceptance

- Health now exposes a separate `operations` layer.
- Morning acceptance reports operations `DEGRADED`/`INFO` as an allowed warning;
  operations `CRITICAL` remains a failure.
- The external-data summary renders a protected retry as
  `OK 1 / ERR 0 / MISS 0 · RETRY 1` with warning styling.
- A failed retry against stale or uncertified data remains a red `ERR`.

## Verification

- NAAIM focused suite: 24 passed.
- Health + morning acceptance: 49 passed.
- Related NAAIM/external refresh/health/morning/WebUI/receipt suite: 199 passed.
- Full suite: 1,211 passed.
- Governance consistency: 7/7 OK.
- Compile check: clean.
- `git diff --check`: clean.

## Independent Review Checklist

1. Confirm direct page discovery still wins when a valid link exists.
2. Confirm Media API candidates cannot escape the official host or XLSX MIME
   restrictions.
3. Confirm malformed/empty Media API responses fail closed and cannot promote.
4. Confirm subscriber and manual-import paths are unchanged.
5. Confirm nonblocking severity requires `status=OK`, current freshness, and
   `evidence_status=MATCH` simultaneously.
6. Confirm stale, missing, unbound, and drifted canonical cases still degrade or
   fail as before.
7. Confirm WebUI shows protected failures as `RETRY`, while preserving the full
   attempt error in diagnostics.
8. Confirm no config, scoring, routing, flag, IBKR policy, or production order
   path changed.

## Release Recommendation

Ready for independent review. After approval: commit and push, verify no
daily/refresh writer is active, then use the R6 deploy path while retaining the
live config. Deployment verification must not rerun the official daily. The
next natural external precheck should provide the first production promotion
evidence for the new NAAIM discovery channel.
