# P12 Gate 2 — SizingOptimizer 替换 scaler 乘法链

**时间**: 2026-06-02
**范围**: 用 `optimize_targets` 替换生产 `pipeline.py` 中的 `size_portfolio` 乘法链，完成 Gate 2（单一处置入口）
**生产影响**: `pipeline.py` 已修改，实际仓位计算路径变更。live 开关仍关闭，advisory-only。

## 变更内容

### `pipeline.py`

| 变更点 | 旧 | 新 |
|---|---|---|
| import | `from .core.portfolio.sizing import size_portfolio` | 新增 `build_risk_state`, `optimize_targets`, `Verdict`, `ConfidenceState` |
| 核心调用 | `sizing = size_portfolio(..., gross_scaler=...)` | `sizing = _optimize_sizing(bundles, histories, portfolio_risk, config)` |
| 输出格式 | `SizingDecision.to_dict()` (旧) | `_SizingProxy.to_dict()` (兼容旧格式 + 新字段) |

### 新增 `_optimize_sizing()` 函数

步骤：
1. `ScoreResult` → `Verdict`（sleeve_cap × (1-sell_fraction) = rule_target_weight）
2. `build_risk_state(leg_returns, target_weights, None, cfg)` → `RiskState`（110/0.90 参数已生效）
3. `portfolio_risk.effective_gross_scaler` → `ConfidenceState`（置信代理）
4. `optimize_targets(verdicts, risk_state, confidence, cfg)` → `SizingDecision`
5. 包装为 `_SizingProxy`（保持 `to_dict()` 向后兼容）

### 安全 fallback

`optimize_targets` 抛异常时自动回退到 `size_portfolio`（旧乘法链），保证系统不中断。

### 新增 `_SizingProxy` 类

兼容旧 `SizingDecision` 的所有输出字段，并新增：
- `binding_constraint`：RiskEngine 绑定约束来源
- `execution_mode`：`execute_now`（硬阀门）或 `twap_3_slices`
- `optimizer_confidence`：置信度
- `sizing_engine`: `"optimize_targets_v1"`（迁移标记）

## 验收结果

| 检查项 | 结果 |
|---|---|
| 270 package tests | **OK** |
| R3 不变式（2026-05-29） | **PASS**：FNGU 0.18≤0.20, MSTR 0≤0, SOXL 0.108≤0.12 |
| sizing_engine 标记 | `optimize_targets_v1` 出现在所有标的 |
| 旧字段保留 | `target_weight`, `vol_scaler`, `gross_scaler`, `clamp_applied` 均在 `to_dict()` |
| 实时运行时间 | ~1.0 秒（无性能退步） |

## 系统级 7 道总闸进度

| # | 总闸 | 状态 |
|---|---|---|
| 1 | 单一风险源（唯一 cov） | ✅ RiskEngine |
| **2** | **单一处置入口（无 scaler 连乘）** | ✅ **DONE — optimize_targets 唯一入口** |
| 3 | R3 100% | ✅ 当日验证 PASS |
| 4-7 | 其余 | 骨架就绪，待全量验证 |

## 状态

P12: **DONE / GATE-2-COMPLETE**。生产 pipeline 现在通过 `optimize_targets` 产出所有仓位。
