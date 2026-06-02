# Hermes 逃顶 + 镜像系统 · 文档系统（终极全貌）

本仓库是 Hermes 投资防守系统的**统一文档系统**：把"功能规格 → 系统架构 → 基线施工 → 进阶增强 → 整合架构"拢成一套，有入口、有层次、有路线。Hermes/Codex 读这一套即可掌握终极全貌并继续搭建。

> 性质：只读风控/建议系统，**不下单**。覆盖标的 MSTR / FNGU / SOXL（逃顶）+ QQQ/FNGU、SOXX/SOXL、MSTR/QQQ（镜像）。

> **Codex 从这里开始施工 →** [`docs/CODEX_GUIDANCE.md`](docs/CODEX_GUIDANCE.md)（当前：P0 合成历史、P1 全窗口回测、NEXT-3 稳定高原校准、P4 Phase 0–I + Pipeline 已完成并落地本地；P5 Phase II 252 日 shadow、相关闸敏感性、2113 日 full-window sensitivity 已跑通；P6/P7/P8/P9 Phase III 人审与 full/exact 复核已完成；下一步生成 updated migration acceptance pack，并并行补 P3 软数据）。

## 阅读路线（按顺序）

| # | 文件 | 作用 | 读者 |
|---|---|---|---|
| 0 | [`docs/00_MASTER_OVERVIEW.md`](docs/00_MASTER_OVERVIEW.md) | **终极全貌**：是什么/架构/三层演进/现状/下一步/安全红线 | 先读这个 |
| ★ | [`docs/CODEX_GUIDANCE.md`](docs/CODEX_GUIDANCE.md) | **明确施工指引**：P0~P4 已完成，P5 full-window sensitivity 已跑通，P3/P6 当前施工优先级 | Codex 动手前必读 |
| 1 | [`docs/01_FUNCTIONAL_SPEC.md`](docs/01_FUNCTIONAL_SPEC.md) | **功能规格（事实源）**：A/B/C/D 因子、硬阀门、缺数据、裁决、路由、再建仓、镜像 | 想知道"系统怎么判" |
| 2 | [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md) | **系统全景**：L0–L10 十层架构、数据流、达标标准、成熟度阶梯 | 想看架构 |
| 3 | [`docs/BUILD_TICKETS.md`](docs/BUILD_TICKETS.md) | **基线施工**：NEXT-0~6 函数级工单（到 M3/M4） | 要动手建基线 |
| 4 | [`docs/ENHANCEMENTS.md`](docs/ENHANCEMENTS.md) | **进阶提升**：E1–E30 函数级工单 | 基线之后增强 |
| 5 | [`docs/INTEGRATION_ARCHITECTURE.md`](docs/INTEGRATION_ARCHITECTURE.md) | **整合架构**：1 脊柱 + 4 引擎 + 1 优化器，把 E1–E30 系统化整合 | 整合落地 |
| 6 | [`docs/ROADMAP.md`](docs/ROADMAP.md) | **统一路线图**：把上述全部串成一条总时间线 + 当前可开工项 | 决定先做什么 |
| — | [`docs/STATUS.md`](docs/STATUS.md) | **进度账本**：每步状态，与各文档对账 | 持续更新 |

## 一句话总览

```
功能规格(怎么判) → 架构(分十层) → 基线NEXT-0~6(建到可信M3/M4)
→ 增强E1-E30(安全/信号/风险/验证/治理) → 整合(脊柱+引擎+优化器) → 人工上线(M4)
```

## 三条不可破的红线

1. **不下单**——只产建议、理想仓位、订单预览。
2. **缺数据 ≠ 安全**——一律走 missing_weight + 盲区惩罚。
3. **硬阀门优先于总分，触发即 EXIT；参数未经回测校准不得上线，开关由人翻。**
