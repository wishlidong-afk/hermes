# Single Source of Truth (repo ↔ .hermes)

There are two copies of the package; this records which is canonical and how they
stay one, so they stop drifting.

## Canonical

- **Code** → the git repo: `src/hermes_escape_top/`. This is the single source of
  truth. The 8766 WebUI is served from here (`scripts/serve_escape_8766_repo.sh`).
- **Live runtime** → `~/.hermes/skills/investment/escape-top/hermes_escape_top/` is
  a **deployment mirror** of the repo code. It is NOT a second source — it is kept
  byte-identical to the repo by syncing.

## Converged 2026-06-08

As of this date the two were reconciled: **repo and .hermes package code are
0-diff** (verified file-by-file, excl tests/__pycache__). The live daily decision
(2026-06-05: MSTR/FNGU/SOXL all EXIT) is unchanged by the sync.

## Sync procedure (repo → .hermes)

Code is the only thing that should ever be synced (data and config are
environment-managed). After changing repo code:

```sh
REPO=~/Documents/github/hermes/src/hermes_escape_top
HP=~/.hermes/skills/investment/escape-top/hermes_escape_top
rsync -ri --exclude='__pycache__/' --exclude='tests/' \
  --include='*/' --include='*.py' --exclude='*' "$REPO/" "$HP/"
```

Because every risk factor and the arm-then-fire mechanism are **flag-gated OFF**,
syncing code never changes the live decision unless a flag is also flipped in
config. Always re-verify after a sync by scoring the latest day in both and
diffing status/sell_fraction.

## Config: deployed state matches, with ONE flagged divergence

`config.json` deployed flags are identical in both (A10/A11/A15 ON, DEFENSIVE_EXIT
70; A12–A19 + use_arm_then_fire OFF). The inert OFF flags + A-factor missing-weights
were added to .hermes on 2026-06-08 to match repo.

⚠️ **One real divergence to resolve (left untouched — it's a live-behaviour
decision):** the repo `config.json` has an `ibkr.executions` block (auto-confirm
enabled, client_id 1042) that the `.hermes` config does **not**. Decide which is
correct and make both match, rather than letting it drift.

## Known incidental behaviour

Running `score_pipeline` / `serve` triggers `bootstrap_history` which copies OHLCV
from a legacy dir, refreshing the repo's tracked history CSVs (e.g. 06-04 → 06-05).
This is benign data churn but dirties the working tree — revert it before commits:
`git checkout -- src/hermes_escape_top/data/history/`. (Worth fixing later so
read-only scoring never writes tracked data.)
