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
| 成熟度 | **M1 实质达成**：流水线通、82 单测绿；盲区门已过 |
| missing_weight | **MSTR 26 / FNGU 19 / SOXL 19（均 <30，盲区升级已解除）** |
| **当前唯一关键瓶颈** | **P0 合成管线已建，但 FNGU overlap 年化 TE 8.42% > 5%；P0.1 官方 FANG3X 诊断 TE 9.91% → proxy 窗口暂不能用于 P1/NEXT-3** |
| 已完成 | Phase 0–9、12 骨架；NEXT-0 代码、NEXT-1 已接 5 个可回溯软数据源、NEXT-2 回测 runner 与报告（窗口受限） |
| 待办 | **P0 修复 FNGU 合成跟踪误差** → NEXT-2 全窗口重跑 → NEXT-3 校准；其余软数据(PCR/NAAIM/BTC微观/GEX)增量补 |
| 安全 | 只读、不下单；所有 live 开关默认关 |

---

## 5. 接下来建什么（据真实进度重排，最高价值优先）

> 详见 `CODEX_GUIDANCE.md`（明确的下一步施工指引）。

1. **P0 合成杠杆历史（最高优先·当前唯一阻塞）**：代码/数据管线已建，FNGU/FNGS 均扩到 2018-01-02；P0.1 已接官方 `FANG3X/FANGT3X` 指数缓存与诊断，但 FNGU 严格 overlap TE 8.42%、官方 FANG3X 诊断 TE 9.91%，均未过 5% 门。下一步继续修 FNGU 合成质量，未过门前不启动 P1/NEXT-3。
2. **NEXT-2 全窗口重跑**：P0 后把回测从 ~15 个月扩到 2018→2026，real-only 与 full(含 proxy) 并排报告。
3. **NEXT-3 校准**：参数扫描（选稳健高原非峰值）+ 每模块达标门 + PBO；报告对合成段的敏感性。
4. **整合地基**：建 ConfidenceSpine / RiskEngine / SizingOptimizer，把组合/仓位从"乘法链"换成"单一风险源 + 约束优化"。→ `INTEGRATION_ARCHITECTURE.md` Phase 0–I
5. **增量并行**：补 NEXT-1 剩余软数据（PCR/NAAIM/BTC funding-basis-DVOL，进一步降 MSTR 的 26）。

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
