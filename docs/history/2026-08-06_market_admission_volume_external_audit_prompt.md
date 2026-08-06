# Independent Audit Prompt: Market Admission Volume Finalization

Audit the current worktree relative to `7868f30` in
`/Users/liweishi/Documents/github/hermes`. Read
`docs/history/2026-08-06_market_admission_volume_finalization_remediation.md`
first. Stay read-only: do not refresh data, run daily, connect IBKR, modify
live, commit, push, or deploy.

## Required Questions

1. Does any changed production path admit a row that the existing
   `MarketAdmissionSession.admit()` would reject? The required answer is no.
2. Are config, feature flags, source roles, thresholds, routing, scoring, and
   order behavior unchanged?
3. Does the field inventory cover every `market_witness_symbols(config)` entry,
   and is `volume_required=false` limited to symbols whose registered role does
   not consume volume? Pay particular attention to BRK.B, QQQ, component-flow
   constituents, radars, and defensive route legs.
4. Can the field-aware shadow ever count a price mismatch, missing witness,
   absent evidence band, or volume-required symbol as `WOULD_ADMIT`?
5. Is Alpha Vantage called only after a blocking mismatch, once per unique
   symbol/date, and strictly as nonblocking research evidence?
6. Can an API key appear in returned payloads, errors, logs, report files, git
   diff, or test output? Exercise an exception containing the complete URL.
7. Are third-source artifacts separate from canonical admission evidence, and
   can the history analyzer safely ignore their filenames?
8. Does a third-source failure leave canonical history and the official score
   path unchanged?
9. Recompute the 2026-08-05 BRK.B three-way comparison from the retained raw
   bars and confirm `third_source_support=ALPACA_WITNESS`.
10. Reproduce the 18/30 study, field-inventory SHA, four-date equivalence,
    focused tests, full suite, governance, compilation, and secret scan.

## Expected Evidence

- focused suite: `126 passed`
- full suite: `1226 passed`
- governance: `7/7 OK`
- four-date equivalence: `all_equal=true`
- field inventory SHA-256:
  `b17ac01d885ea090e14e0b6255711b0eb32b8321ed794a029be68280d4a49613`
- BRK.B 2026-08-05 candidate-vs-third volume diff: `35.3595%`
- BRK.B 2026-08-05 witness-vs-third volume diff: `1.6583%`
- no config/flag diff and no secret in repository

Verdict format: findings first by severity with file/line evidence, then the
ten answers, commands/results, residual risks, and one of `APPROVE DEPLOY FOR
SHADOW COLLECTION` or `HOLD`.
