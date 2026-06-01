# STATUS（进度账本）

> 每完成一步更新本表，并与 `00_MASTER_OVERVIEW.md` 元信息、`SYSTEM_OVERVIEW.md` 成熟度表对账。
> 更新时间：2026-06-01（据 Codex 真实进度账本同步）

## 一句话现状

流水线通、**78 单测绿**；**missing 已降至 MSTR 26 / FNGU 19 / SOXL 19，盲区门(<30)已过 → M1 实质达成**。
**当前唯一关键瓶颈：FNGU 历史只回到 2025-02-20（FNGS 到 2019-11-13），回测有效窗口被压到 ~15 个月，NEXT-3 校准在此数据上无效。** → 见 `CODEX_GUIDANCE.md` P0。

## 成熟度

| 等级 | 达成 | 证据 |
|---|---|---|
| M0 能跑 | ✅ | 78 单测绿 / 单日回放 |
| M1 看得清 | ✅(门已过) | missing 26/19/19 < 30；`N1_missing_rebaseline.md` |
| M2 验得过 | 🟡 受限 | `Backtest_FULL` 已出，但有效窗口仅 2025-02→2026-05（FNGU 缺口） |
| M3 校得准 | ⬜ | 阻塞于回测窗口；待 P0 合成历史 + NEXT-3 |
| M4 可上线 | ⬜ | 待人工 dry-run |
| M5 会学习 | ⬜ | 标签解锁门未达 |

## 基线（NEXT 工单）

| NEXT | 状态 | 备注 |
|---|---|---|
| NEXT-0 数据地基 | DONE-CODE / PARTIAL-DATA | backfill/pit/manifest/leg_proxy 完成；34/38 标的 ≤2018-01-02；**FNGU 仅 2025-02-20、FNGS 仅 2019-11-13** |
| NEXT-1 可历史化软数据 | IN-PROGRESS / 盲区门已过 | 已接 FRED·A5 / CBOE SKEW-VVIX·B4 / AAII·A2 / 成分宽度·A3 / MSTR BTC价代理·D-M3；**待接 PCR / NAAIM / BTC funding-basis-DVOL / GEX / social / valuation（增量，非阻塞）** |
| **P0 合成杠杆历史** | **TODO（新增·最高优先）** | **重建 FNGU/FNGS 2018+ 历史，解锁全窗口回测** |
| NEXT-2 回测引擎 | ACCEPTANCE-READY / 窗口受限 | runner/route-leg/Backtest_FULL/硬阀门矩阵已出；**需 P0 后重跑全窗口** |
| NEXT-3 参数校准 | TODO | 等 P0 + NEXT-2 全窗口 |
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
- 回测有效窗口：2025-02-20 → 2026-05-29（**待 P0 合成历史扩到 2018+**）
- 2026-05-29 回放：MSTR EXIT(H-M1,H-M4) / FNGU WATCH / SOXL WATCH；体制 LOW_VOL_TREND
