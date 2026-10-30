# Daily Failure Evidence Remediation

Date: 2026-10-23. Local implementation and validation completed; independent review pending. **DEPLOY HOLD. This is not A2 closure.**

## 1. Isolated Scope

The candidate is an independent local clone at:

`/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23`

Branch: `codex/daily-failure-evidence`. Base: live release commit `2db0cdc562309b6222a69aaee8dbdaf51c763b93`, not the main directory's unpublished A2 candidate. Its origin is a local repository path, not GitHub. Do not push it to that origin as a publication shortcut.

Only one production file changes: `src/hermes_escape_top/scripts/run_daily_package.py` (8 additions, 1 deletion). One new test file adds 9 cases. There are no threshold, admission, scoring, routing, identity, revision, config, flag or dependency changes.

The main Hermes directory and its frozen A2 3C-5h A packet were not edited. Thirteen implementation/dependency bindings and the packet manifest digest still match their recorded values. No staging, commit, push, deployment, official daily, market/external refresh or IBKR operation was performed. Local clone and branch setup are not a deployment or a GitHub publication.

## 2. Implemented Behaviors

1. Set `context["step"] = "run_receipt"` before final receipt validation. A successful auxiliary flow step is no longer blamed for a subsequent end-state failure.
2. Retain only this invocation's returned scoring payload. After writing a FAILED receipt, attempt to write the existing health JSON/Markdown and per-run archive with that same payload and receipt.
3. Keep FAILED and the original exception. Report-writing failure is logged and cannot replace the primary failure or turn it into success.
4. If the scoring call has not returned its payload, or the FAILED receipt cannot be written, do not fabricate a bound report from a previous run or a synthetic input hash. Shadow/manual failures do not publish official evidence.

This fixes the observed post-scoring SOXL freshness failure chain. It does **not** promise a complete bound health report for every early failure: without a returned current payload, that evidence is unavailable. It does not rerun scoring or retry market requests.

The successful daily path and the health writer's existing archive/alias behavior remain unchanged. Report writes are not a newly atomic four-file transaction or a power-loss durability guarantee.

## 3. Verification

Two RED/GREEN steps were executed independently:

- The first regression failed with `alpaca_flow` instead of `run_receipt`; after the step-label change, it and the existing receipt file passed: 26 tests.
- The next regression reproduced the unchanged old OK health report. After the failure-report change, the current input/decision/date, FAILED receipt, CRITICAL health and dated archive all matched. Explicit and implicit decision dates are covered.

Final results:

| Check | Observed result |
|---|---|
| New failure-evidence file | 9 cases, all included in the runs below |
| New tests + receipt writer + health truth | 75 passed |
| Full suite on the live-based candidate | 1490 passed in 152.02s |
| Governance | 8/8 OK; ibkr_readonly=true |
| New test file full Ruff | PASS |
| Whole production/scripts/ops severe Ruff | PASS: E9,F63,F7,F82 |
| Exact four-module CI mypy scope | PASS |
| Compile / diff whitespace / installed-environment pip check | PASS |
| Four-date pipeline comparison | strict all_equal=true; 4/4 empty strict_differences |
| Locked-dependency vulnerability audit | **FAIL: four advisories in two packages; see section 4** |

The four dates are 2022-01-03, 2022-01-25, 2026-05-29 and 2026-06-04. A fresh `git archive 2db0cdc` provided the baseline and tracked-data seed. The unchanged comparator checks pipeline payloads and seven business artifacts; it does not exercise daily-wrapper failure finalization. That behavior is covered by the new orchestration regressions with real receipt/health writers, isolated scoring/flow inputs and prohibited network sockets.

Scoring logic fingerprint was independently calculated for baseline and candidate; both are:

`42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`

The wrapper is outside that fingerprint's scoring scope. This is not evidence for A2's different `ac025f0f...` fingerprint migration or rollback.

Runtime used: `/tmp/hermes-a2-publication-reader.hZW9jU/venv/bin/python`, Python 3.11.15; pytest 9.1.1; Ruff 0.15.22; mypy 2.3.0; NumPy 2.0.2; pandas 2.3.3; SciPy 1.13.1. Synthetic FRED key and isolated test roots were used. This reused environment has urllib3 2.8.0 and certifi 2026.4.22; it was **not** rebuilt from the live base's old lock and is not a hermetic archived runtime. No cloud CI result is claimed.

## 4. Security Gate Remains Red

The unmodified live-base lock contains urllib3 2.7.0 and certifi 2026.4.22. The actual locked-requirements audit returned exit 1:

- urllib3: PYSEC-2026-4175, PYSEC-2026-4176, PYSEC-2026-4177; reported fixed version 2.8.0. The main A2 directory already has that reviewed lock update, but it was not imported into this isolated incident patch.
- certifi: PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2; reported fixed version 2026.10.19. The main A2 lock also still pins 2026.4.22. This advisory was published on 2026-10-20, after older dependency checks; those historical passes do not clear the current finding.

Primary maintainer advisory: <https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2>. Current OSV record: <https://osv.dev/vulnerability/PYSEC-2026-4320>. The maintainer's initial patched-version field lists 2026.10.18; the updated OSV record recommends 2026.10.19, restoring unaffected roots. Preserve that distinction when choosing the security update.

This audit scanned requirement pins, not the running live interpreter or its TLS routing; it is not proof of exploitation or of the installed live package versions. Do not bypass certificate verification. Prepare the dependency security update as a separately reviewable change, validate its locked installation, then retest the intended release combination before deployment.

## 5. Byte Bindings

| Artifact | SHA256 |
|---|---|
| run_daily_package.py | abb69acb5778c20159844863d6fb94499794bde31f85f4de124b43d59191315b |
| test_daily_failure_evidence.py | 362b877b028a14a0da2d3baa75ec9e94e645141b4146fa4ec23b14af52976a26 |
| Unchanged comparator | 19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d |
| building/reports/daily_failure_remediation/2026-10-23/equivalence.json | 7df7bfe8c45f024e0be2418af15f88a655e29b71f36a3229bfa77b70002c55fa |

These are local reproduction bindings, not an independent audit verdict or signatures. The original live evidence files and A2 frozen reports were not rewritten to make the results pass.

## 6. Remaining Work and Completion Meaning

There is no defensible single percentage for project completion. Two incident fixes are implemented here, while release, upstream-source behavior and the A2 program have different completion criteria:

1. **Incident follow-ups:** show one unique conflict versus three attempts without changing raw ledger counts; evaluate a backup candidate path offline. No majority-vote canonical promotion, threshold relaxation or claim that the original SOXL high was repaired.
2. **A2 engineering:** independently review frozen 3C-5h A; then build the separate read-only official receipt/audit/run adapter, complete automatic T1-to-T2 replay and the remaining runtime reproducibility/declared durability coverage. Reuse unchanged, already reviewed legacy/ON/SIGKILL evidence instead of repeating whole audits.
3. **A1 compatibility:** demonstrate migration/repeated certification/budget rejection/old-writer rollback for the actual intended A2 fingerprint. The unchanged incident-patch fingerprint does not close that separate gate.
4. **Release gate:** fix current security findings, assemble explicitly reviewed changes, run combination CI/governance, obtain deployment authorization, preserve live config and perform one R6 outside the writer window. Do not silently integrate the incident patch into frozen A2 sources.
5. **Natural observation:** use scheduled runs, watchdog and acceptance; at least five distinct trading days plus the required weekend/Monday identity boundaries. Do not count repeated weekend as_of values or manual reruns as extra sessions. Recovery PASS alone is not proof of a source fix or A2 closure.

The next recommended implementation is the small, separately validated security dependency update, followed by unique-conflict presentation. The A2 external review can proceed using its unchanged frozen packet. New factors, strategy experiments and unrelated WebUI work remain paused.

## 7. Minimal Reproduction Commands

Run from this isolated candidate, not the live installation. Let `PY` be the interpreter recorded in section 3; set `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPATH=src`, and a synthetic FRED_API_KEY.

```sh
"$PY" -m pytest src/hermes_escape_top/tests/test_daily_failure_evidence.py src/hermes_escape_top/tests/test_run_receipt_writer.py src/hermes_escape_top/tests/test_health_truth.py -q -p no:cacheprovider
"$PY" -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider
"$PY" scripts/check_governance_consistency.py
"$PY" -m ruff check src/hermes_escape_top/tests/test_daily_failure_evidence.py
"$PY" -m ruff check src scripts ops --select E9,F63,F7,F82
"$PY" -m pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off
```

The last command is expected to remain red until a separate dependency update is applied. Do not describe it as a passed release gate.
