# P10 Updated Migration Acceptance Pack 执行日志

**时间**: 2026-06-02
**范围**: 合并 P8（WARN sensitivity 24 场景）+ P9（110/0.90 full-window + exact）结论，产出最终人工门控文件
**生产影响**: none。未翻 live feature flag，未写 account state，未下单。

## 目标

P9 状态为 DONE/FULL-EXACT-PASSED/REVIEW-GATED，需要一份正式文件把 P5-P9 的所有证据整合在一起，供人工最终审阅和决策。

## 产物

- `building/reports/P10_MIGRATION_ACCEPTANCE_PACK.md`：终极人工审阅文件

## 关键决策建议

候选参数：`corr_regime_extreme_pctl=110 / extreme_corr_penalty=0.90`

| 维度 | 值 | 结论 |
|---|---|---|
| Full-window CAGR vs 旧基线 | +2.24 pp（18.13%→20.37%） | 正向 |
| MaxDD vs 旧基线 | -3.28 pp（-27.60%→-24.32%） | 正向（回撤改善） |
| MaxDD vs 110/0.70 | +1.85 pp（-22.47%→-24.32%） | 需人工决策 |
| WARN 10d avg Δ | -0.13% | 机会成本极小 |
| Max turnover Δ | 0.2886 | vs 110/0.70 的 0.4022，改善 28% |
| R3 violations | 0 | ✅ |
| BLOCK days | 0 | ✅ |
| Fixed OOS below-median | 0.4615 | <0.5，PASS |
| Full-window errors | 0 | ✅ |
| Exact spot-check | 4/4 通过 | ✅ |

## 人工门控检查单

10 项中 9 项代码层面已通过，第 9 项需人工确认：

- **⬜ 接受约 1.85 pp 回撤放大（从-22.47%到-24.32%）？**

一旦确认，Phase III 迁移顺序：
1. 更新 config 参数 → 2. 新 dry-run comparator 报告 → 3. scaler 迁移 → 4. 并排验收 → 5. Phase IV

## 状态

P10: **DONE / HUMAN-GATE-PENDING**（等待人工确认第 9 项）
