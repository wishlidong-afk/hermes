# P4 SizingOptimizer 骨架执行日志

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` §7 (核心 · SizingOptimizer) 的要求，构建全系统唯一的处置入口，取代所有 scaler 乘法链。吸收 E6/E8/E12/E15/E25/E26/E27。

## 已完成实现

### 1. 核心模块 `core/portfolio/sizing_optimizer.py`

**E6 杠杆衰减感知**
- `expected_leg_return(sym, leg_vol, leverage, hold_days, base_mu, cfg) -> float`
- 衰减公式：`drag = 0.5 * L * (L-1) * σ_daily² * hold_days`

**E26 分数 Kelly**
- `kelly_fraction(p_act, payoff_ratio, frac=0.3, ci_width=0.0) -> float`
- `f* = p - (1-p)/payoff_ratio`；fractional = `frac * f* * (1 - ci_width)`

**E12 流动性上限**
- `liquidity_cap(adv20, price, netliq, cfg) -> float`
- `days_to_liquidate = shares / (participation * ADV20)`；反推 max_weight

**E15 CPPI 地板**
- `cppi_exposure_cap(equity, floor, multiplier) -> float`
- `max_exposure = multiplier * (equity - floor)`；floor 棘轮

**E25 回撤厌恶效用**
- `dd_averse_utility(w, mu, cov, dd_aversion) -> float`
- `U(w) = w'mu - λ * sqrt(w'cov w)`

**核心入口**
- `optimize_targets(verdicts, risk_state, confidence, cfg) -> SizingDecision`
- 约束域：
  - R3 硬约束：`w_i ≤ rule_target_weight`（永不违反）
  - 置信收缩：`w_i ≤ rule_target * decision_confidence`
  - 波动预算：`sqrt(w'cov w) ≤ vol_budget`
  - 非负：`w_i ≥ 0`
- 求解器：scipy SLSQP 优先，3-leg 网格搜索 fallback
- 执行计划（E8）：硬阀门 → execute_now；非硬阀门 → TWAP 分批

### 2. 测试 `tests/test_sizing_optimizer.py`

| 测试 | 覆盖 |
|---|---|
| 杠杆衰减降低预期收益 | E6 |
| Kelly 正 edge → 正分数 | E26 |
| Kelly 无 edge → 0 | E26 |
| 流动性 cap 合理 | E12 |
| 零 ADV → 零 cap | E12 |
| CPPI 正 cushion | E15 |
| CPPI at floor → 0 | E15 |
| 高收益 → 高效用 | E25 |
| **R3 不变式 100%** | 核心 |
| 高波动 → 权重降低 | 边界 |
| 置信收缩 | 正常 |
| 硬阀门 → execute_now | E8 |
| 空 verdicts | 缺数据 |
| 确定性 | 不变式 |
| binding 标签正确 | 正常 |

## 设计决策

1. **R3 belt-and-suspenders**：约束域已限制 upper_bound，但 optimize_targets 出口再次 clamp，双保险永不违反。
2. **scipy 可选**：SLSQP 优先；import 失败或求解失败时回退到确定性网格搜索。3-leg 问题 11^3 = 1331 点，亚毫秒完成。
3. **不计算 Kelly 到 optimize_targets**：Kelly 目前作为独立工具函数提供，不直接影响 optimize_targets 的求解，等元模型 p_act 可用后再接入。
4. **E8 执行计划只读**：输出 execution_plan 仅供参考，不下单。

## 当前状态

P4 进入 `IN-PROGRESS / PHASE-I-SIZING-OPTIMIZER-DONE`。

ConfidenceSpine + RiskEngine + SizingOptimizer 三个核心组件已完成骨架。下一步：FactorLab / MarketContext / ValidationHarness 骨架。
