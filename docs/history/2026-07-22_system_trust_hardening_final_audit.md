# Hermes System Trust Hardening Final Audit

Date: 2026-07-22
Branch: `hermes-docs`
Code review range: `origin/hermes-docs..b78e13e`
Deployment performed: **No**

## Executive Decision

- **Implementation:** PASS after independent-review remediation.
- **Strategy experiments:** route transition and C/D trend ownership are both
  REJECTED and remain OFF. This work authorizes no feature or route flip.
- **Repository:** APPROVE an explicit evidence/docs commit and human-reviewed
  push.
- **Live:** HOLD deployment while the latest strategy-data admission remains
  blocked by the `SHV` volume witness mismatch.

The earlier draft PASS was withdrawn when independent review found additional
defects. This document replaces that draft and records the fixes and fresh
verification rather than treating the first self-review as proof.

## Safety Boundaries

1. No live/shared data was written, no live IBKR connection was made, and no
   deployment or push occurred.
2. Full-window work used `/tmp/hermes-cd-gate.uUwtWC` through
   `HERMES_DATA_DIR`; processes ran one at a time.
3. The approved live config was read only and validated against
   `approved_live_config.json` before replay.
4. `ibkr.readonly=true`, default-OFF candidates, and the no-order-path
   invariant were preserved.

## Independent Review Remediation

| Severity | Finding | Resolution | Commit |
|---|---|---|---|
| P1 | Deploy could mix a captured HEAD with later worktree changes | Validate the complete managed source tree, policy, config, ops and untracked Python files before stop and again under the deployment lock | `9f958ce` |
| P1 | Auxiliary writers could run before recovery of an incomplete score transaction | Recover under the shared lease at Web refresh, confirmation, live-check and daily boundaries | `7cbd20c` |
| P2 | Morning acceptance could accept a release without policy-bound attestation | Missing policy/validator or non-v2 attestation now fails closed | `d240a2d` |
| P2 | Legacy top-level provenance could promote fallback data without a recorded primary failure | All legacy provenance now passes through the same primary/fallback validator | `4eebcc8` |
| P2 | History transaction identifiers allowed unsafe path forms | Restrict IDs to `[A-Za-z0-9][A-Za-z0-9_-]{0,127}` and reject empty/dot/traversal forms | `552b947` |
| P2 | History recovery happened after admission/witness preparation | Recover pending history transactions before any network preparation | `d2a49b8` |
| P2 | Baseline normalized config did not retain proof of the approved raw live config | Persist raw-live, policy and normalized semantic hashes plus a reversible normalization map; governance independently verifies all links | `b78e13e` |
| P3 | Timing report pointed to an absolute raw JSON that is intentionally deleted | Point to repo-relative `CURRENT_BASELINE_FULL.json.gz` and declare SHA scope as the decompressed JSON payload | `b78e13e` |
| P3 | The first audit draft claimed PASS before incorporating external findings | Withdrawn and replaced by this post-remediation report | this evidence commit |

Each code defect was reproduced with a failing regression test before the
minimal fix. Focused tests were rerun after each change. The old artifacts then
failed governance as intended until a clean, committed-source rebuild replaced
them.

## Original Seven Tasks

| Task | Final status | Evidence |
|---|---|---|
| Approved live-config policy | PASS | Semantic policy, exact approved diff, readonly invariant and policy-bound attestation |
| Seven-artifact score transaction | PASS | Transaction recovery covers scoring plus auxiliary state across all write entries |
| Source role and provenance | PASS | Strategy/hard-gate/auxiliary/research roles and fallback provenance are explicit |
| Recoverable history promotion | PASS | Staging, backup, ordered promotion, commit and pre-network startup recovery |
| Route-set transition candidate | REJECTED/OFF | Complete no-op; no retuning or second gate |
| C/D trend ownership candidate | REJECTED/OFF | Negative OOS delta and failed PBO criteria; no retuning |
| Maintenance and CI | PASS | Retired endpoints tombstoned, writes atomic, minimal CI and current docs |

## Current Baseline Evidence

| Field | Value |
|---|---|
| Gate-code commit | `b78e13e21b57e3b9553ab6ec86f320c613d5337b` |
| Requested/effective window | 2018-01-01..2026-07-17 / 2018-01-02..2026-07-17 |
| Trading days | 2,146 |
| Equity timing/status | `next_open` / `CURRENT_EXECUTION_EVIDENCE` |
| History manifest | `ea882f4bc91aaa91ab9f222f08c21f650a1282744cbb20e0e4e8122736cd7f9f` |
| Full-source payload SHA256 | `36183fceecae60fffc35d53a171d312d88e15520d45104c4b16e551565262a20` |
| Approved live semantic SHA256 | `c6060e55825f85462e2a8d567d8a6c2b20a771c40884ea721b8f23f730b704f9` |
| Policy SHA256 | `8152c0d1a4adce45caceb413f9182f0de0b95918e70007b8140d16e9712a0aeb` |
| Normalized config semantic SHA256 | `e528980ae9d029c50bde7536e9db427b211137ed887d594cbd510f7add49c82a` |

The deterministic gzip has `mtime=0`; its decompressed bytes match the source
SHA. The raw JSON used for repricing was deleted afterward, and governance
still passed, proving retained evidence does not depend on that temporary file.

| Scenario | CAGR | MaxDD | Sharpe | Sortino | Final value |
|---|---:|---:|---:|---:|---:|
| next open | 15.46% | -20.83% | 1.058 | 1.329 | $340,054 |
| legacy close | 16.49% | -18.83% | 1.114 | 1.435 | $366,178 |
| next close | 16.55% | -16.05% | 1.119 | 1.457 | $368,296 |
| next open + 25 bps | 7.66% | -26.36% | 0.578 | 0.721 | $187,475 |

Execution-required opens are complete: 10,045 rows, zero missing. Total
turnover is `237.927274`; route-set changes contribute `166.588574`
(`70.0166%`). Attribution reconciles exactly.

## Verification

- Full suite: `1172 passed / 0 failed` in 138.04 seconds.
- Governance: 6/6 OK.
- Baseline consistency: `BASELINE_INTERNAL_CONSISTENCY_PASS`.
- Baseline freshness: `FRESH`, zero mismatches.
- External-source failure drill: 8/8 PASS, `network_used=false`,
  `live_data_touched=false`.
- Runtime retention: `DRY_RUN`; current `e266ac7` and previous `cf7e1a1` are
  protected; score-transaction deletions are zero.
- Python compilation passed.
- Shell syntax: 15/15 passed.
- Launchd plist lint: 5/5 passed.
- CI workflow YAML: 1/1 parsed.
- The gzip source, timing SHA, next-open gate metrics/equity, legacy shadow,
  cost curve and route-set turnover were cross-checked from underlying JSON.

## Live Read-Only Evidence

At final review, live VERSION is `e266ac7 20260720_144956`; 8766 returns HTTP
200 and `/health` returns `{"ok":true}`. The latest market-admission evidence
was generated at `2026-07-21T23:10:06Z`:

- 127 rows admitted, one deferred, one rejected, no fetch error.
- `BTC-USD 2026-07-21` is `DEFERRED_UNFINALIZED`, expected and nonblocking.
- `SHV 2026-07-21` is `VOLUME_MISMATCH`: OHLC difference is zero but raw
  volume differs by `36.0426%`, above the 25% policy. It remains blocking.

No refresh or repair was run. Do not whitelist this row or change the threshold
without a separately reviewed, multi-day source-policy study.

## Residual Risks

1. The two rejected candidate implementations remain parked behind OFF flags.
2. Opening-price evidence still includes 2,182 explicitly modeled full-panel
   rows, although execution-required missing rows are zero.
3. Raw-volume comparison across providers can produce operational false
   positives for cash-like ETFs; fail-closed is intentional until supported by
   broader evidence.
4. The branch is 19 commits ahead of origin before the final evidence commit.
   Push and deploy remain separate approvals.

## Recommendation

Commit the explicit evidence bundle and submit it for review. Push may follow
human acceptance. Do not deploy while the strategy-data admission remains
blocked; obtain a later certified admission or a separately approved source
policy decision first.
