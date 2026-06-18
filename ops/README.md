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
| `run_daily.py` | `~/.hermes/skills/investment/escape-top/scripts/run_daily.py` | runs the package via `-m` (single engine) |
| `serve_dashboard.sh` | `~/.hermes/bin/serve_dashboard.sh` | launchd `com.hermes.dashboard` ExecStart; `$HOME`-relative |
| `launchagents/com.hermes.*.plist` | `~/Library/LaunchAgents/` | **machine-specific** (absolute `/Users/...` paths) — reference/backup, edit paths before reuse on another machine |

The Python package itself deploys via `scripts/deploy_to_live.sh`; these ops files
change rarely and are synced/restored by hand from here when they do.

## verify_live.sh — post-deploy end-to-end gate

`predeploy_smoke` runs the *package* and checks data state; it does **not** run the
real entry. `verify_live.sh` closes that seam: it runs the actual
`run_daily.sh → run_daily.py → -m` chain and asserts the **effects landed** (the
run-receipt is fresh + green, and the maintenance steps appear in the log) — the
one check that would have caught B at deploy time instead of at the next 07:10.
Wired as the final gate of `deploy_to_live.sh`.
