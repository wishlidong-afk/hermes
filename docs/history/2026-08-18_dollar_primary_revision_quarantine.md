# Dollar Primary Revision Quarantine - 2026-08-18

## Incident

The 2026-08-18 natural 07:10 run completed its receipt, audit, and seven-artifact
transaction, but strategy readiness failed closed:

```text
dollar: VALIDATION_ERROR history continuity: changed certified FRED row 2026-08-03
```

Read-only evidence showed a two-stage official revision:

1. The certified canonical retained `2026-08-03 = 120.7739`.
2. On 2026-08-12, Board H.10 published `119.6951` while FRED still returned
   `120.7739`; the existing witness-revision policy quarantined this mismatch.
3. On 2026-08-17, FRED changed the same observation to `119.6951`, exactly
   matching H.10. The old code checked primary continuity before witness
   reconciliation and blocked this convergence permanently.

This was not a transport failure and no canonical row had been overwritten.

## Policy

The narrow remediation is:

- preserve every certified Dollar canonical row byte-for-byte;
- quarantine a changed non-latest FRED row only when H.10 confirms the incoming
  value exactly at four decimals;
- record canonical FRED, incoming FRED, H.10, date, and revision source;
- append only dates newer than the canonical tail, each exactly witnessed by
  H.10;
- recompute appended percentile values from the preserved canonical history;
- continue to block a changed latest certified row, a missing certified date,
  an unreviewed historical insertion, missing/mismatched witness evidence, or a
  latest-date mismatch.

No config, feature flag, scoring threshold, routing rule, or IBKR policy changes.

## Verification

TDD RED:

```text
3 failed
```

All three failed on the old unconditional `changed certified FRED row` branch.

TDD GREEN and focused checks:

```text
4 passed
26 passed in test_external_source_fred.py
208 passed across external-source, daily, acceptance, smoke, and drill tests
```

Offline failure drill:

```text
status=PASS
network_used=false
live_data_touched=false
```

Four-date score and seven-artifact persistence comparison against `dece122`:

```text
all_equal=true
dates=2022-06-30, 2024-06-28, 2026-05-29, 2026-07-10
report=/tmp/hermes_dollar_primary_revision_equivalence_2026_08_18.json
```

Governance and full suite:

```text
governance=7/7 OK
1372 passed in 131.84s
```

An isolated replay used the archived 2026-08-17 official raw payload and a copy
of the live canonical. It produced:

```text
status=OK
history_revision_status=QUARANTINED
history_revision_count=1
canonical 2026-08-03 preserved at 120.7739
new tail 2026-08-10..2026-08-14 appended
latest_promoted_as_of=2026-08-14
```

The replay used a temporary data root and did not modify live data.

## Deploy verification remediation

The first R6 deployment attempt of `c991c4b` switched to the candidate release,
failed `verify_live`, and rolled back automatically to `dece122`. The dashboard
returned to HTTP 200 and the failed release did not remain active.

The deploy verifier removes its isolated run log on exit. Its surviving external
precheck summary contained a transient `AttributeError: 'list' object has no
attribute 'get'`, but exact replays of the Dollar retry path succeeded with the
managed Python, live config, and correctly shaped verify data root. A full
candidate `manual_rerun` then reproduced the deterministic blocker at the scoring
boundary:

```text
AttributeError: 'str' object has no attribute 'date'
```

The revision merge preserved certified `publish_date` values as ISO date strings
but appended new rows as pandas timestamps. The resulting mixed CSV column was
not parsed as datetimes by the scoring source. The remediation serializes only
new `publish_date` cells as `YYYY-MM-DD`; certified rows remain unchanged.

TDD proof:

```text
RED: test_dollar_revision_append_remains_consumable_by_scoring_source
     failed at FredPercentileSource.collect with the production traceback
GREEN: 1 passed
Dollar focused: 27 passed
Expanded external/daily/acceptance suite: 363 passed
Full suite: 1373 passed
Governance: 7/7 OK
```

An exact candidate replay using managed Python, live config, and an isolated
clone of live history/soft-history/archive completed with exit 0 through OHLCV
refresh, Dollar promotion, market witness, score pipeline, manifest, reports,
orders preview, and NEXT5. It used `manual_rerun` without commit-state and did not
write an official receipt.
