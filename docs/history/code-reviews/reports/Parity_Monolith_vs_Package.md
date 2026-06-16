# Parity — Monolith vs Package (T5 V1)

Dates compared: 6 (2026-05-22, 2026-05-26, 2026-05-27, 2026-05-28, 2026-05-29, 2026-06-01)

| Field | Match rate | matched/total |
|---|---:|---:|
| hard_ids | 100.0% | 18/18 |
| status | 44.4% | 8/18 |
| sell_pct | 72.2% | 13/18 |
| destination | 72.2% | 13/18 |
| routed | 72.2% | 13/18 |

Total field divergences: **25**

> V1: inputs from each system's own loader; byte-identical bridge is T1-T4.

## Divergences (first 40)
| date | symbol | field | monolith | package |
|---|---|---|---|---|
| 2026-05-22 | FNGU | status | WATCH | HOLD |
| 2026-05-22 | SOXL | status | WATCH | HOLD |
| 2026-05-26 | FNGU | status | WATCH | HOLD |
| 2026-05-26 | SOXL | status | REDUCE | HOLD |
| 2026-05-26 | SOXL | sell_pct | 60 | 0.0 |
| 2026-05-26 | SOXL | destination | BRK.B | None |
| 2026-05-26 | SOXL | routed | True | False |
| 2026-05-27 | FNGU | status | REDUCE | HOLD |
| 2026-05-27 | FNGU | sell_pct | 60 | 0.0 |
| 2026-05-27 | FNGU | destination | BRK.B | None |
| 2026-05-27 | FNGU | routed | True | False |
| 2026-05-28 | FNGU | status | WATCH | HOLD |
| 2026-05-29 | FNGU | status | WATCH | HOLD |
| 2026-05-29 | SOXL | status | WATCH | REDUCE |
| 2026-05-29 | SOXL | sell_pct | 0 | 60.0 |
| 2026-05-29 | SOXL | destination | None | BRK.B |
| 2026-05-29 | SOXL | routed | False | True |
| 2026-06-01 | FNGU | status | REDUCE | HOLD |
| 2026-06-01 | FNGU | sell_pct | 60 | 0.0 |
| 2026-06-01 | FNGU | destination | BRK.B | None |
| 2026-06-01 | FNGU | routed | True | False |
| 2026-06-01 | SOXL | status | WATCH | REDUCE |
| 2026-06-01 | SOXL | sell_pct | 0 | 60.0 |
| 2026-06-01 | SOXL | destination | None | BRK.B |
| 2026-06-01 | SOXL | routed | False | True |
