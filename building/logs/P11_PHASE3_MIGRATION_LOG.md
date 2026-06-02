# P11 Phase III Scaler Migration 执行日志

**时间**: 2026-06-02
**范围**: 人工确认 110/0.90 → config 更新 → 新 dry-run comparator → 迁移验证
**生产影响**: config.json 参数已更新并生效。live 运行时将使用新阈值。live 开关原则上仍为 OFF（不进行实际交易）。

## 人工决策记录

用户于 2026-06-02 确认接受以下 trade-off：

> "可以，继续吧"

| 决策项 | 结果 |
|---|---|
| 候选参数 | `corr_regime_extreme_pctl=110 / extreme_corr_penalty=0.90` |
| 接受 MaxDD 从 -22.47% 放大到 -24.32%（1.85 pp） | **✅ 人工确认** |
| 换取 CAGR 从 18.06% 升至 20.37%（+2.31 pp） | 接受 |
| live feature flags 保持关闭 | ✅ |

## 执行步骤

### Step 1: Config 更新 ✅

- `portfolio.corr_regime_pct.extreme`: **92 → 110**
- `portfolio.extreme_corr_penalty`: **0.7 → 0.90**
- `portfolio._calibration.note`: 写入人工确认记录和日期
- `portfolio._calibration.approved_by`: `human-gate-2026-06-02`

无代码改动。`risk_budget.py` 直接读 config，即时生效。

### Step 2: 新 dry-run comparator（110/0.90）✅

```
phase3_dry_run_compare.py --threshold 110 --penalty 0.90 --suffix _p10_approved
```

| 指标 | 110/0.70（旧） | 110/0.90（新） |
|---|---:|---:|
| PASS days | 128 | **129** |
| WARN days | 124 | **123** |
| BLOCK days | 0 | **0** |
| R3 violations | 0 | **0** |
| Max abs symbol delta | 0.1293 | **0.0997** |
| Max abs turnover delta | 0.4022 | **0.2886** |
| Avg new turnover | 0.2285 | **0.2263** |

所有指标较 110/0.70 全面改善。

### Step 3: 迁移验证 ✅

- `risk_budget.py` 从 config 读参数，config 已更新，**无需改代码**
- 旧 scaler 链（`size_portfolio`）仍在但现在接收新 RiskEngine 的 `effective_gross_scaler`
- 270 package tests OK

## scaler 迁移路径说明

本次迁移是 Phase III 第一层：**参数层迁移**（extreme threshold + penalty）。

| 层 | 描述 | 状态 |
|---|---|---|
| 参数层 | extreme=110, penalty=0.90 写入 config | ✅ DONE |
| 评估层 | `risk_budget.compute_portfolio_risk` 读新参数 | ✅ DONE（自动） |
| 优化器层 | 用 `SizingOptimizer.optimize_targets` 替换 `size_portfolio` 乘法链 | TODO（Phase III Step 2） |

Phase III Step 2（全量替换 `size_portfolio` 为 `optimize_targets`）可在下一轮施工进行，不影响当前安全性（旧链已接收新参数）。

## 产物

- `config/config.json`（已更新，参数生效）
- `reports/PhaseIII_Dry_Run_Comparator_p10_approved.md/json`
- 本日志

## 当前状态

Phase III 参数层迁移：**DONE**
全量优化器替换（Phase III Step 2）：**TODO / 可下一轮施工**
270 tests OK
