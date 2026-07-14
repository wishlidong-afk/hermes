# BTC Spot Witness Evidence

Date: 2026-07-14

## Decision

Add Coinbase Exchange as an independent witness for Yahoo `BTC-USD` daily
candidates. Coinbase never writes `BTC_USD.csv`; it can only admit or freeze a
Yahoo candidate. The repository flag `features.use_btc_spot_witness` defaults
OFF until controlled live activation.

The public endpoint is documented at
`https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles`.
It requires no authentication, supports `86400`-second candles, and returns at
most 300 candles per request. Public Exchange REST limits are 10 requests per
second with a burst up to 15:
`https://docs.cdp.coinbase.com/exchange/introduction/rate-limits-overview`.

## Contract

- Yahoo remains the sole canonical candidate writer.
- Coinbase uses `BTC-USD`, matching Yahoo's USD quote currency.
- Exact UTC day and close are compared. Volume is retained in witness evidence
  but never compared because provider volume semantics differ.
- Close difference `<=0.5%` is normal, `(0.5%,1.0%]` is an admitted warning,
  and `>1.0%` freezes the candidate.
- The currently open UTC day is `DEFERRED_UNFINALIZED`: it is not written and
  does not turn health BLOCKED.
- BTC uses calendar days only while the flag is ON. The old NYSE weekend skip is
  byte-identical while OFF.
- Coinbase and Alpaca fetch independently. A failure remains attributed to its
  own source and cannot erase the other source's evidence.
- Public transport retries transient network/429/5xx failures at most three
  times with bounded 1s/2s backoff; exhaustion fails closed.

## Evidence

| Check | Result |
|---|---|
| Focused adapter/admission/backfill/daily/web tests | 107 passed |
| Full suite | 964 passed |
| OFF behavior | Four dates; payload and six persistence artifacts `all_equal=true` |
| Real tail canary | 2026-07-09 through 2026-07-13 all `MATCH` |
| One-year overlap | 365 Yahoo days, 365 Coinbase days, no missing dates |
| Cross-venue distribution | p50 0.0221%, p95 0.0849%, p99 0.1551%, max 0.5042% |
| Policy false blocks | 0/365 days above 1.0% |

An independent blocking review found two P1 fail-open defects before merge:
duplicate Yahoo dates were selected by label instead of row position, and the
1% decision used a rounded value while non-finite closes were not rejected.
Both defects were reproduced red-first and fixed. The same review's P2 findings
are also closed: conflicting/non-midnight Coinbase buckets now fail closed,
late-page failures retain request provenance, and the v2 validator recomputes
row counts/status while validating Coinbase provenance and canonical hashes.

The 2026-07-13 close was the sole warning-band day: Yahoo `61950.9805` versus
Coinbase `62264.94`, a 0.5042% difference. This validates the warning band and
would not freeze the canonical.

Evidence files:

- `building/reports/data_quality/btc_spot_witness_off_equivalence_2026_07_14.json`
- `building/reports/data_quality/btc_spot_witness_live_canary_2026_07_14.json`
- `building/reports/data_quality/btc_spot_witness_historical_overlap_2026_07_14.json`

## Activation And Rollback

Deploy code with the repo flag OFF first. After smoke and `verify_live` pass,
set live `features.use_btc_spot_witness=true` while holding `.pipeline.lock`.
Run a read-only Coinbase/Yahoo canary and verify 8766 remains healthy. Do not run
an official daily solely for activation.

Rollback is one config change under the same lock:
`features.use_btc_spot_witness=false`. The existing US-equity
`use_market_admission_gate` remains ON, and no historical restoration is needed
because every BTC row still originated from Yahoo.
