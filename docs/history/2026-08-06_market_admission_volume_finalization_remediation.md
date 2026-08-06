# Market Admission Volume Finalization Remediation

Date: 2026-08-06

## Decision

The recurring `BRK.B` admission failure is a vendor-finalization problem, not
a price disagreement. Production admission remains full-row fail-closed. This
batch adds research evidence and operator clarity only; it does not change a
canonical row, threshold, source role, config value, feature flag, score,
routing rule, or order path.

The field-aware production policy remains **HOLD_FAIL_CLOSED_POLICY** until the
pre-registered 30-session gate and independent review are complete.

## Incident Evidence

The 2026-08-06 scheduled run quarantined `BRK.B 2026-08-05`:

- Yahoo candidate volume: `2,389,999`
- Alpaca SIP witness volume: `3,758,684`
- Alpha Vantage third-source volume: `3,697,372`
- Yahoo versus Alpha Vantage volume difference: `35.3595%`
- Alpaca versus Alpha Vantage volume difference: `1.6583%`
- all three OHLC prices agree inside the existing price policy

The third source therefore supports `ALPACA_WITNESS` for this event. It does
not retroactively admit the row.

The refreshed 30-session study currently contains 18 independent sessions:

| Measure | Result |
|---|---:|
| Sessions available | 18 / 30 |
| First-artifact blocked sessions | 10 / 18 (55.56%) |
| Unique blocking events | 15 |
| Matured events | 14 |
| Matured events recovered | 14 / 14 |
| Recovered on next observed run | 14 / 14 |
| Field-aware shadow eligible events | 5 |
| Blocked sessions avoided in shadow | 3 / 10 |

Older artifacts without explicit price/volume evidence bands remain blocked
in the shadow simulation. The analysis does not infer missing evidence from a
close match alone.

## Implementation

1. `market_admission_field_inventory()` generates a config/role-derived field
   inventory for every market-witness symbol. Scored symbols, QQQ, and
   component-flow constituents conservatively require OHLCV. BRK.B records
   `decision_fields=[close]`, coherent OHLC certification, and
   `volume_required=false` for research analysis only.
2. `analyze_market_admission_history.py` binds that inventory by SHA-256 and
   simulates field-aware admission without changing production behavior.
3. `market_third_source.py` queries Alpha Vantage `TIME_SERIES_DAILY` only for
   unique rejected equity symbol/dates. It writes a separate atomic shadow
   artifact and never calls a canonical writer.
4. The natural live daily attaches the shadow result only when admission is
   `BLOCKED` with rejected rows. Fetch or credential errors are nonblocking and
   explicitly recorded as research `ERROR`.
5. API keys are loaded from environment or
   `~/.hermes/secrets/alpha_vantage.env`; persisted errors redact the key even
   when a remote exception includes the full query URL.
6. Health detail now names the rejected symbol/date/status, price evidence,
   volume difference, and third-source support when available.

Official Alpha Vantage documentation describes `TIME_SERIES_DAILY` as raw
daily OHLCV and allows compact output for free and premium keys:
`https://www.alphavantage.co/documentation/`.

## Evidence Artifacts

- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_08_06.json`
- `building/reports/data_quality/MARKET_ADMISSION_30_SESSION_STUDY_2026_08_06.md`
- `building/reports/data_quality/market_admission_third_source_2026-08-06.json`
- `building/reports/data_quality/MARKET_ADMISSION_SHADOW_FOUR_DATE_EQUIVALENCE_2026_08_06.json`

The field inventory SHA-256 is
`b17ac01d885ea090e14e0b6255711b0eb32b8321ed794a029be68280d4a49613`.

## Verification

- focused market admission / health / daily suite: `126 passed`
- full suite: `1226 passed`
- governance: `7/7 OK`
- Python compilation: PASS
- four-date score plus seven-persistence-artifact equivalence: `all_equal=true`
  for `2022-06-30`, `2024-06-28`, `2026-05-29`, and `2026-07-10`
- config and feature flags: unchanged
- IBKR readonly invariant: `true`
- repository credential scan: no Alpha Vantage key found

## Release And Observation

This batch is safe to deploy for evidence collection after review. Deployment
must preserve live config and must not rerun an official daily. The next
natural blocked admission may make one Alpha Vantage request per unique
rejected symbol/date and write a separate shadow artifact under the archive.

Continue natural collection without manual repeat refreshes. At 30 independent
sessions, compare current full-OHLCV fail-closed with field-aware admission and
require score/input-hash, hard-valve, routing, persistence, and next-open
baseline evidence before any policy change.
