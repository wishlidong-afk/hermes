# STATUS（进度账本）

> 每完成一步更新本表，并与 `00_MASTER_OVERVIEW.md` 元信息、`SYSTEM_OVERVIEW.md` 成熟度表对账。
> 更新时间：2026-06-01

## 成熟度

| 等级 | 达成 | 证据 |
|---|---|---|
| M0 能跑 | ✅ | 68 单测绿 / 单日回放 |
| M1 看得清 | ⬜ | 待 NEXT-1 missing<30 |
| M2 验得过 | ⬜ | 待 NEXT-2 Backtest_FULL |
| M3 校得准 | ⬜ | 待 NEXT-3 calibration 档案 |
| M4 可上线 | ⬜ | 待人工 dry-run |
| M5 会学习 | ⬜ | 待元模型解锁 |

## 基线（NEXT-0~6）

| 步 | 状态 | 备注 |
|---|---|---|
| 已建 Phase 0–9/12/14 | DONE | 数据/特征/评分/硬阀门/裁决/组合/路由/再建仓/镜像/WebUI 骨架 |
| NEXT-0 数据地基 | TODO | 价格史2018+ / 版本化 / PIT |
| NEXT-1 可历史化软数据 | TODO | 目标 missing<30 |
| NEXT-2 回测引擎 | TODO | 2018→2026 + walk-forward + 硬阀门触发 |
| NEXT-3 参数校准 | TODO | 稳健选参 + 达标门 |
| NEXT-4 向前软数据 | TODO | GEX/CNN/新闻/mNAV |
| NEXT-5 元模型 | LOCKED | 样本未达解锁门 |
| NEXT-6 IBKR 只读对账 | TODO | 绝不下单 |

## 整合（脊柱+4引擎+优化器）

| 组件 | 状态 |
|---|---|
| ConfidenceSpine | TODO |
| RiskEngine | TODO |
| FactorLab | TODO |
| MarketContext | TODO |
| ValidationHarness | TODO |
| SizingOptimizer | TODO |
| Governance | TODO |

## E 系列增强（E1–E30）

全部 TODO（基线达 M3/M4 后按 INTEGRATION Phase II–IV 接入）。优先：E1/E30/E9（安全）、E4/E11/E14/E12（风险结构）、E17/E7/E21（预警与严谨）。

## 系统级 7 道总闸

①单一风险源 ⬜ ②单一处置入口 ⬜ ③R3 100% ⬜ ④置信脊柱贯通 ⬜ ⑤PBO<0.5+CI+对抗AUC ⬜ ⑥因子健康+概率校准 ⬜ ⑦可解释可治理 ⬜

## 当前关键数字

- missing_weight：MSTR 42 / FNGU 31 / SOXL 31（>30 盲区升级中）
- 2026-05-29 回放：MSTR EXIT(H-M1,H-M4) / FNGU WATCH / SOXL WATCH；体制 LOW_VOL_TREND
