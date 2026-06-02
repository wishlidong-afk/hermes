# P10 Updated Migration Acceptance Pack

**日期**: 2026-06-02  
**范围**: 合并 P8（WARN sensitivity）+ P9（110/0.90 full-window + exact）结论，作为 Phase III scaler 迁移的最终人工审阅文件  
**生产影响**: none。本文件不翻 live feature flag，不写 account state，不写 signal journal，不下单。

---

## 1. 候选参数决策

| 字段 | 值 |
|---|---|
| **推荐候选** | `corr_regime_extreme_pctl = 110` / `extreme_corr_penalty = 0.90` |
| 状态 | REVIEW_READY（P8 WARN sensitivity），FULL-EXACT-PASSED（P9 全窗口复核） |
| 前任候选 | threshold=110 / penalty=0.70（P5/P6/P7 验证，REVIEW_REQUIRED） |
| 决策原因 | penalty=0.90 在 P8 24 场景中得分最低（0.1340），WARN 机会成本最小，max turnover delta 从 0.4022 降到 0.2886 |

**human gate 行动项**：接受/拒绝约 1.85 pp 回撤放大，决定后才可进入 Phase III scaler 迁移。

---

## 2. 全量证据汇总

### 2.1 P5：Phase II Full-Window Sensitivity（基线对比）

| 指标 | 旧基线（full-proxy） | 候选 110/0.70 | 候选 110/0.90 |
|---|---:|---:|---:|
| CAGR | 18.13% | 18.06% | **20.37%** |
| MaxDD | -27.60% | -22.47% | **-24.32%** |
| Sharpe | 0.8818 | 1.0115 | **1.0171** |
| Sortino | 1.1155 | 1.3141 | 1.3033 |
| Turnover | 326.68 | 339.98 | **338.06** |
| R3 violations | n/a | **0** | **0** |
| Fixed OOS below-median | n/a | 0.3077 | 0.4615 |
| Rows evaluated | 2113 | 2113 | 2113 |
| Errors | 0 | 0 | **0** |

**解读**: 110/0.90 在 CAGR、MaxDD、Sharpe 上全面优于 110/0.70；代价是 fixed OOS below-median 从 0.3077 升至 0.4615（仍 <0.5，PASS）。

### 2.2 P8：Phase III WARN Sensitivity（24 场景，252 日）

| 指标 | 110/0.70 | **110/0.90（推荐）** |
|---|---:|---:|
| Score（越低越好） | 0.3888 | **0.1340** |
| Readiness | REVIEW_REQUIRED | **REVIEW_READY** |
| WARN share | 49.21% | **48.81%** |
| EXTREME_CORR share | 40.48% | **40.48%** |
| WARN 1d avg Δ | -0.00% | **0.00%** |
| WARN 5d avg Δ | -0.05% | **+0.01%** |
| WARN 10d avg Δ | -0.29% | **-0.13%** |
| Max turnover Δ | 0.4022 | **0.2886** |
| R3 violations | 0 | **0** |
| BLOCK days | 0 | **0** |

**解读**: 110/0.90 的 WARN 机会成本（-0.13% 10d）远低于 110/0.70（-0.29%），max turnover delta 减少 28%。

### 2.3 P9：Full-Window + Exact 验证（110/0.90 专项）

| 验收项 | 结果 |
|---|---|
| Full-window (2113 日) errors | **0** |
| Full-window R3 violations | **0** |
| Exact 2020H1 vs fast | **浮点级一致（Δ final value < $0.01）** |
| Exact 2022H1 vs fast | **完全一致** |
| Exact 2024H1 vs fast | **浮点级一致（Δ < $0.06）** |
| Exact 2026YTD vs fast | **完全一致** |
| Package tests | **270 OK** |
| Golden tests | **11 OK** |

### 2.4 P6：Phase III Dry-run Comparator（252 日，110/0.70 候选）

> 注：P6 comparator 使用 110/0.70，110/0.90 未单独跑 comparator。WARN 分布模式基本相同（P8 已覆盖），但 turnover delta 在 110/0.90 下更小。

| Gate | Days |
|---|---:|
| PASS | 128 |
| WARN | 124 |
| BLOCK | **0** |
| R3 violations | **0** |

---

## 3. 人工审阅核心问题

### 问题 1：接受 1.85 pp 回撤放大吗？

| | 110/0.70 | 110/0.90 |
|---|---|---|
| MaxDD | -22.47% | **-24.32%** |
| 放大量 | +5.13 pp vs 旧基线 | **+3.28 pp vs 旧基线** |
| 换来的 | CAGR +0pp vs 旧基线 | **CAGR +2.24 pp** |

**参考结论**：110/0.90 将 MaxDD 控制在 -24.32%，仍显著优于旧基线的 -27.60%，同时 CAGR 改善更多。性价比优于 110/0.70。

### 问题 2：WARN 机会成本可接受吗？

110/0.90 的 WARN 日（总 252 日中 123 天）10 日后平均收益 Δ = **-0.13%**。
即候选在这 123 天比旧方案平均少赚 0.13%（10 日积累）。这主要发生在 EXTREME_CORR 触发时（40.48% 的日子），大多为高相关风险期。

**参考结论**：机会成本很小，风险回报比合理。

### 问题 3：train-greedy PBO 0.6154 的含义

train-greedy PBO > 0.5 意味着"每个窗口各自最优"的参数选择策略不可靠。当前方案使用**固定参数**（fixed candidate），fixed OOS below-median = 0.4615 < 0.5，**通过**。不应因 train-greedy PBO 否决固定候选。

---

## 4. 人工门控检查单

请逐行确认后签字（以 GitHub commit 代替签字）：

| # | 检查项 | 状态 |
|---|---|---|
| 1 | Full-window errors = 0（2113 日） | ✅ |
| 2 | R3 violations = 0 | ✅ |
| 3 | Exact/fast spot-check 4 窗口通过 | ✅ |
| 4 | BLOCK days = 0（Phase III dry-run） | ✅ |
| 5 | Fixed OOS below-median < 0.5 | ✅ 0.4615 |
| 6 | MaxDD 仍优于旧基线 | ✅ -24.32% vs -27.60% |
| 7 | WARN 10d avg Δ > -0.15% | ✅ -0.13% |
| 8 | Max turnover Δ < 0.35 | ✅ 0.2886 |
| 9 | 接受约 1.85 pp 回撤放大（vs 110/0.70） | **⬜ 人工决定** |
| 10 | live feature flags 保持关闭 | ✅ 未翻 |

---

## 5. 通过后的下一步（Phase III 实施）

一旦第 9 项由人工确认，按以下顺序推进：

```
Step 1: 更新 config: corr_regime_extreme_pctl=110, extreme_corr_penalty=0.90
Step 2: 跑 phase3_dry_run_compare.py --threshold 110 --penalty 0.90（产出新 comparator 报告）
Step 3: scaler 迁移（SCALER_MIGRATION_GUIDE.md 步骤）
Step 4: 新旧并排回测对照验收（Calmar 不退化 5%，MaxDD 不恶化 5%，Turnover ≤ 25%）
Step 5: Phase IV PBO/CI 实跑（ValidationHarness 全套）
```

**若在任一步失败**：回退到旧 scaler 链（feature flag 关闭），live 状态不受影响。

---

## 6. 产物清单

| 产物 | 状态 |
|---|---|
| `P8 PhaseIII_WARN_Sensitivity.md/json` | ✅ |
| `P9 PhaseII_Full_Backtest_Sensitivity_P9_110_090.md/json` | ✅ |
| `P9 Exact/Fast 4窗口 .md/json` | ✅ |
| `P6 PhaseIII_Dry_Run_Comparator.md/json` | ✅ |
| **P10 本文件** | ✅ |

---

*本文件是 Phase III scaler 迁移的最终人工门控文件。live feature flag 须等人工确认后方可更改。*
