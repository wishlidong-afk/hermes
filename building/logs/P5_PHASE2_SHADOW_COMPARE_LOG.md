# P5 Phase II Shadow Compare Log

**时间**: 2026-06-01
**范围**: P4 统一管线落地后的 Phase II 只读影子对照
**生产影响**: none，未翻 live 开关，未改实盘裁决

## 本次搭建内容

- 新增 `scripts/phase2_shadow_compare.py`，从 `reports/Backtest_FULL.json` 读取最近 N 个历史评分日，接入新的 `score_pipeline(...)` 做只读回放。
- 使用历史 backtest 行内的模块分、状态与 `sell_fraction` 作为 scorer/verdict 输入，避免 shadow 对照混入新打分器误差。
- 输出两份产物：
  - `reports/PhaseII_Shadow_Compare.json`
  - `reports/PhaseII_Shadow_Compare.md`
- 修复 Phase II 回放时的数值稳定性：
  - `RiskEngine` 对 return series / return DataFrame 统一转数值、去除 `NaN/inf`。
  - `portfolio_cvar` 改用 `np.dot(R, w)`，规避 macOS Accelerate 对有限 F-contiguous 矩阵乘法的假阳性 RuntimeWarning。
  - `SizingOptimizer` 只在 SLSQP 内部屏蔽“越界一步后已裁剪”的例行 RuntimeWarning。
- 新增 RiskEngine 单测覆盖非有限 return 输入。

## Shadow 对照结果

| 指标 | 结果 |
|---|---:|
| 回放窗口 | 最近 20 个交易日 |
| rows evaluated | 20 |
| errors | 0 |
| R3 violations | 0 |
| max abs weight delta | 0.2747 |
| confidence mode | NORMAL × 20 |

## 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_risk_engine hermes_escape_top.tests.test_sizing_optimizer`: 31 tests OK。
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`: 245 tests OK。
- ✅ `python3 -m unittest discover -s tests`: 11 tests OK。
- 备注：golden 测试仍出现系统 Python `urllib3 NotOpenSSLWarning`，不影响测试结果。

## 验收结论

Phase II shadow 对照已经可重复运行，并证明新管线满足：

- 不改变生产/live 状态；
- 不违反 R3 规则上限；
- 数据置信度在最近 20 日保持 NORMAL；
- 风险层可以在真实本地历史数据上完成统一 covariance / CVaR / sizing 回放。

## 剩余风险

- 最近 20 日多次触发 `EXTREME_CORR`，shadow gross scaler 明显低于旧 backtest gross scaler；这说明新版风险层更保守，但还需要在 Phase III 之前做参数解释、压力测试与业务口径校准。
- Shadow compare 当前使用历史分数作为输入，属于管线/风险/仓位对照，不等同于完整新评分器回测。
