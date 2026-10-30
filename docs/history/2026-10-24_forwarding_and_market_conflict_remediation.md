# Forwarding Readiness and Market Conflict Reporting

Date: 2026-10-24. **Forwarder instructions updated; candidate code locally verified but NOT DEPLOYED. FNGU source disagreement remains unresolved. A2 OPEN; Phase B not started.**

## 1. Two Separate Changes

| Surface | Change | Current state |
|---|---|---|
| App automation `hermes-2` | Wait for a ready report pair before forwarding | Saved and read back; next natural invocation not yet observed |
| Isolated candidate `web/health.py` | Separate unique rejection identities from repeated comparisons | Local tests pass; independent review and deployment pending |

The independent generator remains a cron task scheduled at 09:10 Beijing time. Forwarding remains attached to this conversation at its existing 09:15 schedule. Neither schedule, task kind nor target changed. The main cron configuration hash is unchanged. No heartbeat was given permission to generate acceptance reports.

The code candidate remains at `/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23`, branch `codex/daily-failure-evidence`, based on live commit `2db0cdc562309b6222a69aaee8dbdaf51c763b93`. The main A2 working directory and live were not edited. No stage, commit, push, R6, official daily, financial-source refresh or real IBKR connection was performed.

## 2. Forwarding State Rules

The earlier instructions allowed a one-shot missing-file notification. The saved instructions now require:

1. Check both files for today's Beijing date, matching acceptance_date, timezone-aware generated_at and consistent JSON/Markdown evidence. Planned trigger minutes and mtime are not validity gates.
2. If the pair is not ready, inspect the actual main task for today and use available waiting tools. If it has not appeared, recheck the readiness condition about every 30 seconds, without busy polling. Maximum wait is 10 minutes from the forwarding invocation.
3. Forward a valid FAIL immediately, including a main command exit of 2. Never wait for a PASS result.
4. If the main task has clearly ended without reports, preserve the execution error and report the missing/damaged artifacts immediately. If the deadline expires while readiness is unresolved, report that state rather than inventing a missed run or a strategy failure.
5. Do not run acceptance generation, daily, market/external refresh, IBKR operations or live repairs.

Readback confirms the exact prompt SHA256:

`08645d9bf5fd1c570d45c499ab69c1971d9e2048edc225db7ec8d430341cdad3`

The observed 10-24 forwarding trigger was 09:11:30.963 and the report was generated at 09:13:12, a 101.037-second gap. Today's JSON exactly matches the existing generator's pure Markdown renderer and remains FAIL. The gap fits the configured budget, but this check is **not** proof that a future model-driven forwarding invocation has executed the new waiting behavior. It also does not fix app scheduler timing or a task that never starts. Natural observation remains required.

## 3. Display-Only Deduplication

Incremental code scope: one production file `src/hermes_escape_top/web/health.py` and new `src/hermes_escape_top/tests/test_market_conflict_counts.py`.

The diagnostic key is exactly `(symbol, date, status, candidate_sha256, witness_sha256)` within the current admission payload. It counts rejected, blocking comparison rows, not HTTP requests or a persistent cross-run incident history. Nonempty string identity fields, lowercase 64-character SHA256 strings and reconciliation with the original integer rejected_rows are required. These checks do not independently authenticate the supplied hashes or replace admission validation.

- Three identical identities: `rejected=3 unique_conflicts=1 attempts=3`.
- Different symbol/date/status/candidate/witness: keep distinct identities.
- Missing/malformed identity: unique_conflicts=UNKNOWN; count attempts only when rows reconcile.
- Missing or inconsistent row counts: both derived counts UNKNOWN.
- Admitted rows and nonblocking deferred BTC rows do not count as rejection attempts.

Original admission rows, rejection counts, classification, thresholds, canonical data and scoring inputs are not changed. Strategy-blocking rejections stay strategy-blocking. Component-only rejections retain their existing auxiliary classification.

## 4. Tests and Bindings

The first regression failed because only `rejected=3` was rendered. After the display change:

| Check | Result |
|---|---|
| New collected cases | 23 |
| New cases plus existing health truth tests | 64 passed in 1.48s |
| Full combined candidate suite | 1513 passed in 152.21s |
| Governance | 8/8 OK; ibkr_readonly=true |
| Changed health/test files full Ruff | PASS |
| Whole production/scripts/ops severe Ruff | PASS |
| Exact four-module CI mypy | PASS |
| Changed-file compilation / whitespace | PASS |
| New four-date pipeline comparison | strict all_equal=true, 4/4 empty strict_differences |

The old 1490-case security packet stays frozen; this count adds 23 tests, not a rewritten historical result. The new comparison binds the current health/test bytes, but its scope remains pipeline payload and seven business artifacts, not health text equivalence. New public compute_health tests cover the intentional diagnostic changes.

The scoring fingerprint remains `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`; web code is outside that unchanged fingerprint definition. Seven core admission/witness/identity/config/pipeline files match the live-base commit exactly. No fingerprint exclusion, budget, route or flag changed.

| Current file | SHA256 |
|---|---|
| web/health.py | 211e9ffd327060221c7dd95555a1a662732b8b79577d4f02e839cff7718f57d7 |
| tests/test_market_conflict_counts.py | 5473f758d086d1668706181bf91a0c36f407d0df526ed48a31722fe955be9375 |

Evidence: `building/reports/market_conflict_reporting/2026-10-24/`, nine files including SHA256SUMS.json. Its manifest SHA256 is `cbf6118cbf1f1ff8f6edfe86d0c579ecb6328a086f384bd24db89e38511bbd99`.

The prior 19-file dependency packet was checked against its unchanged manifest, and 13 main A2 source/dependency bindings plus that packet's manifest still match. Previous receipt, dependency and A2 evidence is historical proof for its own byte state, not automatic approval of this new health change. No cloud CI or independent audit PASS is claimed.

## 5. FNGU Offline Investigation

Only already-saved 10-24 admission, matching third-source shadow and receipt files were read. Their hashes were bound and rechecked unchanged. No quote API was called. The diagnostic output is explicitly not an official health report and contains selected public bar observations, not account data, broker tapes or databases.

For the 10-23 FNGU bar:

| Pair | Recomputed volume difference | Price status | Existing policy result |
|---|---:|---|---|
| Yahoo 1,504,770 vs Alpaca 2,009,902 | 25.1322% | MATCH | VOLUME_MISMATCH |
| Yahoo vs third source 1,001,177 | 50.3001% | MATCH | VOLUME_MISMATCH |
| Alpaca vs third source | 100.7539% | MATCH | VOLUME_MISMATCH |

Existing comparison code and independent Decimal arithmetic agree. All three pairings remain outside policy; the research-only third source still says NEITHER_WITHIN_POLICY. Candidate canonical promotion is not authorized.

The saved preceding FNGU session comparisons report volume differences of 0.0078%, 0.0087%, 0.0046% and 0.0064% for 10-19 through 10-22. Those are recorded metrics, not independently reconstructed prior raw bars. The large latest-day-only change makes publication/update timing worth investigating; it does not prove a particular vendor is wrong.

[Alpaca's aggregation documentation](https://docs.alpaca.markets/us/docs/market-data-faq) distinguishes price and volume updates by trade conditions; some extended-hours trades can update daily volume without changing daily OHLC. Its saved witness was fetched at 19:10:05 New York time. Neither that timestamp nor matching prices establishes a finalized, same-session volume definition across vendors. [Alpha Vantage's daily documentation](https://www.alphavantage.co/documentation/#daily) describes raw daily OHLCV, not a certification that these three observations have identical filtering/finality.

The unresolved evidence is same-session coverage, trade-condition treatment and publisher finalization/correction timing. A future narrowly scoped shadow collection of per-session minute evidence may distinguish them; this increment does not add or activate such collection. Do not relax the 25% ceiling or select a majority to remove the red status.

## 6. What Is and Is Not Fixed

The forwarder readiness rule is saved. The isolated candidate now includes the earlier failed-receipt/health fix, the security dependency update and this clearer conflict display. Local verification is complete for this increment; the refreshed evidence does not replace independent review.

The actual live version is still unchanged. Its current FNGU isolation is real and remains unresolved; an offline preview with the updated renderer remains CRITICAL while explaining one unique conflict and three attempts. The next natural forwarding invocation and any future live code release must be observed separately. No claim of repaired market data, A1/A2 closure or Phase B authorization follows from these tests.
