# Current Baseline Rebuild Handoff

Date: 2026-07-22
Branch: `hermes-docs`
Repository HEAD used for the run: `eeb80a28348ee6594d3532b4a456be05034d4eda`
Gate-code provenance commit: `b23cf124b5b906d897884f2774d354b8cae23d1a`
Deployment performed: **No**

## Decision

- Baseline rebuild: **PASS**.
- Execution-timing and cost derivatives: **PASS**.
- Governance and tests: **PASS**.
- Commit/push: **APPROVED by independent read-only review**.
- Live deployment: **HOLD** while market admission remains blocked by SHV
  volume witness evidence.
- Authorization: `NO_CONFIG_FLIP`.

The provenance commit is intentionally the latest commit touching gate-affecting
code or repository config, not the repository HEAD. The later `eeb80a2` commit
changes test-data isolation only and therefore does not stale the comparator.

## Isolated Run

The effective live config was read from:

`~/.hermes/skills/investment/escape-top/shared/hermes_escape_top/config/config.json`

History, soft history, and archive data were copied to an APFS-backed temporary
root. Active/archived audit logs and `.pipeline.lock` were excluded. File-level
comparison confirmed the history and soft-history copies matched live before the
run. `HERMES_DATA_DIR` resolved history, soft-history, and archive paths only to
that temporary root. No live/shared file was written and no IBKR connection was
made.

Only one full-window process ran:

```bash
HERMES_DATA_DIR=<isolated-root> \
PYTHONPATH=src:scripts \
/Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/build_current_baseline.py \
  --config ~/.hermes/skills/investment/escape-top/shared/hermes_escape_top/config/config.json \
  --start 2018-01-01 \
  --end 2026-07-21
```

The raw JSON was retained in the temporary evidence root after repricing. The
repository retains the deterministic gzip (`mtime=0`), whose decompressed bytes
have SHA256:

`84ba67caee68c090a15b48821aa49cdfdfff45dc882cea811681a8446dd2ed3e`

## Current Headline

| Scenario | CAGR | MaxDD | Sharpe | Sortino | Final value |
|---|---:|---:|---:|---:|---:|
| next_open | 15.56% | -20.83% | 1.064 | 1.335 | $342,742 |
| legacy_close | 16.52% | -18.83% | 1.116 | 1.438 | $367,570 |
| next_close | 16.69% | -16.05% | 1.128 | 1.468 | $372,483 |
| next_open + 25 bps | 7.75% | -26.36% | 0.584 | 0.728 | $188,893 |

- Requested/effective window: `2018-01-01..2026-07-21` /
  `2018-01-02..2026-07-21`.
- Effective trading days: 2,148.
- History manifest:
  `cf06acc7c2454c6fbbb7038f9ae8e56a6fa50ada5dd36a19e219ecec0f21b8e2`.
- Soft-history SHA256:
  `837dab78e922cea360c2da8e769163733507fed579920a07ab4051c578de5721`.
- Execution-required opens: 10,053; missing: 0; modeled: 1,343
  (13.3592%, below the 15% ceiling).
- Full-panel opens: one unused BTC-USD row is missing and remains visible.
- Total next-open turnover: `238.0632`.
- Pre-registered route-set turnover: `103.466858` across 162 events.

## Derivative Equivalence

Independent assertions passed for all of the following:

1. Decompressed gzip bytes equal the generated raw JSON bytes.
2. Timing source SHA equals the raw payload SHA.
3. Timing status is `CURRENT_EXECUTION_EVIDENCE`, source provenance is
   `CURRENT_SOURCE`, and legacy parity is `MATCH`.
4. Gate metrics and turnover equal the `next_open` scenario.
5. `baseline_equity.json` equals the `next_open` equity curve.
6. `baseline_legacy_close_equity.json` equals the `legacy_close` curve.
7. Cost 0 bps equals `next_open`; cost 25 bps equals `next_open_stress`.
8. Turnover attribution reconciles by leg and mechanism.
9. `build_config("baseline")` equals the retained config snapshot.
10. Recomputed freshness is `FRESH` with zero mismatches across all 13 cache
    evidence fields.

## Verification

- Focused baseline/timing/cost/governance/formal-gate tests: `65 passed`.
- Full suite: `1188 passed` in 114.99 seconds.
- Governance: `7/7 OK`.
- Baseline internal consistency: `PASS`.
- Baseline freshness: `FRESH`, zero mismatches.
- `git diff --check`: `PASS`.

Independent review found no P0/P1/P2 issue and approved commit/push while
holding deployment. Three documentation-only P3 observations were closed
before integration: the current test count is 1,188; the pre-registered
route-set turnover definition is now explicit and distinguished from the cost
report's broader attribution; and the historical
`CURRENT_BASELINE_EQUITY.json` filename is explicitly labeled as the
legacy-close source curve rather than the formal gate curve.

## Live Hold

The live release remains `e266ac7 20260720_144956`. Its old server does not yet
provide `/livez` or `/readyz`, so both return 404 until a later approved deploy.
The dashboard root remains HTTP 200.

The latest market-admission artifact remains `BLOCKED`:

- `SHV 2026-07-21`: OHLC difference `0.0%`, raw-volume difference `36.0426%`;
- policy ceiling: `25%`;
- action: candidate isolated, certified canonical retained;
- no threshold relaxation or whitelist was applied.

Historical admission artifacts show prior SHV rows normally reconverged below
1% after a later vendor refresh. This supports waiting for a certified rerun
rather than changing policy from one observation. Deployment remains blocked
until market admission is clear or a separately reviewed multi-day policy study
authorizes a change.

## Review Checklist

1. Confirm the diff contains only the 13 rebuilt baseline/current-doc files plus
   this handoff, with no config, flag, routing, order, or live data change.
2. Recompute gzip decompressed SHA and compare it with timing and cost sources.
3. Re-run baseline internal equivalence and freshness against an isolated clone
   of the same data snapshot.
4. Confirm required missing opens are zero and modeled required share is at most
   15%.
5. Confirm governance remains 7/7 and the full suite remains green.
6. Treat the SHV admission block independently from baseline validity; do not
   weaken the volume threshold as part of this evidence commit.
