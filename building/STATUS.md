| Phase | 状态 | 分支/PR | 回测达标 | 阻塞 | 更新时间 |
|---|---|---|---|---|---|
| 0 脚手架与契约 | DONE | local only | n/a | - | 2026-05-31 |
| 1 数据层与离线回放 | DONE | local only | n/a | 真实软数据 adapter 尚未接入，本阶段只种 dated archive | 2026-05-31 |
| 2 指标与特征层 | DONE | local only | n/a | EMA/MA/RSI/MACD/ATR/Chandelier/派发日/AVWAP/平台支撑/CMF/MFI/AD 已全部内建 | 2026-06-01 |
| 3 评分核心 A/B/C/D | DONE | local only | n/a | A6/C7/D-F4/D-S4 已接本地可算价格/资金流字段；软数据 adapter 未接导致部分 blind-spot 属预期 | 2026-06-01 |
| 4 硬阀门 | DONE | local only | n/a | 历史 raw/precheck 样本仍只有 5 个交易日，触发矩阵覆盖受限 | 2026-06-01 |
| 5 裁决层 | DONE | local only | n/a | 二次确认纯函数与 signal journal 已接；生产状态切换未启用 | 2026-06-01 |
| 6 组合风险预算层 | DONE | local only | pending | 参数 sweep/回测校准 **已完成（NEXT-3）**；当前 effective scaler 仍为 shadow-only | 2026-06-01 |
| 7 仓位管理 | DONE | local only | pending | gross scaler 仍为 shadow-only；未接持久化滞回状态 | 2026-06-01 |
| 8 资金路由 | DONE | local only | n/a | BRK.B 降级监控已接；实时生效需本地 BRK.B 历史；仅 advisory | 2026-06-01 |
| 9 3-3-4 再建仓 | DONE | local only | n/a | 卖出日期读取 signal journal；T1/T2 活跃状态仍未持久化 | 2026-06-01 |
| 10 扩展数据 adapter | IN-PROGRESS | local only | n/a | FRED、CBOE SKEW/VVIX、AAII、成分宽度已接；PCR/NAAIM/真实 BTC funding-basis-DVOL/GEX/social/valuation 待接 | 2026-06-01 |
| 11 回测与验证框架 | ACCEPTANCE-READY | local only | coverage-constrained | 已有完整 routed runner、Backtest_FULL 报告、硬阀门历史测试；P0 已通过，可重跑全窗口 | 2026-06-01 |
| 12 镜像参考系统 | DONE | local only | n/a | 策略、SQLite 快照、后验盈亏、Web 展示已接；IBKR reconciliation 未接 | 2026-06-01 |
| 13 元模型 | LOCKED | - | - | 标签解锁门未达 | - |
| 14 WebUI 与可观测性 | PARTIAL | local only | n/a | 已有只读 HTML/HTTP 面板、体制/模块分/审计明细展示与结构化 audit log；未接 IBKR drilldown | 2026-06-01 |
| 15 集成、dry-run、切换 | PARTIAL | local only | pending | 后验盈亏/API/live只读server/audit/signal journal已做；未切换生产 WebUI/未接 IBKR reconciliation | 2026-06-01 |

## NEXT 工单进度

| NEXT | 状态 | 产出 | 验收 | 阻塞 |
|---|---|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | `scripts/backfill_history.py`, `core/data/pit.py`, `core/data/manifest.py`, `core/routing/leg_proxy.py` | 86 tests OK; 34/38 symbols ≤2018-01-02 | FNGU 原始源只到 2025-02-20，P0 已生成 proxy |
| NEXT-1 可历史化软数据 | IN-PROGRESS / BLIND-SPOT-GATE-PASS | FRED/CBOE/AAII/成分宽度/MSTR BTC 代理已接 | FNGU 19, SOXL 19, MSTR 26，均<30 | PCR/NAAIM/BTC funding-basis-DVOL 待接 |
| NEXT-2 回测引擎 | **DONE / P1-COMPLETE** | Backtest_FULL real-only + full-proxy | real-only CAGR 44.39% Sharpe 1.79 DSR 1.66 | - |
| P0 合成历史 | **DONE / STRICT-GATE-PASSED** | synth_leverage + 官方指数缓存 | FNGU TE 4.67%, corr 0.9986 | - |
| NEXT-3 校准 | **✅ DONE / M3-COMPLETE** | calibration_v2.json | deployment fixed PBO=0.1538 | - |
| NEXT-4 向前软数据 | TODO | - | - | 可与 NEXT-6 并行 |
| NEXT-5 元模型 | LOCKED | - | - | 标签解锁门未达 |
| NEXT-6 IBKR 对账 | TODO | - | - | 尚未接 greenfield |

## P4 整合地基进度（Phase 0 + Phase I）

| 组件 | 文件 | 吸收 E 系列 | 状态 |
|---|---|---|---|
| 公共契约 | `core/contracts.py` | - | ✅ DONE |
| ConfidenceSpine（脊柱） | `core/confidence/spine.py` | E1/E9/E10/E28/E30 | ✅ DONE |
| RiskEngine（唯一协方差源） | `core/portfolio/risk_engine.py` | E4/E5/E11/E13/E14 | ✅ DONE |
| SizingOptimizer（唯一处置入口） | `core/portfolio/sizing_optimizer.py` | E6/E8/E12/E15/E25/E26/E27 | ✅ DONE |
| FactorLab（IC/去冗余/校准） | `core/factors/lab.py` | E2/E3/E23 | ✅ DONE |
| MarketContext（多标的上下文） | `core/features/context.py` | E7/E16/E17/E18/E19/E20 | ✅ DONE |
| ValidationHarness（防过拟合） | `core/backtest/harness.py` | E21/E22/E23/E24 | ✅ DONE |
| 数据净化 | `core/data/sanitize.py` | E1 | ✅ DONE |
| 故障转移 | `core/data/failover.py` | E30 | ✅ DONE |
| Governance | `core/governance/governance.py` | E10/E28/E29 | ✅ DONE |

**Phase 0–I 全部 10 个核心组件骨架完成。E1–E30 中 29/30 已有骨架实现（E27 税务有接口预留）。85 个新测试。**

## 系统级 7 道总闸

| # | 总闸 | 骨架 | 集成验证 |
|---|---|---|---|
| 1 | 单一风险源（唯一 cov） | ✅ | ⬜ 待 pipeline 接线 |
| 2 | 单一处置入口（无 scaler 链） | ✅ | ⬜ 待删旧 scaler |
| 3 | R3 不变式 OOS 100% | ✅ | ⬜ 待全窗口验证 |
| 4 | 置信脊柱贯通 | ✅ | ⬜ 待每决策携带 |
| 5 | PBO<0.5 + CI + 对抗 AUC | ✅ | ⬜ 待实跑 |
| 6 | 因子健康 + 概率校准 | ✅ | ⬜ 待 Factor_Health.md |
| 7 | 可解释可治理 | ✅ | ⬜ 待熔断测试 |

## 下一步

1. Pipeline 接线：把 10 个组件串入每日 score_pipeline
2. Phase II 风险与信号插件接入
3. 旧 scaler 乘法链删除，用 SizingOptimizer 替换
4. 7 道总闸集成验证
5. 继续补 NEXT-1 剩余软数据（PCR/NAAIM/BTC funding-basis-DVOL）
