# Phase 8 Report - Capital Routing

Date: 2026-06-01

## Scope

Phase 8 adds deterministic sell-proceeds routing:

- DEFCON1: macro/liquidity nuclear condition routes to BOXX defensive sleeve, with optional trend sleeve from config.
- DEFCON2: internal break / hard valve / distribution shock routes to BRK.B.
- DEFCON3: routine risk reduction routes to the corresponding 1x instrument.
- BRK.B degradation monitor: if BRK.B is below MA200 or BRK.B/SPY correlation is above the configured threshold, DEFCON2 routes to the configured fallback.

The protocol is pure and read-only. It does not submit orders.

## Verification

- A-module nuclear condition routes to BOXX.
- Hard valve routes to BRK.B when macro nuclear condition is absent.
- Degraded BRK.B routes DEFCON2 proceeds to fallback BOXX.
- Routine SOXL reduction routes to SOXX.
- WATCH/HOLD state produces no route.
- `score_pipeline(...)` includes routing decisions for all trade symbols.

## Remaining Gaps

- BRK.B live degradation requires BRK.B local history or a configured market data adapter.
- Route output is advisory only and not connected to order generation.
