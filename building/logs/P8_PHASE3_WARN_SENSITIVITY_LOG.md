# P8 Phase III WARN Sensitivity Log

**时间**: 2026-06-02  
**范围**: EXTREME_CORR threshold / penalty 二次 dry-run 网格审阅  
**生产影响**: none。未翻 live feature flag，未写 account state，未写 signal journal，未下单。

## 本次搭建内容

- 新增 `scripts/phase3_warn_sensitivity.py`。
- 新增 `tests/test_phase3_warn_sensitivity.py`。
- 对 P7 的 WARN 机会成本做参数敏感性网格：
  - threshold: `100 / 110 / 120 / 130 / 140 / 150`
  - penalty: `0.70 / 0.80 / 0.90 / 1.00`
  - 共 24 个场景。
- 只回放一次 252 日 pipeline，然后复用 replay cache 评估全部场景。
- 新增 `NO_PENALTY_REVIEW` 标记：`penalty=1.00` 等于触发相关闸但不实际降 gross，不能当作正常防守候选。

## P8 结果摘要

| 指标 | 当前 110/0.70 | P8 保留惩罚候选 110/0.90 |
|---|---:|---:|
| readiness | REVIEW_REQUIRED | REVIEW_READY |
| R3 violations | 0 | 0 |
| BLOCK | 0 | 0 |
| WARN share | 49.21% | 48.81% |
| EXTREME_CORR share | 40.48% | 40.48% |
| WARN 10d candidate-old avg | -0.29% | -0.13% |
| max turnover delta | 0.4022 | 0.2886 |
| review score | 0.3888 | 0.1340 |

## 解读

- `110/0.90` 在 P8 的 252 日 dry-run 人审指标上优于当前 `110/0.70`：
  - 保持同样的 EXTREME_CORR 触发覆盖；
  - 降低 WARN 10 日机会成本；
  - 将最大换手差降到 0.30 以下；
  - 无 R3/BLOCK 硬伤。
- `penalty=1.00` 场景虽然机会成本更低，但属于 `NO_PENALTY_REVIEW`，不应作为保留防守性的候选。
- P8 不是上线批准。`110/0.90` 必须进入 full-window backtest sensitivity + exact spot-check 后，才可考虑替代 `110/0.70`。

## 验收结果

| 验收项 | 结果 |
|---|---|
| WARN sensitivity run | PASS |
| focused tests | 6 tests OK |
| package tests | 270 tests OK |
| golden tests | 11 tests OK |

## 产物

- `reports/PhaseIII_WARN_Sensitivity.md`
- `reports/PhaseIII_WARN_Sensitivity.json`
- `scripts/phase3_warn_sensitivity.py`
- `tests/test_phase3_warn_sensitivity.py`

## 下一步

1. 对 `threshold=110 / penalty=0.90` 运行 full-window backtest sensitivity 单场景复核。
2. 对该候选跑 exact optimizer spot-check。
3. 若 full-window 与 exact 复核通过，再生成 updated migration acceptance pack；live flags 仍由人工决定。
