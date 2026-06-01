# Phase 12 Report - Mirror Reference System

Date: 2026-06-01

## Scope

Phase 12 adds an independent mirror-reference strategy:

- QQQ/FNGU sleeve capped at 20%.
- SOXX/SOXL sleeve capped at 30%.
- MSTR/QQQ sleeve capped at 15%.
- Cycle states: `RISK_ON`, `BASE_DEFENSE`, `CASH`.
- SQLite snapshot persistence for mirror decisions.

## Verification

- Synthetic risk-on inputs select FNGU/SOXL/MSTR.
- SQLite snapshot stores one row per mirror sleeve.
- `score_pipeline(...)` includes mirror decisions and DB path.

## Remaining Gaps

- Posterior ideal P/L is implemented in Phase 15.
- WebUI presentation is implemented as a read-only greenfield dashboard in Phase 15.
- IBKR position reconciliation remains outside this mirror module.
