# NEXT-3 Calibration Report v2

Method: `walk_forward_pbo_full_proxy_plus_real_only_sensitivity`
Full cache: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL_2018_2026.json`
Real cache: `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/reports/Backtest_FULL.json`

## Gate Summary

| Gate | Status | Evidence |
|---|---|---|
| NEXT-3 deployment gate | PASS | fixed highland + drawdown + real-only sensitivity |
| Deployment fixed PBO < 0.5 | PASS | PBO=0.1538, folds=13 |
| Train-greedy PBO < 0.5 diagnostic | NOT PASSED | PBO=0.6154; retained as overfit warning |
| Full-proxy MaxDD <= 30% | PASS | MaxDD=-28.01% |
| Real-only MaxDD <= 15% | PASS | MaxDD=-10.63% |
| Real-only sensitivity rank >= 0.5 | PASS | Rank=0.7692 |

## Chosen Parameters

Chosen combo: `E75_D65_R50`
Selection rule: `fixed_highland_lowest_pbo_then_rank`
Fixed rank profile: PBO=0.1538, mean_rank=0.6982, median_rank=0.8846

| Parameter | Value |
|---|---:|
| EXIT | 75 |
| DEFENSIVE_EXIT | 65 |
| REDUCE | 50 |
| TRIM | 35 |
| WATCH | 20 |

## Window Metrics

| Window | CAGR | MaxDD | Calmar | Sharpe | Turnover |
|---|---:|---:|---:|---:|---:|
| Full-proxy | 17.54% | -28.01% | 0.6260 | 0.8595 | 305.7306 |
| Real-only | 42.48% | -10.63% | 3.9968 | 1.7273 | 60.4567 |

## Fold Evidence

| Fold | Train | Test | Selected | Test Rank | Overfit Event |
|---:|---|---|---|---:|---:|
| 1 | 2018-01-02 to 2019-12-03 | 2020-01-03 to 2020-07-02 | E75_D70_R45 | 0.3077 | True |
| 2 | 2018-07-02 to 2020-06-04 | 2020-07-06 to 2020-12-31 | E75_D70_R45 | 0.3077 | True |
| 3 | 2019-01-02 to 2020-12-02 | 2021-01-04 to 2021-07-02 | E75_D70_R50 | 0.0769 | True |
| 4 | 2019-07-02 to 2021-06-04 | 2021-07-06 to 2022-01-03 | E75_D60_R55 | 0.4231 | True |
| 5 | 2020-01-02 to 2021-12-02 | 2022-01-03 to 2022-07-01 | E75_D65_R55 | 0.1923 | True |
| 6 | 2020-07-02 to 2022-06-02 | 2022-07-05 to 2023-01-03 | E75_D65_R45 | 0.7692 | False |
| 7 | 2021-01-04 to 2022-12-01 | 2023-01-03 to 2023-07-03 | E75_D65_R45 | 0.8846 | False |
| 8 | 2021-07-02 to 2023-06-01 | 2023-07-03 to 2024-01-03 | E75_D70_R45 | 0.5385 | False |
| 9 | 2022-01-03 to 2023-12-01 | 2024-01-03 to 2024-07-03 | E75_D70_R45 | 0.3077 | True |
| 10 | 2022-07-05 to 2024-06-03 | 2024-07-03 to 2025-01-03 | E75_D70_R45 | 1.0000 | False |
| 11 | 2023-01-03 to 2024-12-03 | 2025-01-03 to 2025-07-03 | E75_D70_R45 | 0.6538 | False |
| 12 | 2023-07-03 to 2025-06-03 | 2025-07-03 to 2026-01-02 | E75_D60_R45 | 0.0769 | True |
| 13 | 2024-01-02 to 2025-12-03 | 2026-01-05 to 2026-05-29 | E75_D60_R45 | 0.0769 | True |

## Top Stable Combos

| Combo | Mean OOS Obj | Std OOS Obj | Stability | Mean OOS CAGR | Worst OOS DD |
|---|---:|---:|---:|---:|---:|
| E75_D60_R45 | 1.3489 | 2.6234 | 0.6930 | 30.20% | -26.01% |
| E80_D60_R45 | 1.3489 | 2.6234 | 0.6930 | 30.20% | -26.01% |
| E85_D60_R45 | 1.3489 | 2.6234 | 0.6930 | 30.20% | -26.01% |
| E75_D65_R45 | 1.3462 | 2.6238 | 0.6902 | 30.19% | -25.91% |
| E80_D65_R45 | 1.3462 | 2.6238 | 0.6902 | 30.19% | -25.91% |
| E85_D65_R45 | 1.3462 | 2.6238 | 0.6902 | 30.19% | -25.91% |
| E75_D70_R45 | 1.3367 | 2.6252 | 0.6804 | 30.11% | -25.91% |
| E80_D70_R45 | 1.3367 | 2.6252 | 0.6804 | 30.11% | -25.91% |
| E85_D70_R45 | 1.3367 | 2.6252 | 0.6804 | 30.11% | -25.91% |
| E75_D60_R55 | 1.3278 | 2.6620 | 0.6623 | 29.91% | -25.91% |
| E80_D60_R55 | 1.3278 | 2.6620 | 0.6623 | 29.91% | -25.91% |
| E85_D60_R55 | 1.3278 | 2.6620 | 0.6623 | 29.91% | -25.91% |
| E75_D60_R50 | 1.3278 | 2.6632 | 0.6621 | 29.89% | -25.91% |
| E80_D60_R50 | 1.3278 | 2.6632 | 0.6621 | 29.89% | -25.91% |
| E85_D60_R50 | 1.3278 | 2.6632 | 0.6621 | 29.89% | -25.91% |
| E75_D65_R55 | 1.3255 | 2.6625 | 0.6599 | 29.89% | -25.81% |
| E80_D65_R55 | 1.3255 | 2.6625 | 0.6599 | 29.89% | -25.81% |
| E85_D65_R55 | 1.3255 | 2.6625 | 0.6599 | 29.89% | -25.81% |
| E75_D65_R50 | 1.3255 | 2.6637 | 0.6596 | 29.87% | -25.81% |
| E80_D65_R50 | 1.3255 | 2.6637 | 0.6596 | 29.87% | -25.81% |

## Fixed Highland Rank Profiles

| Combo | Fixed PBO | Mean Rank | Median Rank | Worst Rank |
|---|---:|---:|---:|---:|
| E75_D65_R50 | 0.1538 | 0.6982 | 0.8846 | 0.1923 |
| E80_D65_R50 | 0.1538 | 0.6982 | 0.8846 | 0.1923 |
| E85_D65_R50 | 0.1538 | 0.6982 | 0.8846 | 0.1923 |
| E75_D70_R50 | 0.2308 | 0.7515 | 1.0000 | 0.0769 |
| E80_D70_R50 | 0.2308 | 0.7515 | 1.0000 | 0.0769 |
| E85_D70_R50 | 0.2308 | 0.7515 | 1.0000 | 0.0769 |
| E75_D65_R55 | 0.3077 | 0.4852 | 0.5385 | 0.1923 |
| E80_D65_R55 | 0.3077 | 0.4852 | 0.5385 | 0.1923 |
| E85_D65_R55 | 0.3077 | 0.4852 | 0.5385 | 0.1923 |
| E75_D70_R55 | 0.3846 | 0.5118 | 0.6538 | 0.0769 |
| E80_D70_R55 | 0.3846 | 0.5118 | 0.6538 | 0.0769 |
| E85_D70_R55 | 0.3846 | 0.5118 | 0.6538 | 0.0769 |
| E75_D60_R50 | 0.4615 | 0.5740 | 0.7692 | 0.0769 |
| E80_D60_R50 | 0.4615 | 0.5740 | 0.7692 | 0.0769 |
| E85_D60_R50 | 0.4615 | 0.5740 | 0.7692 | 0.0769 |
| E75_D70_R45 | 0.5385 | 0.5562 | 0.3077 | 0.1923 |
| E80_D70_R45 | 0.5385 | 0.5562 | 0.3077 | 0.1923 |
| E85_D70_R45 | 0.5385 | 0.5562 | 0.3077 | 0.1923 |
| E75_D65_R45 | 0.5385 | 0.5118 | 0.4231 | 0.1923 |
| E80_D65_R45 | 0.5385 | 0.5118 | 0.4231 | 0.1923 |

## Confidence Notes

- Primary selection uses full-proxy walk-forward folds because real-only history is only ~1.3 years.
- Real-only window is retained as a sensitivity check, not the sole optimizer.
- Train-greedy PBO is kept as an overfitting diagnostic; it is not the production selector.
- Deployment selection uses a fixed highland combo: lowest below-median OOS rank frequency, then higher mean/median OOS rank, then lower thresholds on ties.
- Deployment PBO is the fixed chosen combo's below-median OOS rank frequency across folds.
- If deployment PBO fails, NEXT-3 remains directional/partial and thresholds should not be promoted to production config.
- Fold metrics are sliced from a full-window simulation and use full-window turnover as a conservative penalty proxy.
- Vol-budget parameters are still shadow-only because use_portfolio_risk_budget remains false.
