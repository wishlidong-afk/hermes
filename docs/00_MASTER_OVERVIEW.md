# 00 · MASTER OVERVIEW（终极全貌）

> Hermes 入口文档。读完这一页，你就掌握整个系统的"是什么、长什么样、现在到哪、接下来建什么、不许碰什么"。
> 细节下钻见同目录其它文档（见末尾文件地图）。

---

## 1. 这是什么

两套并行的**只读**投资系统（绝不下单，只产建议/理想仓位/资金路由/审计）：

- **逃顶系统**：对高 beta/杠杆资产 **MSTR / FNGU / SOXL** 做"高位防守/减仓/清仓/资金路由/再建仓审计"。百分制评分 + 模块权重 + 硬阀门。
- **镜像参考系统**：对 **QQQ/FNGU、SOXX/SOXL、MSTR/QQQ** 做"右侧周期判断/理想配比/参考建仓"。周期规则判断，无硬阀门。

核心立场：①不下单；②缺数据 ≠ 安全；③硬阀门优先于总分；④参数未经回测校准不得当最优、不得上线；⑤所有 live 开关由人翻。

---

## 2. 终极架构（整合后的统一视图）

系统是**十层单向链路 + 一条置信脊柱 + 四个共享引擎 + 一个统一仓位优化器 + 治理层**：

```text
L0 数据源 ─▶ L1 数据层 ─▶ L2 特征层 ─▶ L3 评分(A/B/C/D + 硬阀门) ─▶ L4 裁决
                                                                        │
   ┌───────────────────── 横切：置信脊柱(ConfidenceSpine) ────────────────┐
   │  汇总 数据净化/故障转移/漂移/脆弱/分歧 → decision_confidence + mode    │
   └──────────────────────────────────────────────────────────────────────┘
L5 组合层(RiskEngine 单一风险源 → SizingOptimizer 统一处置, R3不更激进)
   ─▶ L6 资金路由(DEFCON 1/2/3) ─▶ L7 3-3-4 再建仓
   ─▶ L8 回测/校准(ValidationHarness) ─▶ L9 学习(元模型, 默认关) ─▶ L10 只读展示/IBKR对账

并行：镜像参考系统（独立、轻量）
```

四个共享引擎（整合的关键——避免 30 个增强各自为政）：

| 组件 | 职责 | 取代了什么混乱 |
|---|---|---|
| **ConfidenceSpine** | 唯一"可信度仲裁" → confidence + NORMAL/CAUTION/DEGRADED | 散落各处的置信信号 |
| **RiskEngine** | 唯一协方差源 → 波动/CVaR/风险贡献/因子暴露/相关体制 | 多套互相打架的协方差 |
| **FactorLab** | 因子 IC/去相关/剪枝 + 分数概率校准 | 因子重复计数、阈值拍脑袋 |
| **MarketContext** | 多标的×多周期上下文（体制/领先滞后/背离/多周期） | 信号各自重取数据 |
| **ValidationHarness** | CPCV+PBO / 自助CI / 对抗验证 / 样本增强 | 过拟合无人量化 |
| **SizingOptimizer** | **唯一处置入口**：约束优化取代 scaler 乘法链 | 10 个 scaler 连乘的脆弱链 |

---

## 3. 三层演进（从能跑到机构级）

```text
基线  NEXT-0~6 ：补数据降盲区 → 2018→2026 回测 → 参数正式校准   →  达 M3/M4「可信、可上线」
安全  E1–E10   ：数据净化/概率校准/尾部CVaR/HAR-RV/体制预警/漂移/归因熔断
机构  E11–E30  ：动态相关/流动性/风险归因/CPPI/领先滞后/CPCV-PBO/效用Kelly/故障转移
整合  脊柱+4引擎+1优化器（Phase 0–IV）：把 E1–E30 作为插件接在地基上，而非 30 个 bolt-on
```

- 详细功能规则 → `01_FUNCTIONAL_SPEC.md`
- 架构与达标标准 → `SYSTEM_OVERVIEW.md`
- 基线工单 → `BUILD_TICKETS.md`；增强工单 → `ENHANCEMENTS.md`；整合 → `INTEGRATION_ARCHITECTURE.md`
- 串成一条总时间线 → `ROADMAP.md`

---

## 4. 当前状态（截至 2026-06-01，据 Codex 真实进度）

| 维度 | 现状 |
|---|---|
| 成熟度 | **M3 实质达成**：247 package tests OK + 11 golden tests OK；盲区门已过；NEXT-3 稳定高原校准通过；P4 已落地本地 `.hermes`；P5 Phase II 252 日 shadow + 相关闸敏感性已跑通 |
| missing_weight | **MSTR 26 / FNGU 19 / SOXL 19（均 <30，盲区升级已解除）** |
| 基线 | P0/P1/P2 全部 DONE：合成历史 TE 4.67%；real-only CAGR 44.39% Sharpe 1.79；deployment PBO=0.1538 |
| 校准 | `E75_D65_R50`：EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20 |
| **P4 整合** | **Phase 0–I + Pipeline DONE**：12 组件骨架（脊柱+4引擎+优化器+治理+净化+转移+漂移+Pipeline+Config）；E1–E30 全覆盖；7 闸结构验证通过 |
| **P5 Shadow** | **Phase II 252 日 shadow 已跑通**：rows=252、errors=0、R3 violations=0、confidence NORMAL×252；`EXTREME_CORR` share 78.57%；相关闸 review candidate 为 threshold=110 / penalty=0.70 |
| 待办 | 相关闸候选 full backtest/walk-forward 校准；补剩余软数据；Phase III/IV |
| 安全 | 只读、不下单；所有 feature flags 默认 OFF |

---

## 5. 接下来建什么（据真实进度重排，最高价值优先）

> 详见 `CODEX_GUIDANCE.md`（明确的下一步施工指引）。

1. ~~**P0 合成杠杆历史**~~：✅ DONE — TE 4.67%，corr 0.9986。
2. ~~**P1 全窗口回测**~~：✅ DONE — real-only CAGR 44.39% Sharpe 1.79。
3. ~~**NEXT-3 校准**~~：✅ DONE — deployment PBO=0.1538。
4. ~~**P4 整合地基**~~：✅ **Phase 0–I + Pipeline DONE** — 12 组件 + 247 package tests OK + 11 golden tests OK + E1–E30 全覆盖 + 7 闸验证，并已同步落地本地 `.hermes`。详见 `building/reports/P4_INTEGRATION_PHASE0_I_REPORT.md` 与 `building/logs/P4_LOCAL_SNAPSHOT_SYNC_LOG.md`。
5. **Phase II shadow 对照**：✅ 252 日样本 + 相关闸敏感性已跑通；下一步把候选参数接入完整回测。→ `building/reports/PhaseII_Shadow_Compare.md` 与 `building/reports/PhaseII_Corr_Sensitivity.md`
6. **补剩余软数据**：PCR/NAAIM/BTC funding-basis-DVOL → 降 MSTR missing。
7. **Phase III/IV**：替换旧 scaler 链 → 7 闸全通过。

完整次序与依赖见 `ROADMAP.md`；明确施工指引见 `CODEX_GUIDANCE.md`。

---

## 6. 七条系统级总闸（整合成功的判据）

①单一风险源 ②单一处置入口（无 scaler 连乘）③R3 不变式 OOS 100% ④置信脊柱贯通 ⑤防过拟合(PBO<0.5+CI+对抗AUC) ⑥因子健康+分数概率校准 ⑦可解释可治理。

---

## 7. 文件地图

```
README.md                          索引 + 阅读路线
docs/
  00_MASTER_OVERVIEW.md            ← 你在这里（终极全貌）
  CODEX_GUIDANCE.md                ★明确的下一步施工指引（Codex 先看这个）
  01_FUNCTIONAL_SPEC.md            功能规格（事实源：因子/硬阀门/路由/再建仓/镜像）
  SYSTEM_OVERVIEW.md               系统全景（L0–L10 / 达标标准 / 成熟度）
  BUILD_TICKETS.md                 基线 NEXT-0~6 函数级工单
  ENHANCEMENTS.md                  E1–E30 进阶提升工单
  INTEGRATION_ARCHITECTURE.md      整合：1脊柱+4引擎+1优化器
  ROADMAP.md                       统一路线图（总时间线 + 当前可开工项）
  STATUS.md                        进度账本
```
