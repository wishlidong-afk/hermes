# Market Health Five-Day Observation Closure

Date: 2026-08-28
Release under observation: `66bd598_20260822_102647`
Decision: **CLOSED / STABLE MAINTENANCE**

## 1. Scope

This note closes the natural-run observation period following the market-health
evidence remediation deployed on 2026-08-22. It records existing read-only
evidence only. No daily run, market refresh, external-source refresh, IBKR
connection, scoring change, feature flip, or live mutation was performed to
produce this document.

The observation contract required:

- five consecutive natural market-admission observations;
- one scheduled receipt and one scheduled audit row per decision date;
- a committed score transaction with all seven business artifacts and no active
  transaction residue;
- a healthy 09:00 watchdog;
- release and policy certification against the running live version;
- no strategy-blocking health issue.

## 2. Five-Day Evidence

Source files:
`~/.hermes/logs/acceptance/morning_acceptance_2026-08-24.json` through
`morning_acceptance_2026-08-28.json`.

| Acceptance date | Decision as-of | Overall | Runtime | Strategy | Certification | Scheduled audit | Transaction | Watchdog | Admission streak |
|---|---|---|---|---|---|---|---|---|---:|
| 2026-08-24 | 2026-08-21 | PASS | PASS | WARN | CERTIFIED | count=1 | COMMITTED, 7 artifacts | PASS | 1 |
| 2026-08-25 | 2026-08-24 | PASS | PASS | WARN | CERTIFIED | count=1 | COMMITTED, 7 artifacts | PASS | 2 |
| 2026-08-26 | 2026-08-25 | PASS | PASS | WARN | CERTIFIED | count=1 | COMMITTED, 7 artifacts | PASS | 3 |
| 2026-08-27 | 2026-08-26 | PASS | PASS | WARN | CERTIFIED | count=1 | COMMITTED, 7 artifacts | PASS | 4 |
| 2026-08-28 | 2026-08-27 | PASS | PASS | WARN | CERTIFIED | count=1 | COMMITTED, 7 artifacts | PASS | 5 |

All five transaction manifests reported `active=absent`. The dashboard health
endpoint returned HTTP 200 throughout the period. The market-admission evidence
reached the required five consecutive OK observations on 2026-08-28.

## 3. Remaining Non-Blocking Conditions

### IBKR

IBKR remained stale or unavailable and was classified as non-blocking INFO. This
affects position reconciliation and estimated trade amounts only. It does not
change scores, strategy decisions, target weights, or the acceptance verdict.
IBKR should be refreshed only when current holdings are needed for execution
reconciliation.

### Dollar

Dollar produced a policy WARN on 2026-08-24 and 2026-08-28. On the final day the
official source had been checked that day, while the publisher's latest
observation was seven days old. This remains an operations warning, not a
strategy block. Repeated manual refreshes are not warranted. Investigation is
required only if the source exceeds its formal SLO or misses two expected
publisher releases.

## 4. Closure Decision

The remediation is accepted for stable maintenance:

- runtime integrity passed 5/5 days;
- post-deploy certification remained `CERTIFIED` 5/5 days;
- scheduled receipt, scheduled audit, transaction, and watchdog evidence passed
  5/5 days;
- market admission reached the five-day target;
- no strategy-blocking condition occurred;
- the remaining warnings are explicitly scoped and non-blocking.

No new factor, WebUI, routing, or strategy experiment should be opened as part
of this remediation. The daily 09:10 acceptance cron remains the authoritative
check; the 09:15 thread heartbeat is notification-only and must never execute a
replacement acceptance run.

## 5. Reopen Criteria

Reopen this remediation only if one of the following occurs:

- morning acceptance returns `FAIL`;
- runtime integrity is not `PASS`;
- post-deploy certification is not `CERTIFIED`;
- scheduled audit count differs from one for the selected official run;
- a score transaction is not `COMMITTED`, has fewer than seven artifacts, or
  leaves an active transaction behind;
- market admission reports evidence drift or a strategy-blocking rejection;
- Dollar exceeds its formal SLO or misses two expected releases;
- IBKR data is used for execution reconciliation while stale.
