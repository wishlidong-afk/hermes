# 2026-07-15 Evidence and Runtime Hardening External Audit Handoff

## 1. Status and boundary

This handoff covers the ten repository commits after the current live release.
The implementation is committed locally but has not been pushed or deployed.

| Field | Value |
|---|---|
| Repository | `/Users/liweishi/Documents/github/hermes` |
| Branch | `hermes-docs` |
| Audit base / current live | `b3eea6d5b40cab90b8fcceb1b4ee423c034531ac` |
| Implementation tip | `2af77bb91e99ed8102f8be3260927fafd14c22e7` |
| Latest gate-affecting commit | `b515f98b17dbf6061964048ba806877a5209a5d1` |
| Live VERSION at handoff | `b3eea6d 20260715_094737` |
| 8766 at handoff | HTTP 200 |
| Full suite | `1034 passed in 108.67s` |
| Deployment status | Not pushed; not deployed |

The handoff document itself may be committed after `2af77bb`. It is a docs-only
commit and is outside the implementation range. The baseline intentionally uses
the latest commit affecting gate code or repository config, not an arbitrary
later documentation commit.

### Strict audit safety rules

The audit is read-only unless a command below explicitly writes to `/tmp`.

- Do not run `run_daily`, `manual_rerun`, a full-window gate, or a live refresh.
- Do not connect to or refresh IBKR.
- Do not run `ops/prune_runtime_artifacts.py --apply`.
- Do not deploy, push, flip a feature flag, or modify live config.
- Do not point tests or research runs at the writable live data directory.
- Do not stage, delete, or reinterpret the two known untracked paths:
  `building/reports/current_baseline/CURRENT_BASELINE_FULL.json` and
  `building/reports/execution_timing/`.

## 2. Commit scope

Review these commits in order:

1. `1e0bcc1` - harden evidence, source recovery, and runtime operations
2. `8532e40` - bind execution timing baseline to explicit config
3. `80c64b7` - gate execution evidence on required opening prices
4. `b37bd16` - rebuild current next-open baseline
5. `07f438d` - make baseline evidence reproducible across commits
6. `3073415` - record reproducible current baseline evidence
7. `360aced` - align gate provenance with code hash scope
8. `1e8c826` - refresh baseline after provenance scope fix
9. `b515f98` - tighten evidence append and retention rollback guards
10. `2af77bb` - refresh baseline after evidence hardening

The net diff is `b3eea6d..2af77bb`. Generated equity and execution-sensitivity
artifacts make the textual diff large; auditors should review implementation
files and machine evidence separately rather than treating generated curve rows
as source code.

## 3. Claims under audit

### A. Market evidence and decision date

1. A canonical history file that strictly appends newer, valid, increasing dates
   is classified as `SUPERSEDED_BY_NEWER_DATA`, not false `EVIDENCE_DRIFT`.
2. Duplicate headers, malformed appended rows, duplicate dates, or out-of-order
   dates are not accepted as a strict append.
3. Dashboard evidence selection is read-only and lives in
   `web/market_evidence.py`; it does not write or certify history.
4. Daily, Web, and CLI resolve implicit decision dates through the same
   `decision_as_of` helper and the same decision-symbol set. Explicit historical
   dates remain unchanged.

Primary files:

- `src/hermes_escape_top/core/data/market_admission.py`
- `src/hermes_escape_top/core/data/decision_as_of.py`
- `src/hermes_escape_top/web/market_evidence.py`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/refresh.py`
- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/scripts/run_daily_package.py`

Required PASS evidence:

- Append-only tests reject every non-canonical append listed above.
- Existing canonical history is never rewritten by dashboard evidence reads.
- Implicit dates agree across entry points; explicit dates are not silently
  advanced.

### B. Current next-open baseline and provenance

The formal comparator is bound to an explicit committed config snapshot,
frozen history/soft-history fingerprints, a gate-code commit, and
`equity_timing=next_open`.

Recorded evidence:

| Field | Value |
|---|---|
| Requested window | `2018-01-01` to `2026-07-14` |
| Effective window | `2018-01-02` to `2026-07-14` |
| Trading days | 2,143 |
| History manifest | `24cf3da83b7fc6fb09d17546922d1d3d4d7ec874f84cbf4b75119739dafe54bc` |
| Soft-history SHA256 | `02afefadd8474119d8a0209b63e747de94ee3c35e45441d4c50c2c8bcb0fdd19` |
| Config SHA256 | `7de18c09ee2d245851fbf8dc682abc5eac521e5312508b09155307bdb26a6e56` |
| Code SHA256 | `4834b8b0063482ab4a73508ce9965fb91603e55a9c459308bdcda8a3036b2827` |
| Full-source SHA256 | `4b3cdd5972ed386f420d74a1af248cc909ba97b52df59aecd6c16fca75c8e51a` |
| Evidence status | `CURRENT_EXECUTION_EVIDENCE` |
| Source provenance | `CURRENT_SOURCE` |
| Legacy parity | `MATCH` |
| Required opening-price missing rows | 0 |

Headline metrics:

| Metric | Value |
|---|---:|
| CAGR | 15.5785% |
| Max drawdown | -20.8283% |
| Sharpe | 1.064148 |
| Sortino | 1.335967 |
| Final equity | 342,336.838505 |
| Turnover | 237.534782 |

Sensitivity anchors:

| Scenario | CAGR | MaxDD | Sharpe |
|---|---:|---:|---:|
| Legacy same-close | 16.6128% | -18.8253% | 1.120566 |
| Next close | 16.7116% | -16.0547% | 1.128325 |
| Next open + 25 bps | 7.7712% | -26.3597% | 0.584938 |

Required PASS evidence:

- `building/reports/flag_sweep/baseline.json` metrics exactly equal the
  `next_open` scenario.
- `baseline_equity.json` equals the next-open curve and
  `baseline_legacy_close_equity.json` equals the legacy curve.
- The committed baseline config equals `build_config("baseline")`.
- A docs-only or tests-only commit does not stale the evidence, while a
  gate-affecting code/config commit does.
- Formal-gate variants inherit the baseline's exact start/end window.
- The one full-panel missing BTC open is unused; execution-required missing
  rows are zero.

Primary files:

- `building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json`
- `building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- `building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.json`
- `building/reports/flag_sweep/baseline.json`
- `scripts/backtest_flag_sweep.py`
- `scripts/build_current_baseline.py`
- `scripts/execution_timing_sensitivity.py`
- `scripts/formal_gate.py`
- `scripts/flag_gate.py`

### C. AAII and NAAIM failure recovery

The offline drill executes the production adapters and runner in temporary data
roots. It uses no network and must not touch live data.

The eight scenarios cover, for both AAII and NAAIM:

- primary endpoint failure;
- an older official file;
- a malformed or wrong-issue file;
- successful manual-file recovery.

Required PASS evidence:

- Failure scenarios write ledger evidence but preserve canonical bytes/date.
- Recovery scenarios advance canonical only after parsing and validation pass.
- The report states `network_used=false`, `live_data_touched=false`, and all
  eight scenarios have `passed=true`.

Evidence:

- `ops/external_source_failure_drill.py`
- `building/reports/external_sources/failure_drill_2026_07_15.json`
- `src/hermes_escape_top/tests/test_external_source_failure_drill.py`

### D. Runtime retention and deployment rollback

The weekly retention job is bounded, lock-aware, and safe around R6 releases.

Required PASS evidence:

- Dry-run is the default; deletion requires explicit `--apply`.
- Apply mode acquires the shared pipeline lock non-blocking. BUSY means zero
  deletion and a recorded BUSY result.
- `current`, `previous`, and an active score transaction are always protected.
- Only strictly named direct children of release/backup/archive/transaction
  roots are eligible.
- Deployment installs, backs up, rolls back, and reloads the retention
  LaunchAgent.
- First-install rollback succeeds when no previous retention plist existed; it
  must not attempt to bootstrap a missing plist or report a false double
  failure.

Observed read-only dry-run at handoff:

| Kind | Found | Eligible | Eligible bytes |
|---|---:|---:|---:|
| Deploy backups | 71 | 61 | 295,918,392 |
| Releases | 61 | 49 | 79,149,199 |
| Audit archives | 1 | 0 | 0 |
| Score transactions | 5 | 0 | 0 |

Protected releases were the live `current` and `previous` targets. No deletion
was performed.

Primary files:

- `ops/prune_runtime_artifacts.py`
- `ops/launchagents/com.hermes.runtime-retention.plist`
- `scripts/deploy_to_live.sh`
- `src/hermes_escape_top/tests/test_runtime_retention.py`
- `src/hermes_escape_top/tests/test_deploy_to_live.py`

### E. Percentage-change semantics and module boundary

Required PASS evidence:

- Production `pct_change` calls pass `fill_method=None`; missing prices are not
  silently forward-filled by pandas defaults.
- The AST regression test covers the production package scope.
- Market-evidence display logic is separated from request routing without
  changing dashboard behavior.

Primary files:

- `src/hermes_escape_top/core/backtest/`
- `src/hermes_escape_top/core/features/`
- `src/hermes_escape_top/core/routing/`
- `src/hermes_escape_top/web/market_evidence.py`
- `src/hermes_escape_top/tests/test_pct_change_semantics.py`
- `src/hermes_escape_top/tests/test_web_market_evidence_module.py`

### F. No unintended production behavior change

Required PASS evidence:

- No live feature flag or route is flipped by this range.
- The baseline config snapshot is evidence, not a mutation of live config.
- External failure drills and tests use isolated temporary data.
- No official run, receipt, audit record, IBKR state, or canonical live CSV is
  written by the audit commands.
- Governance reports all four checks `OK`.

## 4. Recommended audit commands

### 4.1 Repository and scope

```bash
cd /Users/liweishi/Documents/github/hermes

git status --short --branch
git log --reverse --oneline b3eea6d..2af77bb
git diff --stat b3eea6d..2af77bb
git diff --check b3eea6d..2af77bb
git diff --name-status b3eea6d..2af77bb
```

Expected worktree exceptions are only the two untracked paths stated in section
1. Any modified tracked file or additional untracked runtime artifact must be
explained before audit proceeds.

### 4.2 Focused tests

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_market_admission.py \
  src/hermes_escape_top/tests/test_decision_as_of.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_current_baseline_builder.py \
  src/hermes_escape_top/tests/test_execution_timing.py \
  src/hermes_escape_top/tests/test_execution_timing_cli.py \
  src/hermes_escape_top/tests/test_flag_sweep_cache.py \
  src/hermes_escape_top/tests/test_formal_gate_cli.py \
  src/hermes_escape_top/tests/test_external_source_failure_drill.py \
  src/hermes_escape_top/tests/test_runtime_retention.py \
  src/hermes_escape_top/tests/test_deploy_to_live.py \
  src/hermes_escape_top/tests/test_pct_change_semantics.py \
  src/hermes_escape_top/tests/test_web_market_evidence_module.py -q
```

### 4.3 Offline source drill

```bash
PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  ops/external_source_failure_drill.py \
  --output /tmp/hermes_external_source_failure_drill_audit.json
```

PASS requires top-level `status=PASS`, eight passing scenarios,
`network_used=false`, and `live_data_touched=false`.

### 4.4 Baseline internal consistency

```bash
PYTHONPATH=src:scripts \
  /Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
import hashlib
import json
from pathlib import Path

from backtest_flag_sweep import build_config

root = Path("/Users/liweishi/Documents/github/hermes")
full_path = root / "building/reports/current_baseline/CURRENT_BASELINE_FULL.json"
timing = json.loads((root / "building/reports/current_baseline/execution_timing/EXECUTION_TIMING_SENSITIVITY.json").read_text())
gate = json.loads((root / "building/reports/flag_sweep/baseline.json").read_text())
config = json.loads((root / "building/reports/current_baseline/CURRENT_BASELINE_CONFIG.json").read_text())
baseline_equity = json.loads((root / "building/reports/flag_sweep/baseline_equity.json").read_text())
legacy_equity = json.loads((root / "building/reports/flag_sweep/baseline_legacy_close_equity.json").read_text())
scenarios = {item["scenario_id"]: item for item in timing["scenarios"]}

assert hashlib.sha256(full_path.read_bytes()).hexdigest() == timing["source"]["sha256"]
assert timing["evidence_status"] == "CURRENT_EXECUTION_EVIDENCE"
assert timing["source_provenance"]["status"] == "CURRENT_SOURCE"
assert timing["legacy_source_parity"]["status"] == "MATCH"
assert timing["open_quality"]["required_missing_rows"] == 0
assert gate["metrics"] == scenarios["next_open"]["metrics"]
assert gate["turnover"] == scenarios["next_open"]["turnover"]
assert baseline_equity == scenarios["next_open"]["equity_curve"]
assert legacy_equity == scenarios["legacy_close"]["equity_curve"]
assert build_config("baseline") == config
print("BASELINE_INTERNAL_CONSISTENCY_PASS")
PY
```

Freshness against source data additionally requires a data root whose manifest
and soft-history fingerprints match the recorded values. A later live data root
may legitimately be newer. Do not call that a baseline defect without first
comparing the two recorded fingerprints.

### 4.5 Retention dry-run and static deployment checks

```bash
PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  ops/prune_runtime_artifacts.py

bash -n scripts/deploy_to_live.sh
plutil -lint ops/launchagents/com.hermes.runtime-retention.plist
```

The retention result must say `mode=DRY_RUN`. Audit fails immediately if this
command deletes anything or includes current/previous among eligible entries.

### 4.6 Governance and full suite

```bash
PYTHONPATH=src \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/check_governance_consistency.py

PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

Expected governance checks:

- `baseline_metadata=OK`
- `config_invariants=OK`
- `context_snapshot=OK`
- `flag_registry=OK`

Expected full-suite baseline: `1034 passed`.

## 5. Required audit questions

1. Can malformed or non-monotonic appended market data bypass evidence drift?
2. Can daily, Web, and CLI silently choose different implicit decision dates?
3. Can a documentation/test commit stale the baseline, or can a production-code
   commit fail to stale it?
4. Can a candidate gate use a different evaluation window from the comparator?
5. Can headline next-open evidence contain a missing opening price for a leg that
   was actually traded?
6. Can AAII/NAAIM fallback promote an older or malformed file?
7. Can a failure drill touch live canonical data or use the network unnoticed?
8. Can retention delete current, previous, an active transaction, or an
   unrecognized path?
9. Does first-install rollback work when the prior retention plist is absent?
10. Does any production `pct_change` retain implicit forward-fill semantics?
11. Did any commit in scope flip a live feature, alter readonly IBKR policy, or
    authorize a route/config change?
12. Are generated reports being mistaken for independent proof rather than
    checked against source hashes, curves, tests, and code?

## 6. PASS / FAIL policy

Mark the batch `PASS` only when all six audit areas pass, focused tests and the
full suite pass, governance is clean, baseline artifacts agree exactly, the
offline drill proves no live/network use, and retention remains a dry-run.

Any of the following is an immediate `FAIL`:

- canonical live data, an official receipt/audit, or IBKR state changes during
  the audit;
- a current/previous release appears in the retention delete plan;
- required opening-price missing rows are nonzero;
- next-open gate metrics or equity differ from the next-open scenario;
- a malformed/older source file advances canonical data;
- evidence remains `FRESH` after a gate-affecting source/config change;
- deployment logic can reach success after rollback or LaunchAgent restoration
  failure.

Non-blocking residuals must be labeled `P3` with evidence. Do not turn an
unverified assumption into `PASS`.

## 7. External auditor response format

```markdown
# External Audit Result

Verdict: PASS | FAIL
Audited range: b3eea6d..2af77bb

## Findings
- [P0/P1/P2/P3] Finding, file:line, reproduction, impact

## Six-area verdict
| Area | Verdict | Evidence |
|---|---|---|
| Market evidence/as_of | PASS/FAIL | ... |
| Baseline/provenance | PASS/FAIL | ... |
| AAII/NAAIM recovery | PASS/FAIL | ... |
| Runtime retention/deploy rollback | PASS/FAIL | ... |
| pct_change/module boundary | PASS/FAIL | ... |
| Production invariants | PASS/FAIL | ... |

## Commands and results
- Focused tests: ...
- Full suite: ...
- Governance: ...
- Baseline consistency: ...
- Failure drill: ...
- Retention dry-run: ...

## Deployment recommendation
APPROVE | BLOCK
Reason: ...
```

An approval authorizes only the next release step. It does not authorize a
feature/config flip or any order execution.
