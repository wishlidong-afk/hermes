# Phase 3 Report - Scoring Core A/B/C/D

Date: 2026-06-01

## Scope

Phase 3 adds the executable greenfield scoring core:

- Factor registry with declared dependencies, max score, module, missing-data label, and pure score function.
- A/B/C/D factor sets using current price-derived data, component basket flow, and explicit placeholders only for true soft-data sources.
- Module caps: A20 / B25 / C35 / D20.
- Symbol-specific module weighting from config.
- Regime multiplier support through `weighted_percent_score`, now wired by the main pipeline from QQQ/VIX/VIX3M snapshots.
- Missing-data scaling through the existing `analyze_missing_fields` contract.
- Preliminary status and sell-fraction mapping from config.
- CLI command: `python3 -m hermes_escape_top.cli score --as-of YYYY-MM-DD`.

## Implemented Factors

- A: QQQ MA200 break, broad-market EMA50 proxy, QQQ CMF/MFI/AD fund-flow pressure, VIX term structure, QQQ distribution days, and explicit missing placeholders only for sentiment/liquidity soft data.
- B: RSI overheat, MA200 extension, post-peak damage, and explicit missing placeholders for options/social/valuation.
- C: Super Trend Structure factor combining EMA50 break, Minervini structure failure, and Weinstein 150/200D failure into one max-10 factor; sharp drop; AVWAP/platform support; distribution pressure; Chandelier break; MA220 rebuild gap; realized-vol expansion.
- D: Asset MA200/MA220 break, 60D trailing peak damage, symbol radar confirmation, FNGU/SOXL component-flow pressure, and MSTR-only soft-data placeholders.

## Safety Notes

- Critical missing fields such as `close` and `ma200` still force adjusted score to 100.
- Soft missing fields are not treated as 0-risk. They enter missing-weight scaling and can activate blind-spot penalty.
- Hard valves are intentionally not implemented here; they remain Phase 4 so the "trigger = EXIT 100%" semantics can be migrated and tested separately.

## Verification

- Unit tests cover C10 cap, critical missing-data escalation, status/sell mapping, deterministic weighting, live local history scoring for FNGU/MSTR/SOXL on 2026-05-29, regime payload wiring, and the removal of A6/C7/D-F4/D-S4 price-core placeholders.

## Remaining Gaps

- Soft data adapters remain missing, so some scores will be blind-spot adjusted until Phase 10.
- Rolling-quantile thresholds are scaffolded but most scoring ladders still use conservative fixed thresholds pending full parameter sweep.
