| Phase | 状态 | 分支/PR | 回测达标 | 阻塞 | 更新时间 |
|---|---|---|---|---|---|
| 0 脚手架与契约 | DONE | local only | n/a | - | 2026-05-31 |
| 1 数据层与离线回放 | DONE | local only | n/a | 真实软数据 adapter 尚未接入，本阶段只种 dated archive | 2026-05-31 |
| 2 指标与特征层 | DONE | local only | n/a | EMA/MA/RSI/MACD/ATR/Chandelier/派发日/AVWAP/平台支撑/CMF/MFI/AD 已全部内建 | 2026-06-01 |
| 3 评分核心 A/B/C/D | DONE | local only | n/a | A6/C7/D-F4/D-S4 已接本地可算价格/资金流字段；软数据 adapter 未接导致部分 blind-spot 属预期 | 2026-06-01 |
| 4 硬阀门 | DONE | local only | n/a | 历史 raw/precheck 样本仍只有 5 个交易日，触发矩阵覆盖受限 | 2026-06-01 |
| 5 裁决层 | DONE | local only | n/a | 二次确认纯函数与 signal journal 已接；生产状态切换未启用 | 2026-06-01 |
| 6 组合风险预算层 | DONE | local only | pending | 参数 sweep/回测校准尚未做；当前 effective scaler 为 shadow-only | 2026-06-01 |
| 7 仓位管理 | DONE | local only | pending | gross scaler 仍为 shadow-only；未接持久化滞回状态 | 2026-06-01 |
| 8 资金路由 | DONE | local only | n/a | BRK.B 降级监控已接；实时生效需本地 BRK.B 历史；仅 advisory | 2026-06-01 |
| 9 3-3-4 再建仓 | DONE | local only | n/a | 卖出日期读取 signal journal；T1/T2 活跃状态仍未持久化 | 2026-06-01 |
| 10 扩展数据 adapter | IN-PROGRESS | local only | n/a | FRED、CBOE SKEW/VVIX、AAII、成分宽度已接；PCR/NAAIM/BTC funding-basis-DVOL/GEX/social/valuation 待接 | 2026-06-01 |
| 11 回测与验证框架 | ACCEPTANCE-READY | local only | coverage-constrained | 已有完整 routed runner、Backtest_FULL 报告、硬阀门历史测试；严格 2018 起点受 FNGU 数据限制 | 2026-06-01 |
| 12 镜像参考系统 | DONE | local only | n/a | 策略、SQLite 快照、后验盈亏、Web 展示已接；IBKR reconciliation 未接 | 2026-06-01 |
| 13 元模型 | LOCKED | - | - | 标签解锁门未达 | - |
| 14 WebUI 与可观测性 | PARTIAL | local only | n/a | 已有只读 HTML/HTTP 面板、体制/模块分/审计明细展示与结构化 audit log；未接 IBKR drilldown | 2026-06-01 |
| 15 集成、dry-run、切换 | PARTIAL | local only | pending | 后验盈亏/API/live只读server/audit/signal journal已做；未切换生产 WebUI/未接 IBKR reconciliation | 2026-06-01 |

## NEXT 工单进度

| NEXT | 状态 | 产出 | 验收 | 阻塞 |
|---|---|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | `scripts/backfill_history.py`, `core/data/pit.py`, `core/data/manifest.py`, `core/routing/leg_proxy.py`, `reports/NEXT0_REPORT.md`, `reports/N0_history_coverage.md` | 82 tests OK; manifest verify OK; 34/38 symbols at 2018-01-02 or earlier | 原始 FNGU 源只回到 2025-02-20；原始 FNGS 只回到 2019-11-13，P0 已生成 proxy 但 FNGU 严格 TE 未过 |
| NEXT-1 可历史化软数据 | IN-PROGRESS / BLIND-SPOT-GATE-PASS | FRED/A5、CBOE SKEW-VVIX/B4、AAII/A2、成分宽度/A3、MSTR BTC 价格代理/D-M3；`reports/NEXT1_REPORT.md`, `reports/N1_missing_rebaseline.md` | 82 tests OK; FNGU missing 19, SOXL missing 19, MSTR missing 26，均低于 30 | PCR/NAAIM/真实 BTC funding-basis-DVOL/GEX/social/valuation 待接 |
| NEXT-2 回测引擎补全 | ACCEPTANCE-READY / COVERAGE-CONSTRAINED | `run_full_backtest`、routed route-leg simulation、`Backtest_FULL.md/json`、硬阀门历史矩阵、`reports/NEXT2_REPORT.md` | 82 tests OK; full report generated; effective window 2025-02-20 to 2026-05-29 | P0 FNGU 严格 TE 未过，暂不把 2018+ proxy 窗口用于 P1/NEXT-3 |
| P0 合成杠杆历史 | CODE-DONE / STRICT-GATE-NOT-PASSED | `core/data/synth_leverage.py`, `scripts/build_synth_history.py`, `core/data/wso_index.py`, `scripts/backfill_official_indices.py`, `tests/test_p0_synth_leverage.py`, `reports/P0_synth_history_report.md/json` | 84 tests OK; FNGU/FNGS 本地历史均扩到 2018-01-02；proxy rows: FNGU 1793 / FNGS 470；manifest 记录 proxy 区间；官方 ICE `FANG3X/FANGT3X` 已可缓存并诊断 | 严格 overlap 验收 FNGU 年化 TE 8.42% > 5%（corr 0.9950 过门）；官方 `FANG3X` 诊断 TE 9.91%，仍不放行；FNGS 通过。按 `CODEX_GUIDANCE.md` 不启动 P1/NEXT-3，需继续修 FNGU 合成跟踪误差 |
| NEXT-3 参数扫描与正式校准 | TODO | - | - | 等 NEXT-1/2 |
| NEXT-4 纯向前软数据 | TODO | - | - | 等 NEXT-3 或并行接契约 |
| NEXT-5 元模型 | LOCKED | - | - | 标签解锁门未达 |
| NEXT-6 IBKR 只读对账 | TODO | - | - | 尚未接 greenfield |
