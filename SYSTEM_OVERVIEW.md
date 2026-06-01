# HERMES ESCAPE-TOP v3 · SYSTEM OVERVIEW（系统全景与达标标准）

> 本文件是系统的「单页总览 + 达标标准 + 进度看板」三合一固定模板。
> 维护规则：Codex 每完成一个 NEXT，更新 §2 的「现态→目标态」、§6 的成熟度等级、以及文件头的元信息。
> 配套文档：施工工单见 `BUILD_TICKETS.md`（函数级），进度账本见 `STATUS.md`，校准档案见 `config/artifacts/calibration_vX.json`。

---

## 0. 元信息（每次更新刷新）

| 字段 | 值 |
|---|---|
| 文档版本 | v1.0 |
| 更新时间 | 2026-06-01 |
| 当前成熟度 | M0→M1 过渡（能跑，正在补数据降盲区） |
| data_manifest_id | 待 NEXT-0 freeze 后填写 |
| calibration 档案 | 未生成（NEXT-3 产出） |
| 当前 missing_weight (MSTR/FNGU/SOXL) | 42 / 31 / 31（>30，盲区升级中） |
| 安全状态 | 只读、不下单；所有 live 开关默认关 |

---

## 1. 理想全景图（十层链路 + 并行镜像 + 横切铁律）

```text
                              HERMES ESCAPE-TOP v3  ·  IDEAL PANORAMA
══════════════════════════════════════════════════════════════════════════════════════

  L0 数据源(外部)                          L1 数据层(data)                     横切层(贯穿所有)
 ┌───────────────────────┐     ┌──────────────────────────────────┐   ┌────────────────────┐
 │ 价格 yfinance/本地CSV   │     │ base(Field/Snapshot契约)          │   │ offline_replay闸门 │
 │ 宏观 FRED(WALCL/TGA/RRP)│────▶│ store(历史CSV+dated归档)          │   │  → 回放0外呼        │
 │ CBOE(VIX3M/SKEW/VVIX/PCR)│    │ market/flow/macro/sentiment/...   │   ├────────────────────┤
 │ AAII/NAAIM 周频         │     │ pit(时点对齐·防前视)              │   │ data_quality:      │
 │ 加密 funding/basis/DVOL │     │ quality(完整50/质量30/延迟20)    │   │  missing_weight    │
 │ [向前]GEX/CNN/新闻/mNAV │     │ manifest(数据版本hash·可复现)     │   │  + 盲区惩罚>30升级  │
 └───────────────────────┘     └───────────────┬──────────────────┘   ├────────────────────┤
                                                 ▼                       │ 缺数据≠安全        │
  L2 特征层(features)                  L3 评分核心(scoring)               │ 确定性/无前视       │
 ┌──────────────────────────┐   ┌──────────────────────────────────┐   │ 审计日志(可复现)    │
 │ indicators(EMA/MA/RSI/    │   │ registry(因子声明:依赖/上限/缺失)  │   │ 不下单             │
 │  MACD/ATR/Chandelier4.5x/ │──▶│ A≤20 B≤25 C≤35 D≤20               │   └────────────────────┘
 │  AVWAP/平台/CMF/MFI/AD)   │   │ scorer:标的加权→归一化百分制       │
 │ normalize(滚动分位/zscore)│   │  →缺失缩放→盲区惩罚                │
 │ volatility(EWMA前瞻波动)  │   │ ┌───────────────────────────────┐ │
 │ regime(4体制+非对称滞回)  │   │ │ hard_valves(H系列·纯函数·优先)│ │
 └──────────────────────────┘   │ └───────────────────────────────┘ │
                                  └───────────────┬──────────────────┘
                                                  ▼
  L4 裁决(decision)         L5 组合层(portfolio)        L6 路由(routing)        L7 再建仓(reentry)
 ┌────────────────┐   ┌──────────────────────┐   ┌────────────────────┐   ┌──────────────────┐
 │ 状态阶梯        │   │ risk_budget:          │   │ DEFCON1 BOXX+趋势   │   │ 三锁:时间11d/     │
 │ HOLD..EXIT     │──▶│  相关聚合+LedoitWolf   │──▶│ DEFCON2 BRK.B(自beta│──▶│  情绪<19/结构C<5  │
 │ 升级规则        │   │  +组合波动预算         │   │  监测→BOXX降级)     │   │ T1 30/T2 30/T3 40 │
 │ 稳定器+滞回     │   │  →gross_scaler≤1      │   │ DEFCON3 1x降维      │   │ 有卖出信号则锁定   │
 │ (硬阀门绕过)    │   │ sizing:相对基线vol目标 │   │ routing_explain     │   └──────────────────┘
 └────────────────┘   │  +末位clamp(R3不变式) │   └────────────────────┘
                       └──────────────────────┘
                                                  ▼
  L8 验证与校准(backtest)                      L9 学习(meta)            L10 展示/对账(web/ibkr)
 ┌──────────────────────────────┐   ┌────────────────────┐   ┌──────────────────────────┐
 │ replay(2018→2026确定性回放)   │   │ 回放backfill造样本  │   │ web 只读:评分/体制/组合/  │
 │ simulator(成本/滑点/路由腿)   │──▶│ purged+embargo CV   │──▶│  路由/再建仓/审计/数据质量 │
 │ metrics(Calmar/Sortino/      │   │ Deflated Sharpe     │   │ ibkr 只读对账(理想vs实际) │
 │  DD削减/CAGR拖累/保险比)      │   │ p_act(默认关·解锁门) │   │ 绝不下单                  │
 │ walk-forward + param_sweep   │   └────────────────────┘   └──────────────────────────┘
 │ → calibration_vX.json(档案)  │
 └──────────────────────────────┘

  并行子系统: 镜像参考系统(mirror) —— 右侧周期判断/理想配比/后验盈亏，无硬阀门、不下单
```

**每日刷新数据流**：`L1取数 → quality算missing → L2特征(分位/体制) → L3评分(A/B/C/D+硬阀门) → L4裁决 → L5组合gross+仓位clamp → L6路由 → L7再建仓 → L10展示+审计`

**回测/校准流**：`freeze manifest → 逐日build_snapshot → 同一评分链 → simulator → metrics → walk-forward OOS → param_sweep → 稳健选参 → calibration档案 → 每模块达标门`

---

## 2. 每一层达标标准（职责 / 硬标准 / 现态→目标态）

| 层 | 职责 | 达标硬标准（可度量） | 现态 → 目标态 |
|---|---|---|---|
| **L1 数据** | 取数、对齐、质量、版本化 | 离线 0 外呼；每字段带 source/as_of/is_proxy/latency；周/低频按**发布日**对齐(PIT)无前视；回测钉 `data_manifest_id`；缺则 None 不补 0 | 价格 DONE / 软数据 BLOCKED → **价格回填 2018+、可回溯软数据接入、missing<30** |
| **L2 特征** | 指标/分位/体制 | 全本地 OHLCV 可算；阈值走滚动分位(自校准)；t+1 突变不改 t；体制**风险态快进、出态 dwell≥3 日** | DONE → 维持 |
| **L3 评分** | A/B/C/D + 硬阀门 | 模块封顶 A20/B25/C35/D20；缺失缩放 `raw/(100-missing)*100`；missing>30 触盲区升级；每因子声明依赖/上限/缺失/score_fn；硬阀门优先于总分 | DONE(missing偏高) → **接数据后 missing<30，裁决不再被盲区人为抬升** |
| **L4 裁决** | 状态阶梯+升级+稳定器 | 阈值 80/65/50/35/20→EXIT..WATCH；软升级需二次收盘确认、硬阀门不等待；进/出滞回不同阈值 | DONE → 维持 |
| **L5 组合+仓位** | 总风险预算+波动率目标 | gross_scaler≤1(只减不增)；硬阀门腿排除 gross；vol 目标**相对自身基线**(SOXL 日常高波动 scaler≈1)；**R3 不变式 100% 成立**(末位 clamp) | DONE-CODE/未校准 → **回测校准后参数入档** |
| **L6 路由** | DEFCON 1/2/3 | 全 config 驱动无硬编码；匹配 1→2→3 即止；BRK.B 失效/高相关→降级 BOXX；输出 routing_explain | DONE → 维持(+趋势腿可选) |
| **L7 再建仓** | 3-3-4 + 三锁 | 时间 11 交易日/总分<19/C<5 且背离解除；有卖出信号或硬阀门强制锁定；T1/T2/T3=30/30/40 | DONE(持久化待补) → **T1/T2 活跃状态持久化** |
| **L8 验证校准** | 回测+扫描+达标门 | 2018→2026 确定性可复现；含成本/滑点；walk-forward OOS + Deflated Sharpe；选**稳健高原**非峰值 | PARTIAL → **出 Backtest_FULL + calibration_vX + 达标门报告** |
| **L9 学习** | 元标注 | 仅 purged CV 上报；普通 vs purged 差距展示；DSR>0；硬阀门绕过；`use_meta_label` 默认关 | LOCKED → 达解锁门才训 |
| **L10 展示/对账** | 只读 web + IBKR | UI 不改决策；审计日志可复现一次决策；IBKR 只读对账、断连标同步时间；**绝不下单** | web PARTIAL / IBKR 未接 → **接 IBKR 只读对账** |
| **镜像子系统** | 右侧周期参考 | 周期裁决+base/risk/cash×袖珍上限；后验现金腿 0 波动；无硬阀门、不下单 | DONE → 维持 |

---

## 3. 横切标准（任何模块都要满足）

| 横切项 | 硬标准 |
|---|---|
| 确定性 | 同输入连跑两次逐位一致；seed 固定；网络数据冻进版本化 CSV |
| 无前视 | 时序函数过"未来突变不改过去"断言；回测只用 ≤as_of；低频按发布日对齐 |
| 缺数据安全 | 缺失→missing_weight/盲区，**永不 0 占位、永不默认安全**；missing>30 升级防守 |
| 可复现 | 每份回测/校准报告头带 `data_manifest_id` + 参数档案版本 |
| 出处可溯 | 每字段 source/as_of/is_proxy/latency_days/quality_penalty 齐全 |
| 安全边界 | 任何路径不下单；`features.*`/`use_*` 翻 true 由人决定，Codex 只到达标为止 |
| 测试 | `unittest` 全绿；新模块行覆盖 ≥85%；硬阀门有历史触发测试 |

---

## 4. 量化达标门（校准放行用，提议初值，最终以 calibration 档案为准）

| 对象 | 达标门（OOS） | 不达标处理 |
|---|---|---|
| 组合风险预算(L5) | DD_reduction ≥ 相对 15% 且 Insurance_ratio ≥ 2.0 且 Calmar 优于买入持有 | 保持 shadow/off，人复核 |
| 波动率目标(L5) | Calmar 改善 ≥ 10% 且 Turnover 增幅 ≤ 25% 且 **R3 100%** | 同上 |
| 评分主链(TRIM+信号) | Precision ≥ 0.55、Recall ≥ 0.5、Brier 优于基准、假阳性代价可接受 | 调因子/权重 |
| 硬阀门(L3) | 历史已知暴跌全触发、合成干净上行 0 误触发 | 阻塞，必须修 |
| 数据(L1) | 三标的 missing_weight < 30；可回溯源 2018+ 覆盖率报告 | 继续补源 |
| 元模型解锁(L9) | 完成标签 ≥300、正样本 ≥40、覆盖体制 ≥2 | LOCKED |

---

## 5. 关键数值基线（config 单一事实源摘要）

| 项 | 值 |
|---|---|
| 袖珍上限 | MSTR 15% / FNGU 20% / SOXL 30% |
| 模块封顶 | A20 / B25 / C35 / D20 |
| 标的模块权重 | MSTR 0.90/0.95/1.00/1.25 · FNGU 1.10/0.90/1.10/1.05 · SOXL 0.90/0.95/1.15/1.25 |
| 状态阈值 | EXIT≥80 / DEFENSIVE_EXIT≥65 / REDUCE≥50 / TRIM≥35 / WATCH≥20 |
| 卖出比例(MSTR) | TRIM25/REDUCE50/DEF75/EXIT100 |
| 卖出比例(FNGU/SOXL) | TRIM35/REDUCE60/DEF85/EXIT100 |
| ATR 吊灯 | 22 日 × 4.5x |
| 盲区阈值 | missing_weight > 30 升级一级 |
| 组合(待校准) | corr_window 60 / vol_budget_annual 0.35 / extreme_corr_penalty 0.7 |
| 波动率目标(待校准) | relative_to_baseline / baseline 252 / floor 0.25 / EWMA |
| 体制滞回 | 进风险即时 / 出风险 dwell≥3 日 |
| 再建仓 | 时间锁 11d / 情绪锁<19 / 结构锁 C<5 / 30-30-40 |
| 元模型解锁 | 标签≥300 / 正样本≥40 / 体制≥2 |

---

## 6. 成熟度阶梯（升级钥匙 = §3/§4 对应硬标准）

```text
M0 能跑        : 流水线通、测试绿、单日回放有结果              [当前]
M1 看得清      : missing<30、盲区解除、数据可回溯              ← NEXT-0/1
M2 验得过      : 2018→2026回测 + walk-forward + 硬阀门历史触发  ← NEXT-2
M3 校得准      : 参数入档(稳健选参) + 每模块达标门通过          ← NEXT-3
M4 可上线      : 人逐个翻开关 + dry-run对照达标(shadow→live)   ← 人决定
M5 会学习      : 元模型解锁 + p_act 校准达标                    ← NEXT-5(条件满足)
```

| 等级 | 是否达成 | 达成日期 | 证据(报告/档案) |
|---|---|---|---|
| M0 能跑 | 是 | 2026-06-01 | 68 tests OK / 单日回放 |
| M1 看得清 | 否 | - | 待 N1_missing_rebaseline.md |
| M2 验得过 | 否 | - | 待 Backtest_FULL.md |
| M3 校得准 | 否 | - | 待 calibration_vX.json / Calibration_vX.md |
| M4 可上线 | 否 | - | 待人工 dry-run 对照 |
| M5 会学习 | 否 | - | 待 calibration_report.md(meta) |

---

## 7. 施工路线（NEXT 索引，详见 BUILD_TICKETS.md）

| NEXT | 内容 | 目标成熟度 | 状态 |
|---|---|---|---|
| NEXT-0 | 数据地基：价格史2018+ / 数据版本化 / 时点对齐 | → M1 前置 | TODO |
| NEXT-1 | 可历史化软数据接入（FRED/CBOE/PCR/AAII/NAAIM/BTC微观），降盲区 | → M1 | TODO |
| NEXT-2 | 回测引擎补全（2018→2026 + 成本 + walk-forward + 硬阀门历史触发） | → M2 | TODO |
| NEXT-3 | 参数扫描与正式校准（稳健选参 + 每模块达标门） | → M3 | TODO |
| NEXT-4 | 纯向前软数据（GEX/CNN/新闻/mNAV）+ dated 归档 | 增强 | TODO |
| NEXT-5 | 元模型回放 backfill + 训练（解锁门） | → M5 | LOCKED |
| NEXT-6 | IBKR 只读对账（绝不下单） | 增强 | TODO |

---

## 8. 安全红线（永不逾越）

1. 不下单——任何路径只产建议/理想仓位/订单预览。
2. 缺数据不等于安全——一律走 missing_weight/盲区。
3. 硬阀门语义冻结，优先于总分，触发即 EXIT。
4. 参数未经回测校准不得当最优；未经 OOS 达标不得上线。
5. `features.*`/`use_*` 由人翻开；Codex 只负责建到「达标/DONE」。
6. 回测结果必须钉死 `data_manifest_id`，否则不可信。

---

*维护说明：每个 NEXT 收尾时，更新 §0 元信息、§2 现态→目标态、§6 成熟度表、§7 状态列。本文件与 STATUS.md 双向对账。*
