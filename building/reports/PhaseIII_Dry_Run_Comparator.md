# Phase III Dry-run Comparator

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Rows evaluated: 252 / loaded 252
Date filter: `{'start': None, 'end': None, 'days': 252}`
Candidate: threshold `110.0000`, penalty `0.7000`
Live effect: `none`

## Human Gate Summary

| Gate | Count |
|---|---:|
| PASS | 128 |
| WARN | 124 |
| BLOCK | 0 |

| Metric | Value |
|---|---:|
| R3 violations | 0 |
| Max abs symbol delta | 0.1293 |
| Avg max abs symbol delta | 0.0425 |
| Max abs route leg delta | 0.2802 |
| Avg abs turnover delta | 0.0382 |
| Max abs turnover delta | 0.4022 |
| Avg old turnover | 0.2244 |
| Avg new turnover | 0.2285 |

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
| 2025-08-04 | WARN | 0.1293 | -0.4022 | SOXL:-0.1293, FNGU:-0.0862, MSTR:-0.0647 | max symbol delta=0.1293; max route leg delta=0.2802; turnover delta=-0.4022; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5825 |
| 2025-10-08 | WARN | 0.1255 | 0.0786 | SOXL:-0.1255, FNGU:-0.0837 | max symbol delta=0.1255; max route leg delta=0.2091; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5953 |
| 2025-10-06 | WARN | 0.1241 | 0.0978 | SOXL:-0.1241, FNGU:-0.0827, MSTR:-0.0620 | max symbol delta=0.1241; max route leg delta=0.2688; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6001 |
| 2025-08-12 | WARN | 0.1217 | 0.0982 | SOXL:-0.1217, FNGU:-0.0811, MSTR:-0.0608 | max symbol delta=0.1217; max route leg delta=0.2637; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6085 |
| 2025-08-07 | WARN | 0.1203 | 0.1352 | SOXL:-0.1203, FNGU:-0.0802, MSTR:-0.0602 | max symbol delta=0.1203; max route leg delta=0.2607; turnover delta=0.1352; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6133 |
| 2025-07-14 | WARN | 0.1142 | 0.3165 | SOXL:-0.1142, FNGU:-0.0761, MSTR:-0.0571 | max symbol delta=0.1142; max route leg delta=0.2474; turnover delta=0.3165; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6343 |
| 2025-10-09 | WARN | 0.1126 | 0.0431 | SOXL:-0.1126, FNGU:-0.0750 | max symbol delta=0.1126; max route leg delta=0.1876; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6394 |
| 2025-08-13 | WARN | 0.1120 | 0.0421 | SOXL:-0.1120, FNGU:-0.0747, MSTR:-0.0560 | max symbol delta=0.1120; max route leg delta=0.2426; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6416 |
| 2025-07-15 | WARN | 0.1086 | 0.0244 | SOXL:-0.1086, FNGU:-0.0724, MSTR:-0.0543 | max symbol delta=0.1086; max route leg delta=0.2352; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-18 | WARN | 0.1084 | 0.0453 | SOXL:-0.1084, FNGU:-0.0723 | max symbol delta=0.1084; max route leg delta=0.1807; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-08 | WARN | 0.1078 | 0.0543 | SOXL:-0.1078, FNGU:-0.0718, MSTR:-0.0539 | max symbol delta=0.1078; max route leg delta=0.2335; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-02 | WARN | 0.1068 | 0.0401 | SOXL:-0.1068, FNGU:-0.0712, MSTR:-0.0534 | max symbol delta=0.1068; max route leg delta=0.2315; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-16 | WARN | 0.1056 | 0.0130 | SOXL:-0.1056, FNGU:-0.0704, MSTR:-0.0528 | max symbol delta=0.1056; max route leg delta=0.2287; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-28 | WARN | 0.1036 | 0.0298 | SOXL:-0.1036, FNGU:-0.0691, MSTR:-0.0518 | max symbol delta=0.1036; max route leg delta=0.2244; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-23 | WARN | 0.1028 | 0.0012 | SOXL:-0.1028, FNGU:-0.0685, MSTR:-0.0514 | max symbol delta=0.1028; max route leg delta=0.2228; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-22 | WARN | 0.1025 | 0.0309 | SOXL:-0.1025, FNGU:-0.0684, MSTR:-0.0513 | max symbol delta=0.1025; max route leg delta=0.2222; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-07 | WARN | 0.1019 | 0.0739 | SOXL:-0.1019, FNGU:-0.0679 | max symbol delta=0.1019; max route leg delta=0.1698; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-03 | WARN | 0.1015 | 0.0230 | SOXL:-0.1015, FNGU:-0.0677, MSTR:-0.0508 | max symbol delta=0.1015; max route leg delta=0.2199; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-18 | WARN | 0.1006 | 0.0035 | SOXL:-0.1006, FNGU:-0.0671, MSTR:-0.0503 | max symbol delta=0.1006; max route leg delta=0.2180; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-24 | WARN | 0.1004 | 0.0103 | SOXL:-0.1004, FNGU:-0.0670, MSTR:-0.0502 | max symbol delta=0.1004; max route leg delta=0.2176; risk binding=EXTREME_CORR; corr regime=EXTREME |

## Notes

- Read-only dry run; no live config, feature flag, account state, or signal journal is changed.
- Old route weights come from cached backtest rows; new route weights use the Phase II review candidate and cached routing decision.
- BLOCK means invariant failure; WARN means human review required before any scaler migration; PASS is informational only.
- The candidate remains shadow-only until daily comparator, turnover review, and human gate all pass.
