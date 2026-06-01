| Phase | 状态 | 分支/PR | 回测达标 | 阻塞 | 更新时间 |
|---|---|---|---|---|---|
| 0 脚手架与契约 | DONE | local only | n/a | - | 2026-05-31 |
| 1 数据层与离线回放 | DONE | local only | n/a | 真实软数据 adapter 尚未接入，本阶段只种 dated archive | 2026-05-31 |
| 2 指标与特征层 | DONE | local only | n/a | EMA/MA/RSI/MACD/ATR/Chandelier/派发日/AVWAP/平台支撑/CMF/MFI/AD 已全部内建 | 2026-06-01 |
| 3 评分核心 A/B/C/D | DONE | local only | n/a | A6/C7/D-F4/D-S4 已接本地可算价格/资金流字段；软数据 adapter 未接导致部分 blind-spot 属预期 | 2026-06-01 |
| 4 硬阀门 | DONE | local only | n/a | 历史 raw/precheck 样本仍只有 5 个交易日，触发矩阵覆盖受限 | 2026-06-01 |
| 5 裁决层 | DONE | local only | n/a | 二次确认纯函数与 signal journal 已接；生产状态切换未启用 | 2026-06-01 |
| 6 组合风险预算层 | DONE | local only | NEXT-3 passed | 参数 sweep/校准 v2 已完成；当前 effective scaler 仍为 shadow-only，live 开关未翻 | 2026-06-01 |
| 7 仓位管理 | DONE | local only | NEXT-3 passed | 校准阈值已产出；gross scaler 仍为 shadow-only；未接持久化滞回状态 | 2026-06-01 |
| 8 资金路由 | DONE | local only | n/a | BRK.B 降级监控已接；实时生效需本地 BRK.B 历史；仅 advisory | 2026-06-01 |
| 9 3-3-4 再建仓 | DONE | local only | n/a | 卖出日期读取 signal journal；T1/T2 活跃状态仍未持久化 | 2026-06-01 |
| 10 扩展数据 adapter | IN-PROGRESS | local only | n/a | FRED、CBOE SKEW/VVIX、AAII、成分宽度已接；PCR/NAAIM/BTC funding-basis-DVOL/GEX/social/valuation 待接 | 2026-06-01 |
| 11 回测与验证框架 | DONE / M3-COMPLETE | local only | passed | full-proxy + real-only 回测、walk-forward、NEXT-3 校准 v2 已完成；train-greedy PBO 作为风险诊断保留 | 2026-06-01 |
| 12 镜像参考系统 | DONE | local only | n/a | 策略、SQLite 快照、后验盈亏、Web 展示已接；IBKR reconciliation 未接 | 2026-06-01 |
| 13 元模型 | LOCKED | - | - | 标签解锁门未达 | - |
| 14 WebUI 与可观测性 | PARTIAL | local only | n/a | 已有只读 HTML/HTTP 面板、体制/模块分/审计明细展示与结构化 audit log；未接 IBKR drilldown | 2026-06-01 |
| 15 集成、dry-run、切换 | **IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE** | local only | shadow + full sensitivity passed | Phase II 252 日 shadow、相关闸敏感性、2113 日 full-window sensitivity 完成；253 package tests OK；live 开关保持关闭 | 2026-06-01 |

## NEXT 工单进度

| NEXT | 状态 | 产出 | 验收 | 阻塞 |
|---|---|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | `scripts/backfill_history.py`, `core/data/pit.py`, `core/data/manifest.py`, `core/routing/leg_proxy.py`, `reports/NEXT0_REPORT.md`, `reports/N0_history_coverage.md` | 94 package tests OK + 11 golden tests OK; manifest verify OK; 34/38 symbols at 2018-01-02 or earlier | 原始 FNGU 源只回到 2025-02-20；原始 FNGS 只回到 2019-11-13，P0 已生成 proxy |
| NEXT-1 可历史化软数据 | IN-PROGRESS / BLIND-SPOT-GATE-PASS | FRED/A5、CBOE SKEW-VVIX/B4、AAII/A2、成分宽度/A3、MSTR BTC 价格代理/D-M3；`reports/NEXT1_REPORT.md`, `reports/N1_missing_rebaseline.md` | FNGU missing 19, SOXL missing 19, MSTR missing 26，均低于 30 | PCR/NAAIM/真实 BTC funding-basis-DVOL/GEX/social/valuation 待接 |
| NEXT-2 回测引擎补全 | **DONE / P1-COMPLETE** | `Backtest_FULL.md/json`（real-only CAGR 44.39% MaxDD -10.43% Sharpe 1.79 DSR 1.66）、`Backtest_FULL_2018_2026.md/json`（full-proxy CAGR 18.13% MaxDD -27.60% DSR 0.77）、`core/backtest/reports.py` label 修复 | **94 package tests OK + 11 golden tests OK** | - |
| **P0 合成杠杆历史** | **DONE / STRICT-GATE-PASSED** | `core/data/synth_leverage.py`, `scripts/build_synth_history.py`, `core/data/wso_index.py`, `scripts/backfill_official_indices.py`, `tests/test_p0_synth_leverage.py`, `reports/P0_synth_history_report.md/json` | FNGU/FNGS 本地历史均扩到 2018-01-02；**接缝调整严格门控通过**：FNGU seam_adj TE 4.67%，corr 0.9986；FNGS seam_adj TE 4.11%；接缝文档化 | - |
| **NEXT-3 参数扫描与正式校准** | **DONE / M3-COMPLETE / STABLE-HIGHLAND-PASSED** | `scripts/calibrate_next3_v2.py`；`config/artifacts/calibration_v2.json`；`reports/Calibration_v2.md`；`reports/NEXT3_CALIBRATION_LOG.md`；27 组阈值组合 × 13 fold full-proxy walk-forward + real-only 敏感性 | **94 package tests OK + 11 golden tests OK**；chosen: EXIT=75 DEF_EXIT=65 REDUCE=50 TRIM=35 WATCH=20；deployment fixed PBO=0.1538 PASS；full-proxy CAGR 17.54% MaxDD -28.01%；real-only CAGR 42.48% MaxDD -10.63%；real-only rank 0.7692；train-greedy PBO=0.6154 仅保留为过拟合警报 | 不自动翻 live 开关；逐窗口贪心最优不得上线 |
| NEXT-4 纯向前软数据 | TODO | - | - | 等 NEXT-3 或并行接契约 |
| NEXT-5 元模型 | LOCKED | - | - | 标签解锁门未达 |
| NEXT-6 IBKR 只读对账 | TODO | - | - | 尚未接 greenfield |
| **P4 整合地基** | **DONE / PHASE0-I-PIPELINE-LOCAL-SYNCED** | `core/contracts.py`；`core/confidence/spine.py`；`core/portfolio/risk_engine.py`；`core/portfolio/sizing_optimizer.py`；`core/factors/lab.py`；`core/features/context.py`；`core/backtest/harness.py`；`core/pipeline.py`；`core/reentry/tracker.py`；`core/audit/exporter.py`；`reports/P4_LOCAL_SNAPSHOT_SYNC_LOG.md` | **253 package tests OK + 11 golden tests OK**；远端 P4 source snapshots 已落地本地；修复 integration_config 路径、Python 3.9 日期、RiskEngine 下行相关/数值稳定、SizingOptimizer shrinkage、MarketContext 测试警告 | live 开关保持关闭 |
| **P5 Phase II Shadow 对照** | **IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE** | `scripts/phase2_shadow_compare.py`；`scripts/phase2_corr_sensitivity.py`；`scripts/phase2_full_backtest_sensitivity.py`；`reports/PhaseII_Shadow_Compare.md/json`；`reports/PhaseII_Corr_Sensitivity.md/json`；`reports/PhaseII_Full_Backtest_Sensitivity.md/json`；`reports/P5_PHASE2_EXTENDED_DIAGNOSTICS_LOG.md` | 252 日 shadow：rows=252、errors=0、R3 violations=0、max abs weight delta=0.1592；2113 日 full sensitivity：errors=0、scenario count=21、R3 violations=0；review candidate `threshold=110 / penalty=0.70`，CAGR 18.06%、MaxDD -22.47%、Sharpe 1.0115、fixed OOS below-median 0.3077 | Phase III 仍需 exact optimizer 抽样复核、dry-run、人审；live 开关保持关闭 |
