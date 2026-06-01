# P1 执行日志 — NEXT-2 全窗口回测（2018→2026）

生成时间：`2026-06-01`

## 触发条件

P0 接缝调整严格门控已通过（2026-06-01），P1 阻塞解除，立即启动全窗口回测。

## 前置检查

| 标的 | history 行数 | 起始日期 | 结束日期 | 含 proxy |
|---|---:|---|---|---|
| MSTR | 2113 | 2018-01-02 | 2026-05-29 | 是（real_start 2018-01-02，MSTR 本身即有真实历史） |
| FNGU | 2113 | 2018-01-02 | 2026-05-29 | 是（proxy 1793 行，real_start 2025-02-20） |
| SOXL | 2113 | 2018-01-02 | 2026-05-29 | 是（proxy 段来自 SOXX 3x 合成） |

有效窗口预期：2018-01-02 → 2026-05-29（约 2047 个交易日）

## 执行

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -c "
from hermes_escape_top.core.backtest.run_full import run_full_backtest
report = run_full_backtest(start='2018-01-01', end='2026-05-29')
"
```

## 最终结果（2026-06-01）

### 两栏并排

| 报告类型 | 窗口 | 交易日 | CAGR | MaxDD | Sharpe | Sortino | DSR |
|---|---|---:|---:|---:|---:|---:|---:|
| **Real-only（高置信）** | 2025-02-20 → 2026-05-29 | 320 | **44.39%** | -10.43% | 1.7871 | 2.2201 | **1.664** |
| Full-proxy（含合成段） | 2018-01-02 → 2026-05-29 | 2113 | 18.13% | -27.60% | 0.8818 | 1.1155 | 0.774 |

**基准对比（8 年窗口）：** SPY CAGR 13.14% / MaxDD -34.10%；QQQ CAGR 20.15% / MaxDD -36.91%。系统全窗口 CAGR 18.13% 超过 SPY，与 QQQ 接近，MaxDD (-27.60%) 显著优于两者。

### 硬阀门历史覆盖（全窗口）

| 标的 | 信号数 | 20日命中率 | 平均后向最大回撤 |
|---|---:|---:|---:|
| FNGU | 1173 | 55.41% | -15.62% |
| SOXL | 1350 | 56.67% | -16.13% |
| MSTR | 1449 | 40.95% | -11.57% |

### Walk-Forward

- Folds: 13（IS 2y / OOS 6m / step 6m）
- Deflated Sharpe（real-only）: **1.664**（显著正值，置信度高）
- Deflated Sharpe（full-proxy）: 0.774（代理段信号统计意义有限，符合预期）

### 报告文件

- `building/reports/Backtest_FULL.md/json` — real-only（主报告，用于验收）
- `building/reports/Backtest_FULL_2018_2026.md/json` — full-proxy（参考报告）

### 下一步 → P2（NEXT-3 参数扫描）

P1 全窗口回测完成，M2 验收条件达成。可以启动 NEXT-3 参数扫描与校准。

