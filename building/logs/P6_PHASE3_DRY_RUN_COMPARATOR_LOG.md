# P6 Phase III Dry-run Comparator Log

**时间**: 2026-06-02  
**范围**: old scaler / route chain vs Phase II review candidate `threshold=110 / penalty=0.70`  
**生产影响**: none。未翻 live feature flag，未写 account state，未写 signal journal，未下单。

## 本次搭建内容

- 新增 `scripts/phase3_dry_run_compare.py`。
- 新增 `tests/test_phase3_dry_run_compare.py`。
- 干跑脚本逐日输出：
  - 旧 backtest target weights；
  - 候选 pipeline target weights；
  - 旧 route leg weights；
  - 候选 route leg weights；
  - per-symbol delta、per-route-leg delta；
  - old/new turnover 与 turnover delta；
  - risk binding、corr regime、scenario gross；
  - 每日 `PASS` / `WARN` / `BLOCK` gate verdict。
- gate 语义：
  - `BLOCK`: R3 invariant 失败或候选 route gross 异常；
  - `WARN`: target/route/turnover 差异较大、EXTREME_CORR、EXTREME regime 或 gross 过低；
  - `PASS`: 在 dry-run tolerance 内。

## 252 日干跑结果

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
| PASS | 128 |
| WARN | 124 |
| BLOCK | 0 |
| max abs symbol delta | 0.1293 |
| avg max abs symbol delta | 0.0425 |
| max abs route leg delta | 0.2802 |
| avg abs turnover delta | 0.0382 |
| max abs turnover delta | 0.4022 |
| avg old turnover | 0.2244 |
| avg new turnover | 0.2285 |
| risk binding counts | NONE 97 / VOL 53 / EXTREME_CORR 102 |
| corr regime counts | ELEVATED 150 / EXTREME 102 |

最新交易日 `2026-05-29` gate 为 `PASS`：

| 字段 | 结果 |
|---|---:|
| old route | BOXX 0.4436 / BRK.B 0.1500 / FNGU 0.1801 / SOXL 0.2263 |
| candidate route | BOXX 0.5119 / BRK.B 0.1500 / FNGU 0.1353 / SOXL 0.2029 |
| max target delta | 0.0449 |
| turnover old/new/delta | 0.0186 / 0.0079 / -0.0107 |
| scenario gross | 0.6909 |
| risk binding | VOL |

## 解读

- `BLOCK=0` 与 `R3 violations=0` 表明候选链路没有违反硬约束。
- `WARN=124` 不是失败，而是 human dry-run 必审清单：主要集中在 EXTREME_CORR、较低 gross、以及少数 route/turnover 差异较大的日期。
- 候选平均 turnover 与旧链路接近：0.2285 vs 0.2244；但最大单日 turnover delta 达 0.4022，迁移前仍需人工确认这些日期是否符合预期。
- 该报告把 P5 acceptance pack 中的 `Daily old-vs-new dry-run comparator` 从 TODO 推进为 DONE；live promotion 仍保持 BLOCKED。

## 验收结果

| 验收项 | 结果 |
|---|---|
| smoke dry-run 5 rows | PASS |
| 252-day dry-run comparator | PASS |
| focused tests | 7 tests OK |
| package tests | 260 tests OK |
| golden tests | 11 tests OK |

## 产物

- `reports/PhaseIII_Dry_Run_Comparator.md`
- `reports/PhaseIII_Dry_Run_Comparator.json`
- `reports/PhaseIII_Dry_Run_Comparator_smoke.md`
- `reports/PhaseIII_Dry_Run_Comparator_smoke.json`
- `scripts/phase3_dry_run_compare.py`
- `tests/test_phase3_dry_run_compare.py`

## 下一步

1. 人工审阅 WARN 日期，尤其是 `2025-08-04`、`2025-07-14` 等最大差异日。
2. 若 human gate 接受 WARN 行为，再进入 Phase III scaler migration 的代码替换设计。
3. live flags 继续保持关闭；任何上线必须由人工确认。
