# P9 Phase III 110/0.90 Full-Window + Exact Verification Log

**时间**: 2026-06-02  
**范围**: 对 P8 推荐候选 `EXTREME_CORR threshold=110 / penalty=0.90` 做 full-window 回测复核与 exact optimizer 抽查  
**生产影响**: none。未翻 live feature flag，未写 account state，未写 signal journal，未下单。

## 本次搭建内容

- 复用既有 `scripts/phase2_full_backtest_sensitivity.py`，未新增生产逻辑。
- 对 `threshold=110 / penalty=0.90` 跑 2018-01-02 至 2026-05-29 全窗口单场景敏感性复核。
- 对 4 个代表窗口跑 exact optimizer 与 fast optimizer 对照：
  - `2020H1`: 2020-01-03 至 2020-07-02
  - `2022H1`: 2022-01-03 至 2022-07-01
  - `2024H1`: 2024-01-03 至 2024-07-03
  - `2026YTD`: 2026-01-05 至 2026-05-29
- 生成 P9 独立报告与 JSON，避免覆盖 P5/P8 历史审计产物。

## 全窗口结果

| 指标 | P5 当前候选 110/0.70 | P9 复核候选 110/0.90 | 变化 |
|---|---:|---:|---:|
| rows evaluated | 2113 | 2113 | 0 |
| errors | 0 | 0 | 0 |
| R3 violations | 0 | 0 | 0 |
| final value | $401,635.03 | $472,466.65 | +$70,831.63 |
| CAGR | 18.06% | 20.37% | +2.31 pp |
| max drawdown | -22.47% | -24.32% | -1.85 pp |
| max drawdown window | 2021-11-19 -> 2023-04-26 | 2021-02-12 -> 2023-05-12 | shifted / longer |
| Sharpe | 1.0115 | 1.0171 | +0.0055 |
| Sortino | 1.3141 | 1.3033 | -0.0108 |
| turnover | 339.9802 | 338.0594 | -1.9208 |
| deflated Sharpe | 0.8791 | 0.8770* | -0.0021 |
| avg gross | 0.8447 | 0.9205 | +0.0758 |
| min gross | 0.3595 | 0.4571 | +0.0975 |
| max abs weight delta | 0.1698 | 0.1675 | -0.0023 |
| fixed OOS below-median share | 30.77% | 46.15% | +15.38 pp |

`*` P9 单场景报告自身的 deflated Sharpe 为 `0.9307`，但单场景 OOS/rank 诊断不具备网格比较意义；上表采用 P5 21 场景 full-window grid 中同一 `110/0.90` 场景的可比 DSR/OOS 字段。

## P8 WARN 审阅对照

| 指标 | 110/0.70 | 110/0.90 |
|---|---:|---:|
| readiness | REVIEW_REQUIRED | REVIEW_READY |
| WARN share | 49.21% | 48.81% |
| EXTREME_CORR share | 40.48% | 40.48% |
| WARN 10d candidate-old avg | -0.29% | -0.13% |
| max turnover delta | 0.4022 | 0.2886 |
| review score | 0.3888 | 0.1340 |

## Exact / Fast 抽查

| Window | Mode | Rows | Errors | R3 | Final Value | CAGR | MaxDD | Sharpe | Turnover | Avg Gross | Max Weight Delta |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020H1 | exact | 126 | 0 | 0 | $114,315.01 | 31.22% | -10.66% | 1.2823 | 13.1918 | 0.9599 | 0.1435 |
| 2020H1 | fast | 126 | 0 | 0 | $114,315.01 | 31.22% | -10.66% | 1.2823 | 13.1918 | 0.9599 | 0.1435 |
| 2022H1 | exact | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 | 1.0000 | 0.0440 |
| 2022H1 | fast | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 | 1.0000 | 0.0440 |
| 2024H1 | exact | 126 | 0 | 0 | $145,591.56 | 113.68% | -10.38% | 2.9913 | 20.0377 | 0.7995 | 0.1094 |
| 2024H1 | fast | 126 | 0 | 0 | $145,591.62 | 113.68% | -10.38% | 2.9913 | 20.0377 | 0.7995 | 0.1094 |
| 2026YTD | exact | 101 | 0 | 0 | $134,000.54 | 109.61% | -8.64% | 3.5696 | 26.2505 | 0.8923 | 0.0997 |
| 2026YTD | fast | 101 | 0 | 0 | $134,000.54 | 109.61% | -8.64% | 3.5696 | 26.2505 | 0.8923 | 0.0997 |

最大 exact/fast 差异出现在 `2024H1`，final value 约 `$0.06`，CAGR 差异约 `0.0002 pp`，不影响验收结论。

## 解读

- `110/0.90` 通过 P9 full-window 复核：无 errors、无 R3 violations、收益与换手指标稳定。
- `110/0.90` 通过 exact optimizer 抽查：四个代表窗口的 exact/fast 差异为浮点级。
- 相对 `110/0.70`，`110/0.90` 的主要优势是：
  - full-window CAGR 高约 `2.31 pp`；
  - final value 高约 `$70.8k`；
  - turnover 略低；
  - P8 WARN 机会成本与最大换手差显著下降。
- 主要代价是：
  - max drawdown 从 `-22.47%` 放大到 `-24.32%`；
  - P5 21 场景 grid 中 fixed OOS below-median share 从 `30.77%` 升到 `46.15%`，说明它不是 OOS 排名最漂亮的点，只是 Phase III WARN 可解释性更好。

## 当前结论

P9 状态为 `DONE / FULL-EXACT-PASSED / REVIEW-GATED`。

`threshold=110 / penalty=0.90` 可以进入 updated migration acceptance pack，作为 `110/0.70` 的 Phase III 替代候选继续 shadow-only 审核；但不应直接自动上线。上线前必须由人工确认是否接受约 `1.85 pp` 的最大回撤放大，且 live feature flag 继续保持关闭。

## 验收结果

| 验收项 | 结果 |
|---|---|
| full-window run | PASS |
| exact/fast spot-check | PASS |
| package tests | 270 tests OK |
| golden tests | 11 tests OK（仅 urllib3/LibreSSL 环境警告） |

## 产物

- `reports/PhaseII_Full_Backtest_Sensitivity_P9_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Exact_2020H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Fast_2020H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Exact_2022H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Fast_2022H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Exact_2024H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Fast_2024H1_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Exact_2026YTD_110_090.md/json`
- `reports/PhaseII_Full_Backtest_Sensitivity_P9_Fast_2026YTD_110_090.md/json`
- `reports/P9_PHASE3_110_090_FULL_EXACT_LOG.md`

## 下一步

1. 生成 updated migration acceptance pack，把 P8/P9 结论合并成可审阅的参数迁移提案。
2. 将 `110/0.90` 标成 shadow-only candidate；live flags 保持关闭。
3. 后续若要进一步压回撤，可另开一轮 drawdown-aware grid，不在 P9 中混入新变量。
