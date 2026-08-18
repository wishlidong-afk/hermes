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
