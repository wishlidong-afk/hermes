# Phase III WARN Review

Source: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/PhaseIII_Dry_Run_Comparator.json`
Rows evaluated: 252
Candidate: `{'penalty': 0.7, 'threshold': 110.0}`
Live effect: `none`

## Readiness

| Field | Value |
|---|---|
| Status | `REVIEW_REQUIRED` |
| WARN share | 49.21% |
| Live promotion | `BLOCKED` |
| Next step | Human-review WARN clusters and turnover outliers before scaler migration design. |
| Review items | max turnover delta requires human review |

## Gate And Reason Counts

| Field | Counts |
|---|---|
| Gates | `{'PASS': 128, 'WARN': 124}` |
| Reason categories | `{'TURNOVER_DELTA': 28, 'EXTREME_CORR': 102, 'EXTREME_REGIME': 102, 'LOW_GROSS': 16, 'ROUTE_LEG_DELTA': 50, 'SYMBOL_DELTA': 20}` |
| WARN months | `{'2025-07': 17, '2025-08': 19, '2025-09': 21, '2025-10': 12, '2025-11': 3, '2026-01': 20, '2026-02': 16, '2026-03': 7, '2026-04': 3, '2026-05': 6}` |

## Forward Delta Stats

Candidate minus old route, using same-day route weights held over the next N trading days.

| Horizon | WARN avg | WARN median | WARN positive share | PASS avg | PASS median | PASS positive share |
|---:|---:|---:|---:|---:|---:|---:|
| 1d | -0.00% | -0.02% | 39.52% | -0.00% | 0.00% | 43.31% |
| 5d | -0.05% | -0.04% | 40.98% | 0.01% | 0.00% | 38.40% |
| 10d | -0.29% | -0.02% | 41.80% | 0.07% | 0.00% | 39.17% |

## Category Forward Stats

| Category | Count | Avg Abs Turnover Δ | 1d Avg Δ | 5d Avg Δ | 10d Avg Δ |
|---|---:|---:|---:|---:|---:|
| EXTREME_CORR | 102 | 0.0443 | -0.01% | -0.09% | -0.28% |
| EXTREME_REGIME | 102 | 0.0443 | -0.01% | -0.09% | -0.28% |
| LOW_GROSS | 16 | 0.1063 | 0.26% | 0.49% | -0.10% |
| ROUTE_LEG_DELTA | 50 | 0.0475 | -0.01% | -0.12% | -0.47% |
| SYMBOL_DELTA | 20 | 0.0782 | 0.10% | 0.50% | 0.52% |
| TURNOVER_DELTA | 28 | 0.1810 | 0.06% | -0.15% | -0.28% |

## Largest Symbol Delta WARN Rows

| Date | Categories | Gross | Binding | Max Symbol Δ | Turnover Δ | Forward Δ | Reasons |
|---|---|---:|---|---:|---:|---:|---|
| 2025-08-04 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.5825 | EXTREME_CORR | 0.1293 | -0.4022 | 0.75% | max symbol delta=0.1293; max route leg delta=0.2802; turnover delta=-0.4022; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5825 |
| 2025-10-08 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.5953 | EXTREME_CORR | 0.1255 | 0.0786 | 0.09% | max symbol delta=0.1255; max route leg delta=0.2091; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5953 |
| 2025-10-06 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6001 | EXTREME_CORR | 0.1241 | 0.0978 | 1.49% | max symbol delta=0.1241; max route leg delta=0.2688; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6001 |
| 2025-08-12 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6085 | EXTREME_CORR | 0.1217 | 0.0982 | -0.39% | max symbol delta=0.1217; max route leg delta=0.2637; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6085 |
| 2025-08-07 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.6133 | EXTREME_CORR | 0.1203 | 0.1352 | -0.47% | max symbol delta=0.1203; max route leg delta=0.2607; turnover delta=0.1352; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6133 |
| 2025-07-14 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.6343 | EXTREME_CORR | 0.1142 | 0.3165 | -0.31% | max symbol delta=0.1142; max route leg delta=0.2474; turnover delta=0.3165; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6343 |
| 2025-10-09 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6394 | EXTREME_CORR | 0.1126 | 0.0431 | 2.88% | max symbol delta=0.1126; max route leg delta=0.1876; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6394 |
| 2025-08-13 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6416 | EXTREME_CORR | 0.1120 | 0.0421 | 0.12% | max symbol delta=0.1120; max route leg delta=0.2426; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6416 |
| 2025-07-15 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6535 | EXTREME_CORR | 0.1086 | 0.0244 | -0.03% | max symbol delta=0.1086; max route leg delta=0.2352; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-18 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6536 | EXTREME_CORR | 0.1084 | 0.0453 | 0.01% | max symbol delta=0.1084; max route leg delta=0.1807; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-08 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6561 | EXTREME_CORR | 0.1078 | 0.0543 | 0.02% | max symbol delta=0.1078; max route leg delta=0.2335; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-02 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6590 | EXTREME_CORR | 0.1068 | 0.0401 | 0.37% | max symbol delta=0.1068; max route leg delta=0.2315; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-16 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6637 | EXTREME_CORR | 0.1056 | 0.0130 | -0.16% | max symbol delta=0.1056; max route leg delta=0.2287; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-28 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6704 | EXTREME_CORR | 0.1036 | 0.0298 | 0.11% | max symbol delta=0.1036; max route leg delta=0.2244; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-23 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6731 | EXTREME_CORR | 0.1028 | 0.0012 | -0.22% | max symbol delta=0.1028; max route leg delta=0.2228; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-22 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6740 | EXTREME_CORR | 0.1025 | 0.0309 | 0.38% | max symbol delta=0.1025; max route leg delta=0.2222; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-07 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6757 | EXTREME_CORR | 0.1019 | 0.0739 | -1.35% | max symbol delta=0.1019; max route leg delta=0.1698; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-03 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6771 | EXTREME_CORR | 0.1015 | 0.0230 | -1.12% | max symbol delta=0.1015; max route leg delta=0.2199; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-18 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6805 | EXTREME_CORR | 0.1006 | 0.0035 | -0.29% | max symbol delta=0.1006; max route leg delta=0.2180; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-24 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6812 | EXTREME_CORR | 0.1004 | 0.0103 | 0.15% | max symbol delta=0.1004; max route leg delta=0.2176; risk binding=EXTREME_CORR; corr regime=EXTREME |

## Largest Abs Turnover Delta WARN Rows

| Date | Categories | Gross | Binding | Max Symbol Δ | Turnover Δ | Forward Δ | Reasons |
|---|---|---:|---|---:|---:|---:|---|
| 2025-08-04 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.5825 | EXTREME_CORR | 0.1293 | -0.4022 | 0.75% | max symbol delta=0.1293; max route leg delta=0.2802; turnover delta=-0.4022; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5825 |
| 2025-07-14 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.6343 | EXTREME_CORR | 0.1142 | 0.3165 | -0.31% | max symbol delta=0.1142; max route leg delta=0.2474; turnover delta=0.3165; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6343 |
| 2025-08-28 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0949 | 0.2930 | 1.16% | max route leg delta=0.1581; turnover delta=0.2930; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-05 | TURNOVER_DELTA | 1.0000 | NONE | 0.0047 | 0.2910 | -0.02% | turnover delta=0.2910 |
| 2025-08-06 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0633 | 0.2754 | -0.37% | turnover delta=0.2754; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-15 | LOW_GROSS,TURNOVER_DELTA | 0.5939 | VOL | 0.0687 | -0.2751 | 0.08% | turnover delta=-0.2751; scenario gross=0.5939 |
| 2026-04-24 | TURNOVER_DELTA | 0.6751 | VOL | 0.0997 | -0.2582 | 0.36% | turnover delta=-0.2582 |
| 2025-10-14 | TURNOVER_DELTA | 0.9102 | VOL | 0.0501 | -0.2404 | 0.46% | turnover delta=-0.2404 |
| 2025-11-10 | TURNOVER_DELTA | 0.6929 | VOL | 0.0583 | -0.2270 | 0.29% | turnover delta=-0.2270 |
| 2025-09-03 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | -0.1897 | -0.46% | max route leg delta=0.1581; turnover delta=-0.1897; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-25 | TURNOVER_DELTA | 0.9995 | VOL | 0.0071 | 0.1856 | -0.02% | turnover delta=0.1856 |
| 2025-08-01 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0411 | -0.1392 | -0.36% | turnover delta=-0.1392; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-11-13 | TURNOVER_DELTA | 1.0000 | NONE | 0.0241 | -0.1372 | -0.02% | turnover delta=-0.1372 |
| 2025-10-10 | TURNOVER_DELTA | 1.0000 | NONE | 0.0030 | -0.1359 | -0.02% | turnover delta=-0.1359 |
| 2025-08-07 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.6133 | EXTREME_CORR | 0.1203 | 0.1352 | -0.47% | max symbol delta=0.1203; max route leg delta=0.2607; turnover delta=0.1352; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6133 |
| 2025-07-02 | TURNOVER_DELTA | 0.8155 | VOL | 0.0611 | 0.1317 | -0.27% | turnover delta=0.1317 |
| 2026-04-27 | TURNOVER_DELTA | 1.0000 | NONE | 0.0481 | -0.1301 | -0.19% | turnover delta=-0.1301 |
| 2025-07-08 | TURNOVER_DELTA | 0.8188 | VOL | 0.0601 | 0.1295 | -0.33% | turnover delta=0.1295 |
| 2026-04-15 | TURNOVER_DELTA | 0.9648 | VOL | 0.0340 | 0.1291 | 0.10% | turnover delta=0.1291 |
| 2025-08-21 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0379 | 0.1265 | -0.42% | turnover delta=0.1265; risk binding=EXTREME_CORR; corr regime=EXTREME |

## Largest 1d Candidate Drag WARN Rows

| Date | Categories | Gross | Binding | Max Symbol Δ | Turnover Δ | Forward Δ | Reasons |
|---|---|---:|---|---:|---:|---:|---|
| 2025-10-07 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6757 | EXTREME_CORR | 0.1019 | 0.0739 | -1.35% | max symbol delta=0.1019; max route leg delta=0.1698; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-17 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | 0.0000 | -1.20% | max route leg delta=0.1580; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-03 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6771 | EXTREME_CORR | 0.1015 | 0.0230 | -1.12% | max symbol delta=0.1015; max route leg delta=0.2199; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-11 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6858 | EXTREME_CORR | 0.0990 | 0.0378 | -1.07% | max route leg delta=0.2146; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-01-05 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0946 | -0.0663 | -0.92% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-01-27 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0946 | 0.0000 | -0.75% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-01-26 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0946 | 0.0000 | -0.66% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-01 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | 0.0000 | -0.63% | max route leg delta=0.1580; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-09 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | 0.0000 | -0.58% | max route leg delta=0.1581; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-25 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6939 | EXTREME_CORR | 0.0967 | 0.0162 | -0.58% | max route leg delta=0.2095; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-30 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | 0.0000 | -0.55% | max route leg delta=0.1580; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-12 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | 0.0000 | -0.51% | max route leg delta=0.1581; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-07 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.6133 | EXTREME_CORR | 0.1203 | 0.1352 | -0.47% | max symbol delta=0.1203; max route leg delta=0.2607; turnover delta=0.1352; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6133 |
| 2025-09-03 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0948 | -0.1897 | -0.46% | max route leg delta=0.1581; turnover delta=-0.1897; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-09-05 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6857 | EXTREME_CORR | 0.0990 | 0.0000 | -0.44% | max route leg delta=0.1651; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-05-12 | LOW_GROSS | 0.6206 | VOL | 0.0666 | -0.0262 | -0.44% | scenario gross=0.6206 |
| 2025-09-04 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6861 | EXTREME_CORR | 0.0989 | 0.0136 | -0.43% | max route leg delta=0.1649; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-21 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0379 | 0.1265 | -0.42% | turnover delta=0.1265; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-12 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6085 | EXTREME_CORR | 0.1217 | 0.0982 | -0.39% | max symbol delta=0.1217; max route leg delta=0.2637; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6085 |
| 2025-08-06 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0633 | 0.2754 | -0.37% | turnover delta=0.2754; risk binding=EXTREME_CORR; corr regime=EXTREME |

## Largest 1d Candidate Benefit WARN Rows

| Date | Categories | Gross | Binding | Max Symbol Δ | Turnover Δ | Forward Δ | Reasons |
|---|---|---:|---|---:|---:|---:|---|
| 2025-10-09 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6394 | EXTREME_CORR | 0.1126 | 0.0431 | 2.88% | max symbol delta=0.1126; max route leg delta=0.1876; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6394 |
| 2025-10-06 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6001 | EXTREME_CORR | 0.1241 | 0.0978 | 1.49% | max symbol delta=0.1241; max route leg delta=0.2688; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.6001 |
| 2025-08-28 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0949 | 0.2930 | 1.16% | max route leg delta=0.1581; turnover delta=0.2930; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-31 | EXTREME_CORR,EXTREME_REGIME,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0633 | -0.1139 | 1.07% | turnover delta=-0.1139; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-03-02 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0615 | 0.0756 | 0.92% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-02-25 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0946 | -0.0662 | 0.86% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-18 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0949 | 0.0027 | 0.78% | max route leg delta=0.1581; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-30 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.7000 | EXTREME_CORR | 0.0949 | 0.0000 | 0.78% | max route leg delta=0.2056; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-08-04 | EXTREME_CORR,EXTREME_REGIME,LOW_GROSS,ROUTE_LEG_DELTA,SYMBOL_DELTA,TURNOVER_DELTA | 0.5825 | EXTREME_CORR | 0.1293 | -0.4022 | 0.75% | max symbol delta=0.1293; max route leg delta=0.2802; turnover delta=-0.4022; risk binding=EXTREME_CORR; corr regime=EXTREME; scenario gross=0.5825 |
| 2025-08-14 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,TURNOVER_DELTA | 0.7000 | EXTREME_CORR | 0.0949 | -0.1120 | 0.69% | max route leg delta=0.1581; turnover delta=-0.1120; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-07-21 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6984 | EXTREME_CORR | 0.0954 | 0.0226 | 0.64% | max route leg delta=0.2067; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-05-11 | LOW_GROSS | 0.6091 | VOL | 0.0700 | -0.0216 | 0.58% | scenario gross=0.6091 |
| 2026-02-03 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0344 | -0.0037 | 0.52% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-01-07 | EXTREME_CORR,EXTREME_REGIME | 0.7000 | EXTREME_CORR | 0.0946 | 0.0000 | 0.48% | risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-14 | TURNOVER_DELTA | 0.9102 | VOL | 0.0501 | -0.2404 | 0.46% | turnover delta=-0.2404 |
| 2025-10-13 | LOW_GROSS | 0.5770 | VOL | 0.0674 | 0.0285 | 0.44% | scenario gross=0.5770 |
| 2025-07-22 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6740 | EXTREME_CORR | 0.1025 | 0.0309 | 0.38% | max symbol delta=0.1025; max route leg delta=0.2222; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2025-10-02 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA,SYMBOL_DELTA | 0.6590 | EXTREME_CORR | 0.1068 | 0.0401 | 0.37% | max symbol delta=0.1068; max route leg delta=0.2315; risk binding=EXTREME_CORR; corr regime=EXTREME |
| 2026-04-24 | TURNOVER_DELTA | 0.6751 | VOL | 0.0997 | -0.2582 | 0.36% | turnover delta=-0.2582 |
| 2025-07-17 | EXTREME_CORR,EXTREME_REGIME,ROUTE_LEG_DELTA | 0.6833 | EXTREME_CORR | 0.0998 | 0.0249 | 0.36% | max route leg delta=0.2163; risk binding=EXTREME_CORR; corr regime=EXTREME |

## Notes

- Read-only human-gate helper; no live config, feature flag, account state, signal journal, or order routing is changed.
- Forward returns use same-day route weights held over the next N trading days on the local price panel.
- This report does not approve scaler migration.  It only organizes WARN evidence for human review.
