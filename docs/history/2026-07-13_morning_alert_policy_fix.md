# Morning Alert Policy Fix - 2026-07-13

## Incident

The 07:10 scheduled escape-top run completed successfully, but the operator saw
multiple failure notifications. Two scheduled external prechecks each returned
exit 3 for the same Dollar publisher lag, and the 09:05 acceptance monitor then
failed because health represented that same Dollar condition in two rows.

Core production evidence was healthy: receipt `OK`, one scheduled audit,
six-artifact transaction `COMMITTED`, data quality `HIGH 97.6`, 8766 HTTP 200,
and watchdog `ok`.

## Root Cause

Dollar refresh returned `OK`, but the publisher's latest observation remained
2026-07-02. The external readiness profile classified age 11 days as `STALE`
and blocking, while the production scoring policy intentionally treats Dollar
past its six-day SLO as visible defensive missing data. Health then emitted both
`soft source stale: dollar` and `external source stale: dollar`; the acceptance
allowlist recognized only the first representation.

## Fix

1. External precheck downgrades only Dollar publisher lag to WARN when all of
   these are true: current refresh `OK`, source ledger `OK/STALE`,
   `use_soft_data_max_age=true`, `data_dollar=true`, and age exceeds the
   configured Dollar SLO.
2. Dollar refresh/parse errors, missing evidence, guard-off state, and every
   other stale source remain blocking.
3. Policy-warn output says the official source was checked today and instructs
   the operator to wait for the publisher instead of repeating refresh.
4. Morning acceptance coalesces the two exact Dollar-only health rows into one
   visible warning. Any second source still fails acceptance.

No data, config, score, receipt, audit, IBKR state, or live strategy output was
modified during diagnosis and implementation.

## TDD Evidence

- New policy-stale Dollar test failed as blocking before the fix.
- New duplicate-Dollar acceptance test failed before the fix.
- A stale real-rate row remained failing throughout.
- A Dollar fetch error remains blocking even with stale cached data.
- Focused external/acceptance/ops/health suite: `73 passed`.
- Final full suite: `802 passed in 104.52s`, with no warnings.

## Live Read-Only Replay

Using the 2026-07-13 external precheck JSON without refreshing sources:

```text
DOLLAR_POLICY_WARN_ONLY True
status=OK freshness=STALE age_days=11 latest=2026-07-02
current refresh status=OK
```

Using the fixed acceptance code against the current live receipt, audit,
transaction, health API, and watchdog:

```text
PASS; allowed warnings: dollar stale; IBKR stale/unavailable
```

The replay wrote only the acceptance monitor's own report under
`~/.hermes/logs/acceptance/`.

## Deployment Evidence

Deployed with R6 atomic release switching at 10:06 CST:

```text
repo/live VERSION: feab9c5 20260713_100612
current:  releases/feab9c5_20260713_100612
previous: releases/d9ec486_20260712_184620
staged smoke: PASS with policy-verified Dollar WARN
verify_live: PASS; official receipt/state untouched
dashboard: HTTP 200; preview banner absent
refresh_external.py repo/live SHA-256: identical
post-deploy morning acceptance: PASS with Dollar WARN and IBKR INFO
~/.hermes commit: c41727c
```

The config prompt was answered `N`; live runtime config was preserved. The
07:11 scheduled receipt remained `OK`, `as_of=2026-07-10`, with its original
timestamp.
