# Phase III Dry-run Comparator

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 252 / loaded 252
Date filter: `{'start': None, 'end': None, 'days': 252}`
Candidate: threshold `110.0000`, penalty `0.9000`
Live effect: `none`

## Human Gate Summary

| Gate | Count |
|---|---:|
| PASS | 129 |
| WARN | 123 |
| BLOCK | 0 |

| Metric | Value |
|---|---:|
| R3 violations | 0 |
| Max abs symbol delta | 0.0997 |
| Avg max abs symbol delta | 0.0255 |
| Max abs route leg delta | 0.1745 |
| Avg abs turnover delta | 0.0306 |
| Max abs turnover delta | 0.2886 |
| Avg old turnover | 0.2244 |
| Avg new turnover | 0.2263 |

## Risk Regime Counts

| Field | Counts |
|---|---|
| Binding | `{'NONE': 97, 'VOL': 53, 'EXTREME_CORR': 102}` |
| Corr regime | `{'ELEVATED': 150, 'EXTREME': 102}` |

## Latest Daily Rows

| Date | Gate | Gross | Binding | Max Symbol Δ | Turnover Old/New/Δ | Top Target Deltas | Reasons |
|---|---|---:|---|---:|---:|---|---|
| 2026-04-17 | PASS | 0.9582 | VOL | 0.0165 | 0.3955/0.3717/-0.0238 | FNGU:+0.0165, SOXL:+0.0094 | within dry-run tolerance |
| 2026-04-20 | PASS | 1.0000 | NONE | 0.0206 | 0.0258/0.0311/0.0053 | FNGU:+0.0206, SOXL:+0.0095 | within dry-run tolerance |
| 2026-04-21 | PASS | 1.0000 | NONE | 0.0189 | 0.0313/0.0000/-0.0313 | FNGU:+0.0189, SOXL:-0.0044 | within dry-run tolerance |
| 2026-04-22 | PASS | 0.9690 | VOL | 0.0194 | 0.0099/0.0231/0.0132 | FNGU:+0.0194, SOXL:-0.0155 | within dry-run tolerance |
| 2026-04-23 | PASS | 1.0000 | NONE | 0.0236 | 0.9506/0.8824/-0.0682 | FNGU:+0.0236, SOXL:-0.0026 | within dry-run tolerance |
| 2026-04-24 | WARN | 0.6751 | VOL | 0.0997 | 0.5275/0.2692/-0.2582 | SOXL:-0.0997, FNGU:-0.0083 | turnover delta=-0.2582 |
| 2026-04-27 | WARN | 1.0000 | NONE | 0.0481 | 0.3669/0.2367/-0.1301 | FNGU:+0.0481, SOXL:+0.0029 | turnover delta=-0.1301 |
| 2026-04-28 | PASS | 1.0000 | NONE | 0.0206 | 0.2134/0.2349/0.0215 | SOXL:+0.0206, FNGU:+0.0196 | within dry-run tolerance |
| 2026-04-29 | PASS | 0.8051 | VOL | 0.0131 | 0.3111/0.2379/-0.0732 | SOXL:-0.0131, FNGU:+0.0015 | within dry-run tolerance |
| 2026-04-30 | PASS | 0.8113 | VOL | 0.0194 | 0.0218/0.0046/-0.0171 | SOXL:-0.0194, FNGU:-0.0007 | within dry-run tolerance |
| 2026-05-01 | PASS | 0.8142 | VOL | 0.0313 | 0.2295/0.1934/-0.0361 | SOXL:-0.0313, FNGU:-0.0069 | within dry-run tolerance |
| 2026-05-04 | PASS | 0.8281 | VOL | 0.0316 | 0.0256/0.0135/-0.0121 | SOXL:-0.0316, FNGU:-0.0127 | within dry-run tolerance |
| 2026-05-05 | PASS | 0.7543 | VOL | 0.0406 | 0.0252/0.0722/0.0470 | SOXL:-0.0406, FNGU:-0.0353 | within dry-run tolerance |
| 2026-05-06 | WARN | 1.0000 | NONE | 0.0187 | 0.3266/0.2080/-0.1186 | SOXL:+0.0187, FNGU:+0.0085 | turnover delta=-0.1186 |
| 2026-05-07 | PASS | 0.6966 | VOL | 0.0562 | 0.5675/0.4742/-0.0933 | FNGU:-0.0562, SOXL:-0.0226 | within dry-run tolerance |
| 2026-05-08 | WARN | 0.5940 | VOL | 0.0648 | 0.0471/0.1004/0.0534 | FNGU:-0.0648, SOXL:-0.0408 | scenario gross=0.5940 |
| 2026-05-11 | WARN | 0.6091 | VOL | 0.0700 | 0.0364/0.0148/-0.0216 | FNGU:-0.0700, SOXL:-0.0463 | scenario gross=0.6091 |
| 2026-05-12 | WARN | 0.6206 | VOL | 0.0666 | 0.0375/0.0113/-0.0262 | FNGU:-0.0666, SOXL:-0.0254 | scenario gross=0.6206 |
| 2026-05-13 | PASS | 0.6687 | VOL | 0.0625 | 0.0295/0.0471/0.0176 | FNGU:-0.0625, SOXL:-0.0207 | within dry-run tolerance |
| 2026-05-14 | PASS | 0.7002 | VOL | 0.0629 | 0.0327/0.0308/-0.0020 | FNGU:-0.0629, SOXL:-0.0212 | within dry-run tolerance |
| 2026-05-15 | PASS | 0.7114 | VOL | 0.0399 | 0.0855/0.0110/-0.0745 | FNGU:-0.0399, SOXL:+0.0040 | within dry-run tolerance |
| 2026-05-18 | PASS | 1.0000 | NONE | 0.0359 | 0.4401/0.4781/0.0380 | SOXL:+0.0359, FNGU:+0.0150 | within dry-run tolerance |
| 2026-05-19 | PASS | 1.0000 | NONE | 0.0318 | 0.0148/0.0000/-0.0148 | SOXL:+0.0318, FNGU:+0.0117 | within dry-run tolerance |
| 2026-05-20 | PASS | 0.6687 | VOL | 0.0536 | 0.4287/0.4948/0.0661 | FNGU:-0.0536, SOXL:-0.0082 | within dry-run tolerance |
| 2026-05-21 | PASS | 0.7011 | VOL | 0.0547 | 0.0357/0.0317/-0.0040 | FNGU:-0.0547, SOXL:-0.0091 | within dry-run tolerance |
| 2026-05-22 | PASS | 0.7436 | VOL | 0.0489 | 0.0217/0.0416/0.0199 | FNGU:-0.0489, SOXL:-0.0050 | within dry-run tolerance |
| 2026-05-26 | WARN | 0.5873 | VOL | 0.0529 | 0.0937/0.1529/0.0592 | FNGU:-0.0529, SOXL:-0.0306 | scenario gross=0.5873 |
| 2026-05-27 | WARN | 0.6325 | VOL | 0.0512 | 0.0211/0.0442/0.0231 | FNGU:-0.0512, SOXL:-0.0207 | scenario gross=0.6325 |
| 2026-05-28 | PASS | 0.6828 | VOL | 0.0479 | 0.0341/0.0493/0.0152 | FNGU:-0.0479, SOXL:-0.0165 | within dry-run tolerance |
| 2026-05-29 | PASS | 0.6909 | VOL | 0.0449 | 0.0186/0.0079/-0.0107 | FNGU:-0.0449, SOXL:-0.0234 | within dry-run tolerance |

## Largest Difference Days

| Date | Gate | Max Symbol Δ | Turnover Δ | Top Target Deltas | Reasons |
|---|---|---:|---:|---|---|
| 2026-04-24 | WARN | 0.0997 | -0.2582 | SOXL:-0.0997, FNGU:-0.0083 | turnover delta=-0.2582 |
| 2025-08-04 | WARN | 0.0806 | -0.2886 | SOXL:-0.0806, FNGU:-0.0537, MSTR:-0.0403 | max route leg delta=0.1745; turnover delta=-0.2886; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-08 | WARN | 0.0756 | 0.1010 | SOXL:-0.0756, FNGU:-0.0504 | turnover delta=0.1010; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-16 | WARN | 0.0744 | 0.0000 | FNGU:-0.0744, SOXL:-0.0246 | scenario gross=0.6074 |
| 2025-10-06 | WARN | 0.0738 | 0.1258 | SOXL:-0.0738, FNGU:-0.0492, MSTR:-0.0369 | max route leg delta=0.1599; turnover delta=0.1258; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-12 | WARN | 0.0708 | 0.1262 | SOXL:-0.0708, FNGU:-0.0472, MSTR:-0.0354 | max route leg delta=0.1533; turnover delta=0.1262; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-05-11 | WARN | 0.0700 | -0.0216 | FNGU:-0.0700, SOXL:-0.0463 | scenario gross=0.6091 |
| 2025-08-07 | WARN | 0.0690 | 0.1053 | SOXL:-0.0690, FNGU:-0.0460, MSTR:-0.0345 | turnover delta=0.1053; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-15 | WARN | 0.0687 | -0.2751 | FNGU:-0.0687, SOXL:-0.0179 | turnover delta=-0.2751; scenario gross=0.5939 |
| 2025-10-13 | WARN | 0.0674 | 0.0285 | FNGU:-0.0674, SOXL:-0.0162 | scenario gross=0.5770 |
| 2026-05-12 | WARN | 0.0666 | -0.0262 | FNGU:-0.0666, SOXL:-0.0254 | scenario gross=0.6206 |
| 2026-05-08 | WARN | 0.0648 | 0.0534 | FNGU:-0.0648, SOXL:-0.0408 | scenario gross=0.5940 |
| 2026-05-14 | PASS | 0.0629 | -0.0020 | FNGU:-0.0629, SOXL:-0.0212 | within dry-run tolerance |
| 2025-08-22 | PASS | 0.0628 | 0.0483 | SOXL:-0.0628, FNGU:-0.0418, MSTR:-0.0314 | within dry-run tolerance |
| 2026-05-13 | PASS | 0.0625 | 0.0176 | FNGU:-0.0625, SOXL:-0.0207 | within dry-run tolerance |
| 2025-07-02 | WARN | 0.0611 | 0.1317 | SOXL:-0.0611, FNGU:-0.0407, MSTR:-0.0306 | turnover delta=0.1317 |
| 2025-07-14 | WARN | 0.0611 | 0.0864 | SOXL:-0.0611, FNGU:-0.0407, MSTR:-0.0306 | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-08 | WARN | 0.0601 | 0.1295 | SOXL:-0.0601, FNGU:-0.0401, MSTR:-0.0301 | turnover delta=0.1295 |
| 2025-10-09 | WARN | 0.0590 | 0.0554 | SOXL:-0.0590, FNGU:-0.0393 | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-11-10 | WARN | 0.0583 | -0.2270 | FNGU:-0.0583, SOXL:-0.0381 | turnover delta=-0.2270 |

## Notes

- Read-only dry run; no live config, feature flag, account state, or signal journal is changed.
- Old route weights come from cached backtest rows; new route weights use the Phase II review candidate and cached routing decision.
- BLOCK means invariant failure; WARN means human review required before any scaler migration; PASS is informational only.
- The candidate remains shadow-only until daily comparator, turnover review, and human gate all pass.
