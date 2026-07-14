# BTC Spot Witness Design

Date: 2026-07-14

## Goal

Prevent Yahoo from silently replacing `BTC-USD` canonical history when an
independent USD spot exchange does not confirm the completed UTC-day close.
Coinbase Exchange is witness-only and never writes canonical history itself.

## Source Decision

Use the public Coinbase Exchange `BTC-USD` candles endpoint with one-day
granularity. It requires no authentication, returns UTC buckets, limits one
request to 300 candles, and permits public clients at 10 requests per second.
The endpoint warns that historical intervals may be absent when there were no
ticks, so a missing completed bucket freezes the old canonical instead of being
filled or inferred.

Coinbase is preferred over Binance because it is directly accessible in the
current production network and uses the same USD quote currency as Yahoo
`BTC-USD`. It is preferred over Kraken for this task because Coinbase supports
bounded historical ranges rather than only a short rolling tail.

## Admission Contract

1. `features.use_btc_spot_witness` defaults to `false`.
2. OFF preserves the current market-admission payload and persistence outputs
   byte-for-byte.
3. ON fetches Coinbase one-day candles independently from Alpaca SIP. A failure
   in one witness does not erase successful evidence from the other, but the
   affected symbol freezes and health exposes the failed source.
4. BTC compares exact UTC bucket date and close only. Volume is evidence but is
   not compared because Yahoo and Coinbase publish different volume notions.
5. Close difference at or below 0.5% is normal; 0.5%-1.0% is admitted with a
   warning; above 1.0% is `PRICE_MISMATCH` and remains frozen.
6. A candle is eligible only after its UTC day has completed. A still-open UTC
   day is deferred, not counted as a blocking rejection, and never promoted.
7. BTC uses a seven-day calendar. The existing NYSE weekday shortcut remains
   unchanged for every other symbol and remains unchanged for BTC while the
   flag is OFF.
8. Each admission payload records Coinbase request URL, stable response SHA256,
   fetch time, completed-through date, row-level witness SHA, and the canonical
   SHA bound by the existing evidence writer.
9. Missing candle, fetch failure, date mismatch, or price mismatch preserves
   the last certified `BTC_USD.csv`. There is no fallback exchange and no
   silent source selection in this release.

## Integration

Create `core/data/coinbase_witness.py` for transport, chunking, UTC completion,
normalization, and close comparison. Extend `MarketAdmissionSession` with an
opt-in BTC path while leaving the existing Alpaca path unchanged when the new
flag is OFF. `backfill_history.py` passes the flag into automatic and daily
session construction and permits weekend intervals only for an enabled BTC
witness session.

The existing `market_admission_latest.json` remains the health contract. The
source string changes to include Coinbase only while ON. Web health therefore
needs no new severity model: Coinbase failures appear as existing
`FETCH_ERROR`, and mismatches appear as existing `BLOCKED` with a BTC-specific
row reason.

## Verification

- Unit tests for Coinbase parsing, range filtering, 300-candle chunking,
  completed UTC-day cutoff, close tolerances, and response SHA evidence.
- Admission tests for match, warning, mismatch, missing witness, independent
  Alpaca/Coinbase failure, and nonblocking current-day deferral.
- Backfill tests proving weekend BTC admission and frozen canonical on mismatch.
- Four-date OFF payload plus six-persistence-artifact equality proof.
- Isolated real-network canary against current Yahoo canonical.
- Full repository suite, independent review, code-only deployment with flag
  OFF, then a lock-held live activation and non-official verification.

## Rollback

Set live `features.use_btc_spot_witness=false`. Yahoo BTC returns to the current
ungated behavior while the broader Yahoo+Alpaca US-equity admission gate stays
ON. No history rewrite is needed because Coinbase never writes a row and every
admitted row remains a Yahoo candidate.
