# Yahoo + Alpaca canonical market admission gate

Date: 2026-07-14 (Asia/Shanghai)

## Scope

`features.use_market_admission_gate` is default OFF. When enabled, every new or
repair-window Yahoo row for an Alpaca-supported U.S. equity or ETF must match an
Alpaca SIP raw daily bar before it can enter canonical `data/history/*.csv`.
Indices and crypto are explicitly out of scope; their independent official
witnesses are tracked separately.

Admission is fail closed:

- all raw OHLC fields must be comparable and remain within 1%;
- raw volume must be comparable and remain within 25%;
- a missing witness, authentication/network failure, or mismatch freezes the
  candidate row and preserves the previously certified canonical data;
- a backfill execution failure writes `status=ERROR` evidence before the
  original exception propagates, and all canonical files touched by that call
  are rolled back byte-for-byte if execution or evidence persistence fails;
- candidates outside the fetched witness window or later than the latest
  completed U.S. regular session are rejected;
- batch refresh and self-heal reuse one operation id and cumulative session, so
  a retry cannot overwrite an earlier quarantine with an empty OK;
- each evidence record binds the admitted candidate and Alpaca witness hashes,
  plus the post-write SHA256 of every canonical file touched by the operation;
- 8766 reports fetch, quarantine, and execution failures as strategy-data
  degradation rather than silently presenting a green gate. It rejects stale
  operation evidence and escalates canonical hash drift to CRITICAL.

Evidence is atomically written to `market_admission_latest.json` and a dated
file whose day is derived in the Shanghai operating timezone.

## Verification

- Focused admission/backfill/health/daily/persistence tests: 129 passed.
- Full suite: 914 passed.
- Governance consistency: 4/4 OK.
- `compileall` and `git diff --check`: OK.
- OFF-state replay: four historical dates have byte-identical payloads and six
  persistence artifacts. See
  `building/reports/data_quality/market_admission_off_byte_identical_2026_07_14.json`.
- Isolated real-network canary using production `/usr/bin/python3`: 91 candidate
  rows inspected, 74 supported U.S. rows MATCH, 17 unsupported rows marked
  NOT_APPLICABLE, 0 rejected, fetch/run error null. All 45 canonical files were
  SHA-bound and the production validator returned OK. The canary used an
  isolated data root and did not write live canonical history.
- Four independent read-only review passes reproduced and then closed the
  health, self-heal, rollback, PIT, history-head, OFF-path, pagination, and
  same-day operation-binding counterexamples. Final activation blockers: zero.

## Activation rule

Deploy the default-OFF code first. Only after VERSION, 8766, and deployment
verification pass may the live runtime config flip this single flag to true
under `.pipeline.lock`. The flip must preserve all other live config values and
must not trigger an official daily run. A subsequent scheduled run supplies the
first production admission evidence.

## Live activation

- Code release: `e98b5d9_20260714_121821`; R6 smoke and `verify_live` passed.
- The shared live config changed only `features.use_market_admission_gate` from
  absent/false to true under `.pipeline.lock`; repo default remains false.
- Before the flip, live canonical history was certified read-only against
  Alpaca SIP for the completed 2026-07-13 session. Operation
  `c192975dd63c478a904b21c152108a1c` produced 148 MATCH rows, 34
  NOT_APPLICABLE rows, zero rejects, and SHA bindings for all 45 canonical
  files.
- Post-activation validation returned OK and `/api/health_status` reported
  strategy data OK. The scheduled receipt and audit log mtime/size were
  unchanged, proving activation did not run daily or create another official
  record.
