# Hermes Morning Acceptance Audit - 2026-07-12

## Verdict

Implementation verification: **PASS**.

The 2026-07-12 live probe returned **expected pre-first-run FAIL** only for
`persistence_transaction`. Today's 07:10 scheduled run occurred before the R6
release `d9ec486` was deployed at 18:46, so its audit payload cannot contain the
new recoverable-journal evidence. The first meaningful production acceptance
is the 2026-07-13 09:05 check, after the new release's 07:10 scheduled run and
09:00 watchdog.

## Delivered Files

- `ops/morning_acceptance.py`
- `src/hermes_escape_top/tests/test_morning_acceptance.py`
- `ops/README.md`
- `docs/superpowers/specs/2026-07-12-morning-acceptance-design.md`
- `docs/superpowers/plans/2026-07-12-morning-acceptance.md`

## Contract Coverage

The verifier independently checks:

1. R6 `current` symlink and `VERSION` identity.
2. Today's successful scheduled receipt.
3. Exactly one scheduled audit record on the local calendar date.
4. The audit-bound transaction manifest is `COMMITTED`, covers the exact six
   `archive/...` business paths, and leaves no `active.json`.
5. The system-health report has the same `as_of`, `run_type`, and `input_hash`
   as the scheduled audit.
6. The 8766 health API is HTTP 200 and agrees with the scheduled run.
7. The 09:00 watchdog window contains `ok` and no `ALERT`.

Only exact Dollar staleness is accepted as a visible WARN. A combined detail
such as `dollar, naaim_exposure` fails. IBKR stale/unavailable remains a visible
nonblocking INFO. Any other strategy or auxiliary-flow degradation fails.

## TDD Evidence

- Initial happy-path test: failed because `ops/morning_acceptance.py` did not
  exist, then passed after the collector was implemented.
- Atomic report test: failed because `write_reports` did not exist, then passed.
- Binding tests: transaction metadata, exact artifact paths, and report
  `as_of/run_type` each failed against the initial implementation, then passed
  after the gates were tightened.
- Dollar masking test: `dollar, naaim_exposure` incorrectly passed before the
  exact-detail rule; it now fails acceptance.
- Focused result: `12 passed`.
- Full result: `797 passed in 102.37s`.
- `/usr/bin/python3 -m py_compile ops/morning_acceptance.py`: PASS.
- `git diff --check`: PASS.

## Live Read-Only Probe

Command:

```bash
/usr/bin/python3 ops/morning_acceptance.py
```

Observed at `2026-07-12T19:11:01+08:00`:

| Check | Result | Evidence |
|---|---|---|
| release identity | PASS | `d9ec486_20260712_184620` |
| scheduled receipt | PASS | `OK`, as_of `2026-07-10` |
| scheduled audit | PASS | exactly one; input hash `87cdb6293e3c78e5` |
| persistence transaction | EXPECTED FAIL | old scheduled audit has no persistence evidence |
| bound health report | WARN | Dollar stale + IBKR nonblocking |
| dashboard health | WARN | HTTP 200; same permitted warnings |
| watchdog | PASS | `2026-07-12T09:00:05+08:00 ok` |

Before and after the probe, SHA-256 and mtime were compared for the six business
artifacts, `run_receipt.json`, and the bound system-health report. Diff line
count: **0**. The verifier wrote only its own reports under
`~/.hermes/logs/acceptance/`.

## 2026-07-13 Decision Rule

At 09:05 CST:

- PASS requires all seven checks to pass, with only the documented Dollar WARN
  and IBKR INFO permitted.
- FAIL must be reported as-is. The monitor must not run daily, refresh data,
  connect to IBKR, or repair live state.
- A transaction failure after the new 07:10 run is a real release-acceptance
  failure and requires evidence review before any remediation.
