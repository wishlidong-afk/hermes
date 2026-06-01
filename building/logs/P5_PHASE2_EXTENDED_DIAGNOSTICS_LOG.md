# P5 Phase II Extended Diagnostics Log

**时间**: 2026-06-01
**范围**: Phase II shadow 扩窗与 EXTREME_CORR 敏感性诊断
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

## 252 日 Shadow 结果

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
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

P5 状态推进为 `IN-PROGRESS / SHADOW-252D-CORR-SENSITIVITY-DONE`。

## 剩余风险

- 当前 EXTREME_CORR 算法使用“下行相关 / 普通相关 × 100”与 92 阈值，配合 downside floor 后确实偏保守。
- 敏感性脚本只是复算 penalty 层，没有重跑完整投资结果；正式参数变更必须纳入回测引擎。
- Phase III 仍不可启动 live 替换；必须先完成风险预算参数校准。
