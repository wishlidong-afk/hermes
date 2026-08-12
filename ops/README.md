# ops/ — deploy artifacts that run in production but aren't in the package

These are the **live-only entry/scheduler files**: they aren't part of the
`hermes_escape_top` Python package, but they're what actually runs the system in
production. Until 2026-06-17 they lived **only** on the machine (not in git), so
they could drift or break invisibly — the two incidents that cost the most:

- **B**: a loose `run_daily_package.py` copy the daily ran went 4 days stale (now
  eliminated — `run_daily.py` runs the package via `-m`).
- **next5watch 127**: a launchd job pointed at a wrapper script that never existed.

Versioned here so drift shows up in a `git diff`, they're restorable, and a
reviewer can see the *whole* execution path, not just the package.

## File → live location

| repo `ops/` | live location | notes |
|---|---|---|
| `run_daily.sh` | `~/.hermes/bin/run_daily.sh` | launchd `com.hermes.daily` ExecStart; `$HOME`-relative (portable) |
| `refresh_external_precheck.sh` | `~/.hermes/bin/refresh_external_precheck.sh` | launchd `com.hermes.external-precheck` ExecStart; runs external source readiness before daily, no scoring/official run write |
| `retry_market_third_source.sh` | `~/.hermes/bin/retry_market_third_source.sh` | launchd `com.hermes.market-third-source` ExecStart; retries delayed Alpha Vantage evidence at 09:02 without touching canonical history or scoring |
| `prune_runtime_artifacts.py` | `~/.hermes/bin/prune_runtime_artifacts.py` | launchd `com.hermes.runtime-retention`; weekly bounded cleanup under the pipeline lock |
| `run_daily.py` | `~/.hermes/skills/investment/escape-top/scripts/run_daily.py` | runs the package via `-m` (single engine) |
| `serve_dashboard.sh` | `~/.hermes/bin/serve_dashboard.sh` | launchd `com.hermes.dashboard` ExecStart; `$HOME`-relative |
| `launchagents/com.hermes.*.plist` | `~/Library/LaunchAgents/` | **machine-specific** (absolute `/Users/...` paths) — reference/backup, edit paths before reuse on another machine |

The Python package itself deploys via `scripts/deploy_to_live.sh`; the deploy
transaction also syncs, backs up, restores, and reloads these ops entrypoints.

## Runtime retention

`com.hermes.runtime-retention` runs Sundays at 08:30 CST. It keeps the newest
12 releases, 10 deploy backups, 12 compressed audit archives, and 50 completed
score transactions, with independent byte caps. `current`, `previous`, and the
active score transaction are always protected. Apply mode acquires the same
nonblocking `.pipeline.lock` as scoring and deployment; a busy lock records
`BUSY` and deletes nothing. Dated/latest evidence is written to
`~/.hermes/logs/retention/runtime_retention_*.json`.

## External precheck severity

`com.hermes.external-precheck` runs at 06:45 and 07:05. A stale source normally
keeps the precheck non-ready. Dollar remains a narrow publication-lag exception: when the
current refresh attempt succeeded, `use_soft_data_max_age` and `data_dollar`
are enabled, and its age exceeds the configured strategy SLO, it remains a
visible policy WARN instead of generating a FAILED notification. The report
says to wait for the publisher rather than retrying the already-successful
refresh.

NAAIM is a separate lifecycle exception. Its public workbook retired behind a
paywall on 2026-08-01, so certified history is frozen and the source is probed
only on Friday Shanghai time. Retirement staleness is an INFO and still follows
the scoring missing-weight policy; canonical evidence drift or a missing
certified file remains blocking.

Any Dollar fetch/parse failure, missing policy evidence, or stale second source
remains blocking. This exception does not change scoring or the configured
Dollar SLO.

## verify_live.sh — post-deploy end-to-end gate

`predeploy_smoke` runs the *package* and checks data state; it does **not** run the
real entry. `verify_live.sh` closes that seam: it runs the actual
`run_daily.sh → run_daily.py → -m` chain and asserts the **effects landed** (the
manual audit is fresh, maintenance steps appear in the log, and no official
receipt/state is written) — the one check that would have caught B at deploy time
instead of at the next 07:10 without creating a second scheduled run. Wired as
the final gate of `deploy_to_live.sh`.

## Delayed market evidence

`com.hermes.market-third-source` runs at 09:02, after the US daily-bar vendor's
publication window. It only retries the Alpha Vantage shadow for the latest
market-admission operation. The dashboard accepts that delayed evidence only
when both `admission_operation_id` and `completed_through` exactly match the
selected admission payload. It never changes canonical history, admission
status, scoring, official receipts, or `input_hash`. The write uses the shared
pipeline lock; lock contention returns `BUSY` instead of writing concurrently.

## morning_acceptance.py — 09:10 read-only acceptance

Run from the repository after the 07:10 scheduled daily, the 09:00 watchdog,
and the 09:02 delayed market-evidence retry:

```bash
/usr/bin/python3 ops/morning_acceptance.py
```

It verifies the R6 release identity, today's single scheduled receipt and
audit record, the six-artifact score transaction, the input-hash-bound health
report, the 8766 health API, and the scheduled watchdog result. Reports are
written atomically to:

- `~/.hermes/logs/acceptance/morning_acceptance_<date>.json`
- `~/.hermes/logs/acceptance/morning_acceptance_<date>.md`
- matching `morning_acceptance_latest.*` aliases

Exit `0` means PASS; exit `2` means one or more acceptance checks failed.
Stale Dollar data remains a visible permitted WARN, and stale/unavailable IBKR
remains a visible nonblocking INFO. Other strategy or auxiliary-flow
degradation fails acceptance.

The seven primary checks remain stable for automation consumers. A separate
`operational_observations` block tracks weekly retention APPLY evidence, dated
market-admission evidence, and AAII automatic-channel plus NAAIM lifecycle evidence.
Retention is PENDING before its first expected Sunday window, WARN when missing
afterward or older than eight days, and PASS only for a recent successful APPLY
report. Market admission is OBSERVING for one or two consecutive OK dates and
mature after three (with five as the operational target). AAII/NAAIM evidence
is read from the same-day external precheck artifact and includes channel,
official issue date, artifact SHA-256, freshness, and migration deadline; the
observer never fetches either source. `RETIRED_PAYWALL` is accepted only while
the frozen NAAIM canonical remains ledger-bound. Only WARN observations are added to the
summary; they do not change the seven-check schema.

This command is an observer, not a repair command. It never runs daily, scores,
refreshes data, or connects to IBKR. On FAIL, inspect the cited evidence and
follow the production runbook separately.
