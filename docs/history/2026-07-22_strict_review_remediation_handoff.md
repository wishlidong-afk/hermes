# Hermes Strict Review Remediation Handoff

Date: 2026-07-22
Branch: `hermes-docs`
Starting HEAD: `90b1b57`
Deployment performed: **No**

## Decision

- Implementation and locked-runtime verification: **PASS**.
- Push/commit: **HOLD for a correctly scoped independent review**.
- Live deployment: **HOLD**.
- Strategy/config authorization: **NO FLIP**. No score threshold, route, feature
  default, IBKR policy, or order path was changed.

### External audit scope correction

An external report dated 2026-07-22 audited the committed range
`e266ac7..90b1b57` and returned PASS. That report is useful evidence for the 20
already-committed changes, but it is **not release approval for this batch**:

- this batch is still an uncommitted working-tree diff on top of `90b1b57`;
- the report did not include the 34 current working-tree paths or this untracked
  handoff;
- its RR-1 statement that CI installs `requirements.txt` is stale: the current
  workflow installs `requirements.lock`;
- its RR-3 statement that only the developer venv was tested is stale: the
  current batch was verified in a clean Python 3.11 environment synced from
  `requirements.lock`;
- the BTC/AAII compatibility fixes it marked out of scope are current
  working-tree changes and therefore still require independent review; and
- its `APPROVE DEPLOY` conclusion conflicts with the two explicit deployment
  blockers below.

The next reviewer must start from `git status --short`, audit `git diff HEAD`
plus this untracked handoff file, and independently rerun the locked-runtime
checks. A commit-range-only review ending at `90b1b57` is insufficient.

Deployment is held for two independent evidence reasons:

1. the retained current baseline is `STALE` against the current code/data
   provenance (`cache_key`, `manifest_id`, `code_sha256`, and
   `soft_history_sha256` differ); and
2. live strategy health is `DEGRADED` because the latest market-admission
   evidence still isolates `SHV 2026-07-21` for a `36.0426%` raw-volume
   mismatch. Its OHLC difference is zero. No threshold was relaxed and no row
   was whitelisted.

## Remediation Results

### 1. Acceptance evidence is split by purpose

`ops/morning_acceptance.py` now adds an additive `readiness` block without
changing the original seven checks or overall exit semantics:

- `runtime_integrity`: release identity, scheduled receipt/audit, six-artifact
  persistence transaction, and watchdog;
- `strategy_decision`: input-hash-bound health evidence and dashboard health.

This prevents an intact runtime from being described as a usable strategy when
the strategy-data chain is blocked, while preserving existing automation
consumers.

### 2. Market witness evidence separates price and volume

The existing fail-closed admission decision and thresholds are unchanged.
Evidence now records:

- exact price and volume policy thresholds;
- `price_evidence_status` and `volume_evidence_status` per row;
- aggregate price/volume summaries in the admission artifact; and
- both summaries in health detail when a candidate is isolated.

This makes an OHLC match plus a raw-volume mismatch visible instead of reducing
the event to a generic witness failure.

### 3. Turnover experiments have a sealed gate contract

Formal gate schema `hermes-formal-gate-v3` is backward compatible with v1/v2
and adds an exact `turnover_objective`:

- metric: `total_turnover` or `route_set_turnover`;
- `max_delta_vs_baseline`: finite and strictly negative;
- missing/non-finite turnover evidence: `BLOCKED`;
- a target that misses the pre-registered reduction: `REJECTED / NO_FLIP`.

The CLI reads the metric from the already-produced candidate artifact and
prints the sealed comparison. This creates an experiment lane; it does not run
an experiment or authorize a feature flip.

### 4. Modeled opening prices are governed

Governance now independently checks retained execution-timing evidence:

- execution-required missing opens must equal zero;
- modeled execution-required opens must be at most 15% of required rows;
- missing, malformed, negative, or empty evidence fails closed.

Current retained evidence passes at `1343 / 10045 = 13.37%`, leaving only
1.63 percentage points of headroom. This is a ceiling, not a quality target.

### 5. AAII/NAAIM migration evidence is observed daily

Morning acceptance reads the same-day external precheck artifact without
network access or canonical writes. For AAII and NAAIM it validates:

- automatic official channel;
- current-day successful precheck;
- freshness and evidence match;
- official issue date and SHA-256 fingerprint; and
- migration status/deadline.

Pre-deadline NAAIM `MIGRATION_DUE` is `OBSERVING`; a manual channel,
`ACTION_REQUIRED`, stale evidence, invalid fingerprint, or a missed deadline is
`WARN`. The observation is additive and does not change the seven-check schema.

### 6. HTTP probes and CI evidence are separated

- `/health` remains a backward-compatible liveness alias.
- `/livez` proves the HTTP process is alive.
- `/readyz` returns 200 only when `strategy_data.level=OK`; a missing strategy
  layer fails closed as `MISSING`, while auxiliary IBKR/SIP degradation alone
  does not block it.
- deployment probes `/livez`, not strategy readiness, because strategy data may
  legitimately remain blocked after a successful code rollback/swap.
- CI installs the same hashed `requirements.lock` consumed by R6 live runtime,
  runs high-severity Ruff checks, targeted mypy checks, and `pip-audit`.

### 7. Runtime dependencies and hidden compatibility debt

Runtime pins were moved to Python 3.10+ compatible security releases:

- `requests 2.33.0`;
- `curl-cffi 0.15.0`;
- `yfinance 1.2.1`.

The lock changes only those packages plus the new `curl-cffi` transitive
dependencies (`rich`, `markdown-it-py`, `mdurl`, and `pygments`). A clean
Python 3.11 environment exposed two pre-existing defects that the developer
environment had hidden:

- the project named a nonexistent setuptools legacy backend; it now uses
  `setuptools.build_meta:__legacy__`;
- BTC micro data retained object-typed numeric columns under locked pandas
  2.3.3 and failed before promotion. Numeric columns and nullable booleans are
  now explicit;
- AAII first-import concatenation no longer invokes pandas' empty-frame dtype
  behavior.

No canonical/live data was touched while reproducing or fixing these paths.

## Verification Evidence

| Check | Result |
|---|---|
| Locked Python 3.11 full suite | `1188 passed` in 121.55s, no warnings |
| Focused changed-area suite | `220 passed` |
| Locked BTC source suite | `14 passed`, warning-free |
| Locked AAII/refresh suite | `67 passed`, warning-free |
| Ruff severe rules | PASS (`E9,F63,F7,F82`) |
| Targeted mypy | PASS, 4 modules |
| Dependency audit | `No known vulnerabilities found` |
| `pip check` | `No broken requirements found` |
| Governance | `7/7 OK` |
| Compile | `python -m compileall` PASS |
| Deploy syntax | `bash -n scripts/deploy_to_live.sh` PASS |
| Lock preservation | `uv pip compile --no-upgrade` retained all 29 versions |
| Git whitespace | `git diff --check` PASS |

The dependency audit emits only its informational warning that `--no-deps` is
being used; every runtime dependency is nevertheless exact and hashed in the
audited lock file.

## Read-Only Live Snapshot

- live VERSION: `e266ac7 20260720_144956`;
- dashboard root: HTTP 200;
- `/health`: `{"ok":true}` from the old live release;
- active daily/refresh/deploy writers at evidence time: none;
- business health: `DEGRADED`, one market candidate isolated;
- latest market admission: 127 admitted, one nonblocking BTC unfinished-day
  deferral, one blocking SHV volume mismatch, no fetch error.

The candidate `/livez`, `/readyz`, and split price/volume evidence are not yet
present in live because this work has not been deployed.

## Independent Review Checklist

1. Confirm no diff in `config/config.json`, approved live config, routing
   weights, score thresholds, or IBKR readonly policy.
2. Re-run the full suite from a fresh Python 3.11 environment installed from
   `requirements.lock`, not from the developer venv.
3. Confirm formal gate v1/v2 hashes and behavior remain compatible and v3 fails
   closed on missing turnover evidence.
4. Confirm `/readyz` depends only on the strategy-data layer and `/livez` never
   reads business state.
5. Confirm morning acceptance performs no fetch, scoring, canonical promotion,
   or IBKR connection while evaluating AAII/NAAIM migration evidence.
6. Confirm market-admission overall decisions and numeric thresholds are
   unchanged; only evidence labeling is additive.
7. Confirm `requirements.lock` is installed by both CI and R6 runtime and the
   old vulnerable pins are absent.
8. Confirm the BTC and AAII compatibility fixes operate only before validation
   and do not bypass semantic validation or promotion rules.

## Required Next Sequence

1. Independent review this worktree.
2. Commit and push only after approval.
3. From a clean committed research tree, rebuild the current baseline and its
   execution-timing/cost/governance derivatives against the approved live
   config. Run full backtest/gate work one process at a time with isolated data.
4. Re-run governance and baseline freshness; both must be green.
5. Wait for a certified market-admission run with no blocking row, or approve a
   separate multi-day source-policy change. Do not weaken the SHV threshold as
   part of this batch.
6. Only then run the R6 deployment and post-deploy `/livez`, `/readyz`, VERSION,
   default-page, official-receipt, and morning-acceptance checks.
