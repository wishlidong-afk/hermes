# AAII RSS and Delayed Market Third-Source Remediation

Date: 2026-08-08

## Scope

This batch fixes two production evidence failures without changing scoring,
routing, feature flags, canonical market-admission policy, or official-run
semantics:

1. AAII Insights RSS changed from a labeled result block to narrative
   paragraphs. The old parser ignored the newer official issue.
2. Alpha Vantage did not yet expose the latest US daily bar at 07:10, but did
   expose it later in the morning. The existing one-shot third-source shadow
   therefore remained `UNAVAILABLE` for the whole day.

No official daily was run during implementation or verification.

## Implementation

### AAII

- `parse_aaii_insights_feed` retains the legacy labeled parser.
- It now also parses the official narrative form for bullish, neutral, and
  bearish sentiment.
- Extraction is bounded at the next sentiment paragraph and before historical
  averages; the existing three-share sum validation still applies.

### Delayed market evidence

- `com.hermes.market-third-source` runs at 09:02 CST.
- The managed-runtime entry retries only the latest market-admission
  third-source shadow under the shared `.pipeline.lock`.
- It never writes canonical history, market admission, scores, receipts,
  official audit rows, or `input_hash`.
- A matching `OK` shadow skips the network call.
- Lock contention returns exit code 75 with `BUSY` and performs no write.
- 8766 accepts the delayed shadow only when all of these match:
  - schema `hermes-market-admission-third-source-shadow-v1`;
  - `research_only=true`;
  - exact `admission_operation_id`;
  - exact `completed_through`.

### Operations

- R6 deploy now installs, backs up, reloads, and exactly restores both the new
  wrapper and LaunchAgent.
- Failure injection covers first install, reload failure, normal switch, and
  rollback.
- The existing Codex morning-acceptance heartbeat was moved in place from
  09:05 to 09:10, after the 09:00 watchdog and 09:02 evidence retry. No duplicate
  automation was created.

## Verification

| Check | Result |
|---|---|
| Focused AAII / third-source / Web / ops / deploy suites | 102 passed before final schema hardening; final affected suites 27 passed |
| Deploy failure-injection suite | 29 passed |
| Offline external-source failure drill | PASS, 13/13, `network_used=false`, `live_data_touched=false` |
| Full suite on final diff | 1238 passed in 113.57s |
| Governance | 7/7 OK |
| Four-date payload and seven-artifact persistence equivalence | `all_equal=true` |
| Python compile | PASS |
| Shell syntax | PASS |
| LaunchAgent plist | PASS |
| `git diff --check` | PASS |

Equivalence evidence:

`building/reports/data_quality/AAII_MARKET_THIRD_SOURCE_EQUIVALENCE_2026_08_08.json`

The four dates are 2022-06-30, 2024-06-28, 2026-05-29, and 2026-07-10. Their
payloads, statuses, `input_hash` values, and seven persisted business artifacts
are equal between repository `HEAD` and this working tree.

## Isolated Real-Network Canaries

No live data was written.

- Current AAII official Insights RSS parsed four issues. The latest available
  RSS issue was reported 2026-07-29, published 2026-08-01, with
  bull/neutral/bear `31.0% / 26.9% / 42.1%`.
- A temporary copy of the current live admission operation
  `34fd049ffb244a7082e3bcfbc193affe` completed through 2026-08-07 returned
  `status=OK` for BRK.B 2026-08-07 with `third_source_support=ALPACA_WITNESS`.

## Deliberate Safety Boundary

The delayed third source is evidence, not an automatic tie-breaker. A genuine
Yahoo/Alpaca admission mismatch remains fail closed even when Alpha Vantage
supports one side. Morning acceptance may therefore still report a strategy
failure until a separately reviewed admission-policy change or a naturally
matching session resolves it. This batch improves automation and explanation;
it does not turn disagreement green.

## Release State

The repository working tree contains the reviewed implementation but live still
runs the prior release. Commit, push, and R6 deployment should occur only after
an independent diff review. Deployment must preserve live config and must not
run an extra official daily.

The local managed Python does not have `ruff` installed, so no Ruff command was
claimed. Compile, focused tests, full tests, governance, failure drill, and
behavior/persistence equivalence are all green.
