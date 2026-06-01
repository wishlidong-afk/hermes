# Phase II–IV Rollout Plan（分阶段上线计划）

更新时间：2026-06-01

---

## 总览

Phase 0–I 地基已完成（12 组件 + 106 测试）。Phase II–IV 是逐步启用、替换、验证的过程，每阶段有明确的验收标准和回退策略。

```
Phase II  ─ 风险与信号（shadow 对照）
Phase III ─ 统一处置（替换旧 scaler 链）
Phase IV  ─ 验证与治理（全闸通过）
```

---

## Phase II: 风险与信号（Shadow 对照）

### 目标

启用 RiskEngine + ConfidenceSpine + MarketContext + DriftMonitor 在 **shadow 模式**下运行，与现有评分/裁决链并行，对比输出差异但不改变实际决策。

### 启用的 feature flags

```python
use_risk_engine: True
use_confidence_spine: True
use_market_context: True
use_drift_monitor: True
```

### 操作步骤

1. **Shadow 接入**
   - 在现有 pipeline 的评分/裁决链之后，追加调用 `build_risk_state()` 和 `compute_confidence()`
   - 输出写入 audit log 的 `shadow_risk` 和 `shadow_confidence` 字段
   - **不改变** `gross_scaler` / `v3_target` / 实际裁决

2. **对照报告**
   - 每日比较 shadow RiskEngine 的 `gross_scaler` vs 现有 scaler 链的 `gross_scaler`
   - 记录差异 > 5% 的日期和原因
   - 追踪 ConfidenceSpine mode 分布（NORMAL/CAUTION/DEGRADED 各占多少天）

3. **E 系列插件调优**
   - E4: 调 `downside_q`、`cvar_budget` 使 CVaR scaler 与历史 MaxDD 一致
   - E5: 验证 HAR-RV 样本外 MSE < EWMA
   - E7: 检查体制标签在 2020-03、2022 Q2 等已知拐点的准确性
   - E11: EWMA lambda 敏感性（0.90/0.94/0.97）
   - E17: 验证 BTC→MSTR 领先滞后是否稳定

### 验收标准

- [ ] Shadow RiskEngine 在 2020-03 崩盘前 `gross_scaler` < 0.7（vs 旧链）
- [ ] ConfidenceSpine 在数据异常注入后正确降级 DEGRADED
- [ ] HAR-RV 在 2018-2026 回放中样本外 MSE < EWMA
- [ ] DriftMonitor 在已知分布漂移段（如 2022→2023 转换）PSI > 0.25
- [ ] Shadow 运行≥20 个交易日无异常

### 回退策略

关闭 feature flag → 系统回到 Phase I 状态。Shadow 数据保留在 audit log 中。

---

## Phase III: 统一处置（替换旧 Scaler 链）

### 目标

用 SizingOptimizer 替换现有的 `gross_scaler * vol_target_scaler * ...` 乘法链，成为唯一的仓位决策入口。

### 启用的 feature flags

```python
use_sizing_optimizer: True   # NEW
use_governance: True         # NEW
```

### 操作步骤

1. **旧链识别与删除**
   - 在现有代码中搜索所有 `gross_scaler`、`vol_target_scaler`、`scaler` 乘法操作
   - 每个替换为 `sizing.target_weights[sym]` 的直接引用
   - 删除旧的 `scale_position()`、`apply_scalers()` 等函数

2. **R3 验证**
   - 回测全窗口：每日每标的 `w_i ≤ rule_target_weight`
   - 异常日（硬阀门触发日）额外验证 `w_i = 0`

3. **对照回测**
   - 新优化器 vs 旧 scaler 链的并排回测
   - 要求：风险调整收益 ≥ 旧链 且 MaxDD ≤ 旧链
   - Calmar 不退化、Turnover 增幅 ≤ 25%

4. **Execution Plan**
   - 硬阀门 → `execute_now`
   - 非硬阀门 → `twap_3_slices`
   - 验证分批执行不影响回测收益

### 验收标准

- [ ] R3 不变式 OOS 100%（无一日违反）
- [ ] 新优化器 Calmar ≥ 旧 scaler 链
- [ ] 新优化器 MaxDD ≤ 旧 scaler 链
- [ ] Turnover 增幅 ≤ 25%
- [ ] 旧代码中无残留 scaler 乘法
- [ ] `binding_constraint` 每日每标的正确标注

### 回退策略

关闭 `use_sizing_optimizer` → 恢复旧 scaler 链（保留但注释的旧代码）。

---

## Phase IV: 验证与治理（全闸通过）

### 目标

启用 ValidationHarness + Governance 全套，运行完整验证套件，通过 7 道系统级总闸。

### 启用的 feature flags

```python
use_validation_harness: True  # NEW
use_factor_calibration: True  # NEW (FactorLab)
```

### 操作步骤

1. **CPCV + PBO 实跑**
   - 用 2018-2026 回放数据跑 `cpcv_splits()` + `prob_backtest_overfitting()`
   - 目标：PBO < 0.5

2. **Bootstrap CI**
   - 2000 次块重采样 → Calmar/MaxDD/Sortino 95% CI
   - 关键指标 CI 不跨 0

3. **对抗 AUC**
   - 训练集 vs 最近 60 天特征 → AUC ≤ 0.65

4. **Factor Health Report**
   - FactorLab.factor_ic() + cluster_and_prune() → `Factor_Health.md`
   - 死因子标注；冗余降权确认；ECE < 0.15

5. **熔断测试**
   - 注入：坏数据 → ConfidenceSpine DEGRADED
   - 注入：强分歧 → Governance REVIEW_REQUIRED
   - 注入：高脆弱度 → ConfidenceSpine CAUTION
   - 注入：漂移 → DriftMonitor alert

6. **归因完整性**
   - 每个决策可追溯到具体因子贡献
   - leave-one-out counterfactual 有意义

### 验收标准（7 道总闸）

| # | 总闸 | 验收 |
|---|---|---|
| 1 | 单一风险源 | 所有派生量引用同一 cov；改一处全联动 |
| 2 | 单一处置入口 | 无手工 scaler 连乘；目标仓位全来自 optimize_targets |
| 3 | R3 100% | 任一 OOS 日 w_i ≤ rule_target_i |
| 4 | 置信脊柱贯通 | 每决策携带 ConfidenceState；四类异常正确降级 |
| 5 | PBO < 0.5 + CI + AUC ≤ 0.65 | 实数据验证通过 |
| 6 | 因子健康 | Factor_Health.md 已出；ECE < 0.15 |
| 7 | 可解释可治理 | 归因/分歧/熔断全部通过端到端测试 |

### 回退策略

逐个关闭 feature flag。治理层不影响决策（仅监控/告警）。

---

## 风险声明

- 所有 feature flag 默认 OFF，由人决定何时开启
- Phase II shadow 不改变实际决策
- Phase III 替换前必须有并排回测达标
- Phase IV PBO/CI 不达标则停在 shadow
- 元模型（use_meta_label）始终独立于此流程，需满足解锁门才训练
- **绝不下单**；所有输出仅供参考

---

## 时间线估算

| Phase | 依赖 | 估算 |
|---|---|---|
| Phase II | 本地运行环境 + 真实 store | 3-5 交易日 shadow |
| Phase III | Phase II 验收 | 2-3 天回测 + 对照 |
| Phase IV | Phase III 验收 | 3-5 天验证套件 |
| **合计** | - | **~2-3 周** |
