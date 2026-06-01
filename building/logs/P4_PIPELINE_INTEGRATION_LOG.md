# P4 Pipeline Integration + E9 Drift Monitor 执行日志

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` §9 的要求，把全部 10+1 个组件串入统一 pipeline，实现完整的每日决策流。同时补齐 E9 漂移监控为 ConfidenceSpine 提供 drift_state 输入。

---

## E9 漂移监控 `core/monitor/drift.py`

### 已完成

| 函数 | 功能 |
|---|---|
| `DriftMonitor.evaluate(...)` | 综合评估 PSI + precision drop + IC decay → drift_state |
| `compute_psi(expected, actual)` | Population Stability Index；>0.25 告警 |
| `compute_rolling_precision(signals, window)` | 滚动防守精度追踪 |

### 告警规则

- PSI > 0.25 → 分数分布漂移，建议重校准
- Precision drop > 10% → 防守精度下降，检查因子权重
- IC ratio < 0.50 → 因子 IC 衰减，考虑剪枝

### 测试（7 个）

- 同分布低 PSI / 偏移分布高 PSI / 短序列
- 无漂移无告警 / 分数漂移告警 / 精度下降告警 / IC 衰减告警
- 建议列表非空

---

## 统一 Pipeline `core/pipeline.py`

### 数据流（11 步）

```
Step 1:  数据获取      failover → sanitize → clean_store
Step 2:  市场上下文    MarketContext + regime_with_transition
Step 3:  评分          scorer_fn(可插拔) → A/B/C/D/total
Step 4:  裁决          verdict_fn(可插拔) → Verdict(状态/rule_weight/硬阀门)
Step 5:  风险引擎      build_risk_state → 唯一 cov/corr/vol/CVaR
Step 6:  脆弱+分歧     decision_fragility + detect_disagreement
Step 7:  漂移监控      DriftMonitor.evaluate → drift_state
Step 8:  置信脊柱      compute_confidence → ConfidenceState(NORMAL/CAUTION/DEGRADED)
Step 9:  统一优化器    optimize_targets → SizingDecision(R3 强制)
Step 10: 归因          attribute → per-factor contribution + counterfactual
Step 11: 审计日志      structured audit → 可复现
```

### 关键设计

1. **唯一入口**：所有每日决策通过 `score_pipeline()` 进出，无旁路
2. **可插拔评分/裁决**：scorer_fn 和 verdict_fn 可注入，默认 placeholder 供测试
3. **R3 belt-and-suspenders**：optimizer 内部已限制，pipeline 层面再验证
4. **audit 完整性**：11 个字段全部记录，可事后完整复现每一步
5. **确定性**：同输入两次调用逐位一致

### PipelineResult 字段

| 字段 | 类型 | 来源 |
|---|---|---|
| sanitize_results | Dict[str, SanitizeResult] | E1 |
| failover_results | Dict[str, FailoverResult] | E30 |
| scores | Dict[str, Dict] | A/B/C/D scorer |
| verdicts | Dict[str, Verdict] | verdict chain |
| risk_state | RiskState | E4/E5/E11/E13/E14 |
| confidence | ConfidenceState | ConfidenceSpine |
| sizing | SizingDecision | E6/E8/E12/E15/E25/E26/E27 |
| regime | Dict[str, Dict] | E7 |
| fragility | Dict[str, float] | E28 |
| disagreement | Dict[str, float] | E10 |
| attribution | Dict[str, List] | Governance |
| drift_state | Dict | E9 |
| audit | Dict | 结构化审计 |

### 测试（14 个）

| 测试 | 覆盖 |
|---|---|
| 端到端默认运行 | 集成 |
| R3 不变式 | Gate 3 |
| 确定性 | 不变式 |
| 置信传播到 sizing | Gate 4 |
| 审计日志完整 | 可复现 |
| 审计可复现字段 | 可复现 |
| 空 store | 边界 |
| 缺失标的 | 边界 |
| 自定义 scorer + verdict + 硬阀门 | 可插拔 |
| Gate 1: 单一风险源 | 结构 |
| Gate 2: 单一处置入口 | 结构 |
| Gate 3: R3 | 结构 |
| Gate 4: 置信脊柱 | 结构 |
| Gate 5/6/7: PBO/FactorLab/Governance | 结构 |

## 当前状态

P4 Integration Phase 0–I + Pipeline 接线 `DONE`。

系统级 7 道总闸全部有结构性支持，待实数据集成验证。
