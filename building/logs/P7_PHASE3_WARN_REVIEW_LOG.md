# P7 Phase III WARN Review Log

**时间**: 2026-06-02  
**范围**: P6 `PhaseIII_Dry_Run_Comparator` 的 WARN 人审前分析包  
**生产影响**: none。未翻 live feature flag，未写 account state，未写 signal journal，未下单。

## 本次搭建内容

- 新增 `scripts/phase3_warn_review.py`。
- 新增 `tests/test_phase3_warn_review.py`。
- 读取 `PhaseIII_Dry_Run_Comparator.json`，对 WARN 行做二次分析：
  - WARN 原因分类；
  - WARN 月份分布；
  - 最大 target delta / route delta / turnover delta 日期；
  - 用本地价格面板测算 old route vs candidate route 的 1/5/10 个交易日前瞻收益差；
  - 输出 `REVIEW_REQUIRED` readiness，不替人工审批。

## P7 结果摘要

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| PASS | 128 |
| WARN | 124 |
| WARN share | 49.21% |
| BLOCK | 0 |
| EXTREME_CORR WARN | 102 |
| EXTREME_REGIME WARN | 102 |
| ROUTE_LEG_DELTA WARN | 50 |
| TURNOVER_DELTA WARN | 28 |
| SYMBOL_DELTA WARN | 20 |
| LOW_GROSS WARN | 16 |

## 前瞻收益差：candidate - old

| 样本 | 1d avg | 5d avg | 10d avg | 说明 |
|---|---:|---:|---:|---|
| WARN rows | -0.00% | -0.05% | -0.29% | 候选在 WARN 日略有机会成本 |
| PASS rows | -0.00% | +0.01% | +0.07% | PASS 日基本中性 |

## 解读

- 没有 R3/BLOCK 级硬伤，P6 的硬约束结论保持有效。
- WARN 集中在 `EXTREME_CORR`：102/124，说明主要不是普通换手噪声，而是相关性压力闸触发。
- WARN 的 10 日平均候选相对旧链路为 `-0.29%`，这不是上线阻断项，但说明候选更保守，存在可量化机会成本。
- 最大单日 turnover delta 仍需人工审阅；readiness 保持 `REVIEW_REQUIRED`，live promotion 仍为 `BLOCKED`。

## 验收结果

| 验收项 | 结果 |
|---|---|
| WARN review run | PASS |
| focused tests | 4 tests OK |
| package tests | 264 tests OK |
| golden tests | 11 tests OK |

## 产物

- `reports/PhaseIII_WARN_Review.md`
- `reports/PhaseIII_WARN_Review.json`
- `scripts/phase3_warn_review.py`
- `tests/test_phase3_warn_review.py`

## 下一步

1. 人工审阅 P7 报告中的高差异日期，尤其是 `2025-08-04`、`2025-07-14`、`2025-08-28`。
2. 若接受候选的机会成本，再进入 scaler migration 代码替换设计。
3. 若不接受，可回到 P5 参数网格，围绕 EXTREME_CORR penalty/threshold 做二次校准。
