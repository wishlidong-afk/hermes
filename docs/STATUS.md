# STATUS（进度账本）

> 每完成一步更新本表，并与 `00_MASTER_OVERVIEW.md` 元信息、`SYSTEM_OVERVIEW.md` 成熟度表对账。
> 更新时间：2026-06-01（据 Codex + Claude 真实进度账本同步）

## 一句话现状

流水线通；**245 package tests OK + 11 golden tests OK**；**missing 已降至 MSTR 26 / FNGU 19 / SOXL 19，盲区门(<30)已过 → M1 实质达成**。
**P0 合成杠杆历史已通过严格接缝调整门控**；**P1 全窗口回测已完成**；**NEXT-3 参数校准 v2 已通过稳定高原门控**。当前候选参数为 `EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20`。Deployment fixed PBO=0.1538 PASS。系统达到 **M3 校得准**，但 live/生产开关仍保持关闭。
**P4 整合地基 Phase 0–I + Pipeline 接线已完成并已落地本地 `.hermes`**：12 个组件（1 脊柱 + 4 引擎 + 1 优化器 + 治理 + 输入护栏 + 漂移监控 + 统一 Pipeline）全部骨架就绪，E1–E30 全覆盖，7 道系统级总闸全部有结构性验证；本地同步修复后 245 package tests OK。**P5 Phase II 20 日 shadow 对照已跑通**：rows=20、errors=0、R3 violations=0、confidence NORMAL×20，live 开关仍关闭。

## 成熟度

| 等级 | 达成 | 证据 |
|---|---|---|
| M0 能跑 | ✅ | 245 package tests OK + 11 golden tests OK / 单日回放 |
| M1 看得清 | ✅ | missing 26/19/19 < 30；`N1_missing_rebaseline.md` |
| M2 验得过 | ✅ | `Backtest_FULL`（real-only）+ `Backtest_FULL_2018_2026`（full-proxy）均出；DSR 1.66；13 fold walk-forward |
| M3 校得准 | ✅ | `Calibration_v2.md/json`；deployment fixed PBO=0.1538；full-proxy/real-only 门控通过 |
| M4 可上线 | ⬜ | 待人工 dry-run |
| M5 会学习 | ⬜ | 标签解锁门未达 |

## 基线（NEXT 工单）

| NEXT | 状态 | 备注 |
|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | backfill/pit/manifest/leg_proxy 完成；34/38 标的 ≤2018-01-02 |
| NEXT-1 可历史化软数据 | IN-PROGRESS / 盲区门已过 | 已接 FRED·A5 / CBOE SKEW-VVIX·B4 / AAII·A2 / 成分宽度·A3 / MSTR BTC价代理·D-M3；**待接 PCR / NAAIM / BTC funding-basis-DVOL / GEX / social / valuation（增量，非阻塞）** |
| **P0 合成杠杆历史** | **DONE / STRICT-GATE-PASSED** | FNGU/FNGS proxy 到 2018-01-02；接缝调整严格门控 PASS（FNGU TE 4.67%，corr 0.9986；FNGS TE 4.11%）；接缝原因文档化（FNGB→FNGU 迁移，官方 FANG3X 独立确认）；见 `building/reports/P0_synth_history_report.md` |
| NEXT-2 回测引擎 | **DONE / P1 全窗口完成** | `Backtest_FULL.md`（real-only）+ `Backtest_FULL_2018_2026.md`（full-proxy）并排报告已出；real-only CAGR 44.39%、MaxDD -10.43%、Sharpe 1.79、DSR 1.66；full-proxy CAGR 18.13%、MaxDD -27.60%；13 个 walk-forward folds |
| NEXT-3 参数校准 | **DONE / M3-COMPLETE / STABLE-HIGHLAND-PASSED** | v2 稳定高原参数：EXIT=75 / DEF_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20；Deployment fixed PBO=0.1538；train-greedy PBO=0.6154 仅保留为警报 |
| NEXT-4 向前软数据 | TODO | GEX/CNN/新闻/mNAV |
| NEXT-5 元模型 | LOCKED | 样本未达解锁门 |
| NEXT-6 IBKR 只读对账 | TODO | 绝不下单 |

## 老 Phase 映射（已建骨架）

Phase 0–9、12 = DONE；Phase 10(扩展数据)=IN-PROGRESS；Phase 11(回测)=ACCEPTANCE-READY/窗口受限；Phase 14(WebUI)=PARTIAL；Phase 15(集成/切换)=PARTIAL；Phase 13(元模型)=LOCKED。

## 整合（Phase 0–I + Pipeline）

| 组件 | 状态 |
|---|---|
| 公共契约 `contracts.py` | ✅ DONE |
| ConfidenceSpine | ✅ DONE |
| RiskEngine（唯一协方差源） | ✅ DONE |
| SizingOptimizer（唯一处置入口） | ✅ DONE |
| FactorLab（IC/去冗余/校准） | ✅ DONE |
| MarketContext（多标的上下文） | ✅ DONE |
| ValidationHarness（防过拟合） | ✅ DONE |
| E1 数据净化 | ✅ DONE |
| E30 故障转移 | ✅ DONE |
| E9 漂移监控 | ✅ DONE |
| Governance（分歧/脆弱/冠军挑战者） | ✅ DONE |
| **统一 Pipeline**（11 步数据流） | ✅ DONE |

## E 系列增强（E1–E30）

**30/30 全覆盖**（29 骨架实现 + 1 接口预留）。详见 `building/reports/P4_INTEGRATION_PHASE0_I_REPORT.md`。

## 系统级 7 道总闸

①单一风险源 ✅骨架 ②单一处置入口 ✅骨架 ③R3 100% ✅骨架+测试 ④置信脊柱贯通 ✅骨架+测试 ⑤PBO<0.5+CI+对抗AUC ✅骨架 ⑥因子健康+概率校准 ✅骨架 ⑦可解释可治理 ✅骨架
（全部待实数据集成验证）

## 当前关键数字

- missing_weight：MSTR 26 / FNGU 19 / SOXL 19（**均 <30，盲区门已过**）
- P0 proxy 覆盖：FNGU 2018-01-02→2025-02-19（1793 行）；FNGS 2018-01-02→2019-11-12（470 行）
- P0.1 官方指数缓存：`FANG3X` 2020-04-14→2026-05-29（1549 行）；`FANGT3X` 2020-04-14→2026-05-29（1541 行）
- **P0 接缝调整严格门控 PASS**：FNGU seam_adj TE 4.67% / corr 0.9986；FNGS TE 4.11%
- **P1 全窗口回测 DONE**：real-only CAGR 44.39% / MaxDD -10.43% / Sharpe 1.79 / DSR 1.66；full-proxy CAGR 18.13% / MaxDD -27.60% / DSR 0.77（代理段信号统计意义有限）
- **NEXT-3 校准 DONE**：chosen `E75_D65_R50`；full-proxy CAGR 17.54% / MaxDD -28.01% / Sharpe 0.86；real-only CAGR 42.48% / MaxDD -10.63% / Sharpe 1.73；deployment fixed PBO 0.1538；real-only rank 0.7692；train-greedy PBO 0.6154 为过拟合警报
- **P3 并行（部分）**：NAAIM + PCR 数据源基础设施已建（`core/data/pcr.py`、`scripts/backfill_pcr_naaim.py`）；CBOE/NAAIM 外部端点被封，CSV 骨架就绪，等待手动回填后 missing_weight 可降 8pt
- **P4 整合地基本地落地**：远端 `building/source_snapshots/P4_*` 已同步到本地 `.hermes`；修复 integration_config 路径、Python 3.9 日期、RiskEngine 下行相关/数值稳定、SizingOptimizer shrinkage、MarketContext 测试警告。
- **P5 Phase II shadow 对照**：`PhaseII_Shadow_Compare.md/json` 已生成；最近 20 个交易日 rows=20、errors=0、R3 violations=0、max abs weight delta=0.2747、confidence NORMAL×20；多数日触发 `EXTREME_CORR`，Phase III 前需扩窗解释与风险预算校准。
- 单测：245 package tests OK；11 golden tests OK（v25 golden 已按 P0 当前数据地基重生）
- 2026-05-29 回放：MSTR EXIT(H-M1,H-M4) / FNGU HOLD / SOXL HOLD；体制 LOW_VOL_TREND
