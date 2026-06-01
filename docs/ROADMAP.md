# ROADMAP（统一路线图）

> 把功能规格 → 架构 → 基线 → 增强 → 整合串成一条总时间线，并标出"当前可立即开工"。
> 每步的函数级细节见对应文档。

---

## 总时间线

```text
[已完成 M0/M1] Phase 0–9/12/14：数据/特征/评分(A-D)/硬阀门/裁决/组合/路由/再建仓/镜像/WebUI 骨架，253 package tests + 11 golden tests 绿
      │
[基线 → M1] NEXT-0 数据地基(价格史2018+/版本化/PIT) + NEXT-1 可历史化软数据 → missing<30
      │
[基线 → M2] NEXT-2 回测引擎(2018→2026 + 成本 + walk-forward + 硬阀门历史触发)
      │
[已完成 M3] NEXT-3 参数扫描+正式校准(稳健高原 + 每模块达标门 + calibration 档案)
      │
[整合地基] INTEGRATION Phase 0–I：ConfidenceSpine / RiskEngine / FactorLab / MarketContext /
           ValidationHarness 骨架 + SizingOptimizer（删除旧 scaler 乘法链）
      │
[增强接入] INTEGRATION Phase II–IV：把 E1–E30 作为插件接上
           II 风险与信号(E4/E5/E11/E13/E14 + E2/E3 + E7/E16/E17/E18/E19/E20)
           III 统一处置(E6/E8/E12/E15/E25/E26/E27)
           IV 验证与治理(E21/E22/E23/E24 + E9/E10/E28/E29)
      │
[人工上线 M4] 逐个翻 features.*/use_*，dry-run 对照达标（人决定）
      │
[学习 M5] NEXT-5 元模型解锁(标签≥300/正样本≥40/体制≥2) → p_act 校准达标
[增强] NEXT-4 纯向前软数据(GEX/CNN/新闻/mNAV) · NEXT-6 IBKR 只读对账
```

---

## 依赖图（谁挡着谁）

- `NEXT-1 软数据` 解除 30% 盲区，且喂 `NEXT-2 回测`。
- `NEXT-2 回测` 是 `NEXT-3 校准` 的唯一依据。
- `NEXT-3 校准` 决定组合/仓位参数能否上线。
- `RiskEngine + SizingOptimizer`（整合 Phase I）依赖 NEXT-2/3 的回测与校准。
- `E 系列` 几乎都作为插件挂在四引擎/脊柱/优化器上 → 必须先建地基。
- `元模型 NEXT-5` 依赖 `NEXT-2` 的回放 backfill 攒够样本。

---

## 当前可立即开工（据真实进度重排，2026-06-01）

> 现状：missing 已 <30（盲区门过）；P0 合成历史严格接缝调整门控已通过；P1 全窗口回测已完成；NEXT-3 稳定高原校准已完成。候选参数 `EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20`；deployment fixed PBO=0.1538 PASS；train-greedy PBO=0.6154 仅作过拟合警报。明确施工指引见 `CODEX_GUIDANCE.md`。

| 顺位 | 任务 | 文档锚点 | 价值 |
|---|---|---|---|
| ✅ P0 | 合成杠杆历史严格门控 | CODEX_GUIDANCE P0 | 已完成：FNGU TE 4.67%，corr 0.9986 |
| ✅ P1 | NEXT-2 全窗口回测 | BUILD_TICKETS NEXT-2 | 已完成：real-only CAGR 44.39% Sharpe 1.79 |
| ✅ P2 | NEXT-3 稳定高原校准 | BUILD_TICKETS NEXT-3 | 已完成：deployment PBO=0.1538 |
| ✅ P4 | 整合地基 Phase 0–I + Pipeline | INTEGRATION Phase 0–I | **已完成并落地本地：12 组件 + 253 package tests OK + 11 golden tests OK + E1–E30 全覆盖 + 7 闸结构验证** |
| **P5** | Phase II shadow/full sensitivity | PHASE_II_IV_ROLLOUT_PLAN | **252 日 shadow + 2113 日 full-window sensitivity 已跑通**：errors=0、R3 violations=0；review candidate 110/0.70，MaxDD -22.47%、Sharpe 1.0115、fixed OOS below-median 0.3077 |
| **P3** | 补 NEXT-1 剩余软数据 | BUILD_TICKETS NEXT-1 | PCR/NAAIM/BTC；可降 MSTR missing 8pt |
| **P6** | Phase III 替换旧 scaler → Phase IV 7 闸全通过 | SCALER_MIGRATION_GUIDE | 依赖 P5 验收 |

---

## 升级钥匙（达到每个里程碑必须满足）

| 里程碑 | 钥匙 |
|---|---|
| M1 看得清 | 三标的 missing_weight < 30；可回溯源 2018+ 覆盖率报告 |
| M2 验得过 | Backtest_FULL.md（含 walk-forward IS/OOS + DSR）；硬阀门历史触发 100% |
| M3 校得准 | calibration_vX.json + 每模块达标门通过（PBO<0.5） |
| M4 可上线 | 人工 dry-run 对照达标；逐个翻开关 |
| M5 会学习 | 元模型解锁门满足 + purged CV 指标达标 |

---

## 起步指令（给 Codex / Claude）

从 **P5 → P6 交界**继续：①对 110/0.70 做 `--exact-optimizer` 抽样复核；②做 dry-run 对照和人工验收包；③通过后再进入 Phase III scaler 替换；④并行补 P3 剩余软数据。

同步推进 **P3**：补 PCR/NAAIM/BTC funding-basis-DVOL CSV，降 MSTR missing。

> 安全：Codex 只做到"达标/DONE"为止；任何 `features.*`/`use_*` 翻 true 由人决定。
