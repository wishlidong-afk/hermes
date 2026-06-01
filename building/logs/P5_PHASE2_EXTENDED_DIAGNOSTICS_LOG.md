# P5 Phase II Extended Diagnostics Log

**时间**: 2026-06-01
**范围**: Phase II shadow 扩窗、EXTREME_CORR 敏感性诊断、full-window backtest sensitivity
**生产影响**: none，未翻 live 开关，未改实盘裁决参数

## 本次搭建内容

- `RiskEngine.estimator_meta` 新增风险解释字段：
  - `corr_mean`
  - `downside_corr_mean`
  - `downside_corr_ratio_score`
  - `corr_elevated_threshold`
  - `corr_extreme_threshold`
  - `gross_before_corr_penalty`
  - `extreme_corr_penalty`
- `scripts/phase2_shadow_compare.py` 升级为 252 日扩窗诊断报告：
  - 统计 confidence modes、risk bindings、correlation regimes；
  - 输出 VOL/CVAR/EXTREME_CORR 对 gross scaler 的贡献；
  - 给出 most defensive rows，解释最保守日是哪几天、为何压仓。
- 新增 `scripts/phase2_corr_sensitivity.py`：
  - 读取 `PhaseII_Shadow_Compare.json`；
  - 只重算 correlation-regime penalty 层；
  - 对 `threshold=[92,100,110,120,130,140,150]` 与 `penalty=[0.70,0.80,0.90]` 做只读敏感性分析；
  - 输出 `PhaseII_Corr_Sensitivity.md/json`。
- 修复 `SizingOptimizer` 的 shadow-mode 接线：
  - `risk_state.gross_scaler` 现在会参与目标仓位上限；
  - 绑定标签新增 `RISK_GROSS`；
  - shadow expected-return proxy 与 `dd_aversion` 对齐，避免没有 alpha 模型时把 HOLD 袖套错误压到 0。

## 252 日 Shadow 结果

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
| max abs weight delta | 0.1592 |
| confidence mode | NORMAL × 252 |
| avg shadow gross | 0.7229 |
| min shadow gross | 0.4111 |
| avg gross delta | -0.2771 |
| EXTREME_CORR share | 78.57% |
| avg ordinary corr mean | 0.5135 |
| avg downside corr mean | 0.5567 |
| avg downside/ordinary ratio score | 115.2734 |

## Corr Sensitivity 结论

当前默认 `threshold=92 / penalty=0.70` 过于敏感：在 252 日 replay 中命中率 78.57%，更像“长期降档”而非“极端闸门”。

只读 review candidate：

| 参数 | 结果 |
|---|---:|
| threshold | 110 |
| penalty | 0.70 |
| hit share | 40.48% |
| avg gross | 0.8273 |
| min gross | 0.5770 |

该候选只作为 Phase III 前的校准靶子，不得直接上线。下一步必须用 full backtest、walk-forward 与 Phase III migration gates 验证。

## 验收结论

P5 状态先推进为 `IN-PROGRESS / SHADOW-252D-CORR-SENSITIVITY-DONE`。

## Full Backtest Sensitivity 追加

新增 `scripts/phase2_full_backtest_sensitivity.py`，把相关闸候选接入 2018-01-02→2026-05-29 的完整资金曲线与 walk-forward 诊断。该脚本仍为只读 shadow：

- 默认使用确定性的 `R3 × confidence × risk_gross` 上界投影，避免 21 个场景 × 2113 日重复 SLSQP；
- 价格面板一次构建，内部快速模拟器预计算日收益矩阵；
- 保留 `--exact-optimizer` 供小窗口慢速复核；
- 输出 `PhaseII_Full_Backtest_Sensitivity.md/json`。

### 结果摘要

| 指标 | 结果 |
|---|---:|
| rows evaluated | 2113 |
| errors | 0 |
| scenario count | 21 |
| R3 violations | 0 |
| baseline final | $403,631.36 |
| baseline CAGR | 18.13% |
| baseline MaxDD | -27.60% |
| baseline Sharpe | 0.8818 |

Review candidate 仍为 `threshold=110 / penalty=0.70`：

| 指标 | 结果 |
|---|---:|
| hit share | 39.71% |
| avg gross | 0.8447 |
| min gross | 0.3595 |
| final value | $401,635.03 |
| CAGR | 18.06% |
| MaxDD | -22.47% |
| Sharpe | 1.0115 |
| DSR | 0.8791 |
| fixed OOS below-median share | 0.3077 |
| mean OOS rank | 8.7692 / 21 |

治理解释：

- `train-greedy PBO=0.6154`，说明逐窗口贪心选参明显过拟合，不得上线；
- 固定候选 `110/0.70` 的 OOS below-median share 为 0.3077，作为固定规则比贪心选参健康；
- 相比旧 baseline，候选 CAGR 基本持平（18.06% vs 18.13%），MaxDD 从 -27.60% 改善到 -22.47%，Sharpe 从 0.8818 提升到 1.0115。

## 最终验收结论

P5 状态当时推进为 `IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE`；该状态随后已由 P6 dry-run comparator 补齐为 `DONE / DRY-RUN-PACKAGE-READY`。

## Exact Optimizer Spot-check 追加

为验证 full-window sensitivity 默认使用的快速上界投影是否偏离 SLSQP 精确优化，`phase2_full_backtest_sensitivity.py` 已新增：

- `--start` / `--end` 日期过滤；
- `--suffix` 独立输出文件后缀；
- `--exact-optimizer` 慢速精确路径；
- 对 date filter / suffix / fast simulator 的单测。

抽样结果：

| 窗口 | 模式 | rows | errors | R3 | Final | CAGR | MaxDD | Sharpe | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020-01-03→2020-07-02 | exact | 126 | 0 | 0 | $113,421.98 | 29.17% | -9.08% | 1.3104 | 12.9647 |
| 2020-01-03→2020-07-02 | fast | 126 | 0 | 0 | $113,421.97 | 29.17% | -9.08% | 1.3104 | 12.9647 |
| 2022-01-03→2022-07-01 | exact | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 |
| 2022-01-03→2022-07-01 | fast | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 |
| 2024-01-03→2024-07-03 | exact | 126 | 0 | 0 | $140,828.27 | 99.82% | -8.38% | 3.1997 | 19.7482 |
| 2024-01-03→2024-07-03 | fast | 126 | 0 | 0 | $140,828.27 | 99.82% | -8.38% | 3.1997 | 19.7482 |
| 2026-01-05→2026-05-29 | exact | 101 | 0 | 0 | $134,157.91 | 110.23% | -7.57% | 3.7111 | 26.6084 |
| 2026-01-05→2026-05-29 | fast | 101 | 0 | 0 | $134,157.91 | 110.23% | -7.57% | 3.7111 | 26.6084 |

四个代表窗口 exact 与 fast 仅有浮点级微差，R3 全部为 0，说明当前快速投影在代表窗口与 SLSQP 精确优化路径一致；下一步可进入 dry-run 验收包设计。

## Dry-run Acceptance Pack

新增 `P5_DRY_RUN_ACCEPTANCE_PACK.md`：

- 汇总 baseline vs 110/0.70 candidate；
- 汇总 walk-forward governance、exact spot-check、human gate checklist；
- 明确结论：可进入 shadow dry-run package，不可 live promotion。

后续状态：daily old-vs-new comparator 已在 P6 完成，252 日结果为 errors=0、R3=0、PASS=128、WARN=124、BLOCK=0。下一步是人工审阅 WARN 日期。

## 剩余风险

- 当前 EXTREME_CORR 算法使用“下行相关 / 普通相关 × 100”与 92 阈值，配合 downside floor 后确实偏保守。
- full-window sensitivity 已完成，但默认使用快速上界投影；Phase III dry-run 前建议用 `--exact-optimizer` 抽样复核关键窗口。
- Phase III 仍不可启动 live 替换；必须先完成 dry-run、人审与 feature flag 人工开关。
