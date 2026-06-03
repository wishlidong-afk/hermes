# CHANGELOG — 全部修改记录（review → 修复 → M4 迁移准备）

> 本文件汇总本轮工作对 Hermes 逃顶系统所做的**全部改动**,按时间/主题分组。
> 所有改动均已提交到 GitHub `hermes-docs` 分支;活盘代码在
> `~/.hermes/skills/investment/escape-top/`,仓库 `src/` 为其镜像(纯源码,不含数据/密钥)。
> 每条对应的详细说明见 `review/` 下的分项文档。

---

## 0. 起点:独立逐行 Code Review
- `review/CODE_REVIEW_FOLLOWUP.md` — 对项目自带复盘的独立补充,逐行 review 发现 10 项问题
  (脊柱旁路、双 gross、Kelly 误用、mu 退化、LW 死分支、EXTREME_CORR 估计量不一致、
  E12/E15/E26 死代码、CVaR 画饼、RC key ≥10 腿错位、SLSQP 回退未校验)。

## 1. 第一轮修复复审 + 二次修复（FIX_LOG_ROUND2）
`review/FIX_LOG_ROUND2.md`
- **pipeline.py** 🔴 置信脊柱接回真实信号源(原 getattr 全 None → 永久 DEGRADED);
  新增 `_data_confidence`(missing_weight 推导)、`_max_staleness_days`;去双 gross;删重复 import。
- **sizing_optimizer.py** 🔴 Kelly 默认关 + 启用须显式校准 `p_act`(禁止用 confidence 顶替);
  mu 改 `mu_mode`(默认 proxy 保姿态,opt-in historical_tilt);移除冗余 CVaR 约束;grid 用 itertools 泛化。
- **risk_engine.py** 🟡 EXTREME_CORR 改用同一估计量(`downside_vs_linear_ratio`);
  LW 诚实改名 `_shrinkage_intensity`;RC 用位置索引(修 ≥10 腿错位)。
- `review/verify_followup_fixes.py` — 25 项独立断言验证核心数学。

## 2. 落地 + 跑测试（RUN_LOG_TESTS_ROUND2）
`review/RUN_LOG_TESTS_ROUND2.md`
- 把修复落到 canonical `.hermes` 包;跑通官方测试套件。
- 修 5 个预存 numpy-2.4 失败(遗留 `core/portfolio/risk_budget.py` 的 `np.fill_diagonal(df.values)`
  在 pandas-2.x CoW 下只读 → 改用 `to_numpy(copy=True)`)。
- 真实数据 smoke test:confidence=0.696(非永久 DEGRADED)、仓位正常、drift PSI 实算。

## 3. 第三轮：drift 接线 / 回测验证 / Gate ① / 决策（ROUND3）
`review/ROUND3_COMPLETION.md`、`review/DECISIONS_AND_GOLDEN_AUDIT.md`
- **pipeline.py** drift 真信号:`_drift_state` 从 signal journal 算 PSI 喂脊柱;failover 诚实保留默认。
- **core/pipeline.py** 🟡 审计时间戳 `utcnow()` → as_of 锚定(恢复"逐位一致")。
- **tests/test_review_invariants.py** 新增 6 项回归守门(Kelly默认关/无p_act报错/flags默认关/
  健康≠DEGRADED/R3/只读红线)。
- v25 golden 决策中性重生成(0 status/sell_pct 翻转,仅浮点漂移)。
- 全窗口回测(exact optimizer)R3=0/errors=0;全网格 PBO train-greedy=0.077 → 接受 110/0.90。

## 4. 五轮全局 Code Review
`review/CODE_REVIEW_5PASS.md` — 正确性/架构/性能/可测性/安全 五视角;
`review/YELLOW_RED_FIXES.md` — 安全红黄项已修(确定性、回归守门、退役清单),
需确认项列出(数值稳健、三树合一等)。

## 5. M4 迁移准备(单体 → 包)
- `review/A_MIGRATION_PLAN_PARITY.md` — 核查发现:生产是 v25 单体,包是并行已验证重写;
  "canonical 包为真相"= M4 生产切换(人工门)。给出 parity 验收标准 + 工单 T1–T7。
- `review/T1_FEATURE_DIVERGENCE_MAP.md` — status 差异根因 = 特征"计算口径"不同(非阈值)。
- `review/T2_B1_RSI_COMPARISON.md`、`review/T2_COMPLETION.md` — 逐项口径对齐分析。
- **scripts/parity_harness.py / parity_harness_v2.py** — 单体 vs 包决策 parity harness。

### 特征对齐(B/C/A 模块,对照 SKILL.md 规格补全)
- **module_b.py** B1 RSI:daily + weekly(MSTR)/雷达(FNGU/SOXL)、分标的阈值;修误导 reason。
- **module_c.py** C6 分标的急跌阈值;C7 改 20-bar peak-anchored AVWAP + 20-bar 支撑。
- **module_a.py** 修 4 个真实 bug:A3 补"过热"侧(原只算恶化)、A4(QQQ拉伸)缺失补上、
  A1(VIX复杂度)缺失补上、A8 改 max(QQQ,SPY) 派发日。
- **indicators.py** 新增 `rsi14_weekly` / `avwap_anchored_20d` / `support_20d_low`。
- **market.py** INDICATOR_FIELDS 白名单补上述新字段。

### 操作壳 + WebUI
- **scripts/run_daily_package.py** — 包的每日运行操作壳(collect→score→翻译→写 4 产物),
  默认 shadow 模式;翻译层产出 monolith 兼容 schema,下游格式脚本零改动。
- **scripts/run_daily_shadow_compare.sh** — M4-2 影子并行 + 逐日 diff 日志。
- **web/server.py / web/render.py** — WebUI 重建 + M4-2(影子对比)/ M4-3(上线切换)按钮 +
  影子历史面板;dashboard 快速路径(读 precheck,不重跑)。

## 6. 正式重校准链（活盘评分纳入验证）
`review/calibration/Calibration_v2_relive.md`、`calibration_v2_relive.json`
- 用活盘评分(含 A 模块修复)重生成 `Backtest_FULL_2018_2026.json` + real-only 缓存;
  跑 `calibrate_next3_v2`。
- 结果:**next3_pass=TRUE,部署 PBO 0.1538(<0.5),全部门通过**;选定 **E75_D65_R50**;
  real-only Sharpe 1.73 / MaxDD −10.6%。
- **config.json** status_thresholds.EXIT **80 → 75**(校准部署值;备份 `.pre_e75_backup`)。
- 打通了"活盘评分 ↔ 回测/校准"此前的解耦裂缝。

---

## 改动文件清单（活盘 `.hermes`,均镜像到仓库 `src/`）

| 文件 | 改动主题 |
|---|---|
| `core/portfolio/risk_engine.py` | EXTREME_CORR / LW / EWMA / HAR ridge / RC key |
| `core/portfolio/sizing_optimizer.py` | Kelly / mu_mode / CVaR / grid |
| `pipeline.py` | 脊柱接回 + drift + 去双 gross + 单一 gross 上报 |
| `core/pipeline.py` | 审计时间戳 as_of 锚定(确定性) |
| `core/scoring/module_a.py` | A1/A3/A4/A8 真 bug 修复 |
| `core/scoring/module_b.py` | B1 RSI 口径对齐 |
| `core/scoring/module_c.py` | C6/C7 口径对齐 |
| `core/features/indicators.py` | rsi14_weekly / anchored AVWAP / 20d 支撑 |
| `core/data/market.py` | 字段白名单扩充 |
| `config/config.json` | EXIT 80→75(重校准) |
| `web/server.py`, `web/render.py` | WebUI + M4 按钮 |
| `scripts/run_daily_package.py` | 包每日操作壳 |
| `scripts/run_daily_shadow_compare.sh` | 影子并行 |
| `scripts/parity_harness.py`(+v2) | 单体↔包 parity |
| `tests/test_review_invariants.py` | 回归守门(新增) |
| `core/portfolio/risk_budget.py`(遗留树) | numpy-2.4 fill_diagonal 修复（**仅活盘,未镜像**——遗留重复树）|

## 当前状态
- 测试 **322 passed / 0 failed**;部署 PBO **0.1538**;硬阀门安全门达标。
- 活盘评分**端到端验证**(unit + 真实数据 + 全窗口回测 + 重校准)。
- M4 剩余:人工跑影子期(M4-2 按钮)≥5 日 → 人工翻闸(M4-3 按钮)。
