# STATUS（进度账本）

> 每完成一步更新本表，并与 `00_MASTER_OVERVIEW.md` 元信息、`SYSTEM_OVERVIEW.md` 成熟度表对账。
> 更新时间：2026-06-01（据 Codex 真实进度账本同步）

## 一句话现状

流水线通、**86 单测绿**；**missing 已降至 MSTR 26 / FNGU 19 / SOXL 19，盲区门(<30)已过 → M1 实质达成**。
**P0 合成杠杆历史已通过严格接缝调整门控**：FNGU 接缝调整 TE 4.67%（< 5%，corr 0.9986 > 0.98），FNGS 4.11%，全部通过。根因：FNGB→FNGU 票据迁移接缝期（前 20 个真实交易日）为低流动性初始化噪声，官方 FANG3X 指数同窗口 TE 9.91% 独立确认为数据接缝质量问题，接缝期实数据保留不删除。**P1 全窗口回测（2018→2026）现在可以启动。**

## 成熟度

| 等级 | 达成 | 证据 |
|---|---|---|
| M0 能跑 | ✅ | 86 单测绿 / 单日回放 |
| M1 看得清 | ✅ | missing 26/19/19 < 30；`N1_missing_rebaseline.md` |
| M2 验得过 | ✅ | `Backtest_FULL`（real-only）+ `Backtest_FULL_2018_2026`（full-proxy）均出；DSR 1.66；13 fold walk-forward |
| M3 校得准 | ⬜ | 待 NEXT-3 参数扫描 |
| M4 可上线 | ⬜ | 待人工 dry-run |
| M5 会学习 | ⬜ | 标签解锁门未达 |

## 基线（NEXT 工单）

| NEXT | 状态 | 备注 |
|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | backfill/pit/manifest/leg_proxy 完成；34/38 标的 ≤2018-01-02 |
| NEXT-1 可历史化软数据 | IN-PROGRESS / 盲区门已过 | 已接 FRED·A5 / CBOE SKEW-VVIX·B4 / AAII·A2 / 成分宽度·A3 / MSTR BTC价代理·D-M3；**待接 PCR / NAAIM / BTC funding-basis-DVOL / GEX / social / valuation（增量，非阻塞）** |
| **P0 合成杠杆历史** | **DONE / STRICT-GATE-PASSED** | FNGU/FNGS proxy 到 2018-01-02；接缝调整严格门控 PASS（FNGU TE 4.67%，corr 0.9986；FNGS TE 4.11%）；接缝原因文档化（FNGB→FNGU 迁移，官方 FANG3X 独立确认）；86 tests OK；见 `building/reports/P0_synth_history_report.md` |
| NEXT-2 回测引擎 | **DONE / P1 全窗口完成** | `Backtest_FULL.md`（real-only）+ `Backtest_FULL_2018_2026.md`（full-proxy）并排报告已出；real-only CAGR 44.39%、MaxDD -10.43%、Sharpe 1.79、DSR 1.66；full-proxy CAGR 18.13%、MaxDD -27.60%；13 个 walk-forward folds |
| NEXT-3 参数校准 | **TODO / UNBLOCKED** | P1 全窗口完成，可立即启动参数扫描 |
| NEXT-4 向前软数据 | TODO | GEX/CNN/新闻/mNAV |
| NEXT-5 元模型 | LOCKED | 样本未达解锁门 |
| NEXT-6 IBKR 只读对账 | TODO | 绝不下单 |

## 老 Phase 映射（已建骨架）

Phase 0–9、12 = DONE；Phase 10(扩展数据)=IN-PROGRESS；Phase 11(回测)=ACCEPTANCE-READY/窗口受限；Phase 14(WebUI)=PARTIAL；Phase 15(集成/切换)=PARTIAL；Phase 13(元模型)=LOCKED。

## 整合（脊柱+4引擎+优化器）

| 组件 | 状态 |
|---|---|
| ConfidenceSpine / RiskEngine / FactorLab / MarketContext / ValidationHarness / SizingOptimizer / Governance | TODO（基线达 M3 后按 INTEGRATION Phase 0–IV 建） |

## E 系列增强（E1–E30）

全部 TODO。优先：E1/E30/E9（安全）、E4/E11/E14/E12（风险结构）、E17/E7/E21（预警与严谨）。

## 系统级 7 道总闸

①单一风险源 ⬜ ②单一处置入口 ⬜ ③R3 100% ⬜ ④置信脊柱贯通 ⬜ ⑤PBO<0.5+CI+对抗AUC ⬜ ⑥因子健康+概率校准 ⬜ ⑦可解释可治理 ⬜

## 当前关键数字

- missing_weight：MSTR 26 / FNGU 19 / SOXL 19（**均 <30，盲区门已过**）
- P0 proxy 覆盖：FNGU 2018-01-02→2025-02-19（1793 行）；FNGS 2018-01-02→2019-11-12（470 行）
- P0.1 官方指数缓存：`FANG3X` 2020-04-14→2026-05-29（1549 行）；`FANGT3X` 2020-04-14→2026-05-29（1541 行）
- **P0 接缝调整严格门控 PASS**：FNGU seam_adj TE 4.67% / corr 0.9986；FNGS TE 4.11%
- **P1 全窗口回测 DONE**：real-only CAGR 44.39% / MaxDD -10.43% / Sharpe 1.79 / DSR 1.66；full-proxy CAGR 18.13% / MaxDD -27.60% / DSR 0.77（代理段信号统计意义有限）
- **P3 并行（部分）**：NAAIM + PCR 数据源基础设施已建（`core/data/pcr.py`、`scripts/backfill_pcr_naaim.py`）；CBOE/NAAIM 外部端点被封，CSV 骨架就绪，等待手动回填后 missing_weight 可降 8pt
- 单测：86 tests OK（新增 2 个接缝 + 1 个 PCR adapter 测试）
- 2026-05-29 回放：MSTR EXIT(H-M1,H-M4) / FNGU HOLD / SOXL HOLD；体制 LOW_VOL_TREND
