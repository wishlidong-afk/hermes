# Hermes 逃顶 + 镜像系统 — AI Agent 上下文文档

> 本文档专为新 AI agent 快速上手设计。读完本文后，agent 应能理解项目目标、架构、核心逻辑，以及每个主要文件的职责，无需再逐文件扫描代码。

---

## 1. 项目是什么

**Hermes** 是一套针对高波动/杠杆资产的**纯读取、永不下单**量化防御系统，分两个子系统：

| 子系统 | 目标资产 | 功能 |
|--------|---------|------|
| **逃顶 (escape-top)** | MSTR、FNGU、SOXL | 每日评分 → 卖出建议 + 仓位调整 |
| **镜像 (mirror)** | QQQ/FNGU、SOXX/SOXL、MSTR/QQQ | 周期参考配置，纯咨询，无硬阀门 |

**红线**：系统只输出建议，从不自动提交订单。所有 IBKR 连接均配置为 `readonly: true`。

---

## 2. 关键目录结构

```
hermes/
├── src/hermes_escape_top/          # 主包（所有逻辑代码在这里）
│   ├── pipeline.py                 # 生产日常入口：score_pipeline()
│   ├── config.py                   # 配置加载，CONFIG_PATH 指向 config/config.json
│   ├── integration_config.py       # 集成引擎参数（置信度/风险/sizing/验证）的单一来源
│   ├── cli.py                      # CLI 入口（bootstrap / backfill / score / serve）
│   │
│   ├── core/                       # 所有核心引擎
│   │   ├── contracts.py            # 冻结数据类：Field / Verdict / ConfidenceState / RiskState / SizingDecision
│   │   ├── pipeline.py             # 集成测试用 harness（非生产入口）
│   │   ├── data/                   # L1：数据获取 + 质量
│   │   ├── features/               # L2：技术指标 + 归一化 + 波动率 + 机制分类
│   │   ├── scoring/                # L3：A/B/C/D 评分 + 硬阀门
│   │   ├── decision/               # L4：verdict 判决 + action intents
│   │   ├── portfolio/              # L5：风险引擎 + 仓位优化
│   │   ├── routing/                # L6：资本路由（DEFCON 1/2/3）
│   │   ├── reentry/                # L7：三锁再入场
│   │   ├── confidence/             # 横向：决策置信度脊柱
│   │   ├── monitor/                # 横向：分布漂移监控
│   │   ├── governance/             # 横向：决策脆弱性 + 意见分歧
│   │   ├── factors/                # 横向：因子实验室
│   │   └── backtest/               # L8：确定性回放 + 验证
│   │
│   ├── mirror/                     # 镜像策略
│   ├── ibkr/                       # 只读 IBKR 接口
│   ├── web/                        # 只读 Web 仪表板（Flask 8766 端口）
│   ├── scripts/                    # 回测 / 门控 / 诊断脚本
│   ├── tests/                      # 390+ 单元/集成测试
│   └── config/config.json          # 运行时参数（唯一生效的配置文件）
│
├── docs/                           # 设计文档（重要：先读 00_MASTER_OVERVIEW.md）
├── building/reports/               # 历次回测/门控报告
├── data/                           # 运行时数据（CSV 历史 + 归档）
└── scripts/                        # 顶层运行脚本（run_daily_package.py 为日常生产入口）
```

**两个代码副本**：
- `~/Documents/github/hermes`（此 repo）= 代码唯一权威，无运行时状态
- `~/.hermes/skills/investment/escape-top/`（live runtime）= 生产副本，含真实数据/密钥，**绝不提交到 repo**

---

## 3. 系统架构：10 层流水线

```
每日输入（as_of 日期）
       │
       ▼
[L1] 数据层       core/data/          OHLCV + 软数据采集、质量标注、PIT 对齐
       │
       ▼
[L2] 特征层       core/features/      EMA/MA200/RSI14/MACD/Chandelier/VIX 百分位/机制分类
       │
       ▼
[L3] 评分层       core/scoring/       A/B/C/D 四模块 0-100 评分 + 硬阀门评估
       │
       ▼
[L4] 决策层       core/decision/      make_verdict() → 状态阶梯 + 卖出比例
       │
       ▼
[L5] 组合层       core/portfolio/     HAR-RV 波动预测 + EWMA 相关矩阵 + CVaR + SizingOptimizer
       │
       ▼
[L6] 路由层       core/routing/       DEFCON 1/2/3 减仓后资本路由
       │
       ▼
[L7] 再入场层     core/reentry/       三锁状态机（时间/分数/结构）
       │
       ▼
[L8] 回测层       core/backtest/      确定性历史回放（2018-2026）+ WF 验证 + PBO 门控
       │
       ▼
[L9] 镜像层       mirror/             平行的周期参考策略（无硬阀门）
       │
       ▼
[L10] 展示层      web/ + ibkr/        只读仪表板 + IBKR 持仓对账
       │
       ▼
  payload dict（全量 JSON，含 input_hash 保证确定性）
```

**横向贯穿全流程的 4 个引擎**：

| 引擎 | 文件 | 职责 |
|------|------|------|
| **置信度脊柱** | `core/confidence/spine.py` | 6 分量置信度（数据/来源/新鲜度/漂移/脆弱/分歧），低于阈值触发熔断 |
| **漂移监控** | `core/monitor/drift.py` | PSI 检测评分分布漂移 |
| **治理** | `core/governance/governance.py` | 决策脆弱性 + 多模型分歧检测 |
| **因子实验室** | `core/factors/lab.py` | IC 计算、因子聚类、阈值校准 |

---

## 4. 核心评分逻辑

### 4.1 四模块评分（满分 100）

| 模块 | 上限 | 内容 | 权重特点 |
|------|------|------|----------|
| **A（宏观/流动性/情绪）** | 20 | VIX百分位、AAII情绪、NAAIM、PCR、NDX广度、净流动性、VIX期限结构、A10实际利率、A11美元、A15防御轮动 | 信息风险敏感 |
| **B（个股/估值/过热）** | 25 | RSI14、EMA乖离、动量、期权、社交媒体(stub)、远期PE(unwired) | 当前有效上限≈16（B5/B6 尚未接入） |
| **C（技术破位）** | 35 | EMA20/50破位、MACD下穿、分散日、反转K线、相对背离、ATR Chandelier(22,4.5)、AVWAP、Minervini | 技术敏感，SOXL 权重×1.15 |
| **D（品种特有风险）** | 20 | MSTR→BTC背离/mNAV溢价；FNGU→FANG+广度/QQQ趋势；SOXL→半导体广度/SMH领头 | 各品种专属因子 |

**评分公式**：
```
加权原始分 = Σ(模块分 × 品种权重 × 机制乘数)
有效满分   = 100 - missing_weight
最终分数   = (加权原始分 / 有效满分) × 100
```

`missing_weight` 核心原则：**缺数据 ≠ 安全**，缺失越多越偏向防御。

### 4.2 硬阀门（Hard Valves）

触发后直接 100% EXIT，绕过分数阶梯：

| 品种 | 主要阀门 | 关键逻辑 |
|------|---------|---------|
| **MSTR** | H-M1～H-M6 | M1=跌破MA200；M2=单日-15%(已缓冲，见下)；M3=-22% 2日；M4=BTC破MA50+MSTR破EMA20；M5=分数≥80且C≥5；M6=Chandelier+60日回撤≥18% |
| **FNGU** | H-F1～H-F7 | QQQ/FNGS破位、±15%/−22%、Chandelier、EMA50+分散+VIX期限 |
| **SOXL** | H-S1～H-S8 | QQQ/SOXX/SMH破位、±15%/−22%、Chandelier、60日回撤≥25% |

**Suspect 缓冲**（`use_suspect_valve_guard=true`，已部署）：数据被标记为 suspect 时，硬阀门降级为 PENDING，等待次日干净收盘确认，防止坏 tick 误触发。

**H-M2 缓冲**（`use_hm2_buffer`，默认 OFF，回测否决）：孤立 H-M2 降级为 DEFENSIVE_EXIT，而非立即全清。

### 4.3 判决状态阶梯

```
HOLD < WATCH < TRIM < REDUCE < DEFENSIVE_EXIT < EXIT

阈值（config.json status_thresholds）：
  EXIT         ≥ 75
  DEFENSIVE_EXIT ≥ 70
  REDUCE       ≥ 50
  TRIM         ≥ 35
  WATCH        ≥ 20
  HOLD         < 20
```

**状态升级规则**（`make_verdict` 中）：
- C≥18 → 至少 REDUCE
- B≥18 且 C≥12 → 至少 DEFENSIVE_EXIT
- 红灯因子≥4 → 至少 REDUCE
- 杠杆品种且 QQQ < EMA20 → 至少 TRIM
- missing_weight > 30 → 状态上升一级（盲点惩罚）

### 4.4 卖出比例

| 状态 | MSTR | FNGU/SOXL |
|------|------|-----------|
| TRIM | 25% | 35% |
| REDUCE | 50% | 60% |
| DEFENSIVE_EXIT | 75% | 85% |
| EXIT | 100% | 100% |

`sell_fraction_mode="continuous"` 已部署：状态间按分数线性插值，消除阶梯跳变（已门控验证，性能中性）。

---

## 5. 资本路由（DEFCON）

发生 REDUCE 及以上或硬阀门时，减仓资金路由到：

```
DEFCON 1（宏观核弹）：A≥12 + QQQ 破 MA200/EMA50/EMA20
  → BOXX 50% + DBMF 30% + GLD 20%
  （现金+趋势跟踪+通胀对冲三腿）

DEFCON 2（内部破位）：A≥12 或 D≥10 或硬阀门 或 C8/C6≥3
  → BRK.B（主），若相关性>0.85 则 fallback BOXX

DEFCON 3（1x 去杠杆）：
  SOXL → SOXX
  FNGU → QQQ
  MSTR → BTC-USD（保留 BTC 论点，已门控 +1.90pp CAGR，PBO=0.31）
```

文件：`core/routing/capital_routing.py`，`route_capital()` 函数。

---

## 6. 再入场三锁系统

卖出后必须同时通过三个锁才能再入场：

1. **时间锁**：距上次卖出 ≥ 11 个交易日
2. **分数锁**：总分 < 19（情绪充分冷却）
3. **结构锁**：C 模块分 < 5 且背离已解除

三个分批（T1/T2/T3 = 30%/30%/40%）：
- **T1**：雷达收盘 > EMA20 + MACD 零轴附近上叉
- **T2**：T1 浮动 + 收盘 > 近20日高点 + EMA20 以上
- **T3**：T1/T2 浮动 + 市场（QQQ/SPY）创 252 日新高

文件：`core/reentry/plan.py`、`tracker.py`、`auto_confirm.py`。

---

## 7. 置信度脊柱

`core/confidence/spine.py`，`compute_confidence()` 聚合 6 个分量：

| 分量 | 来源 |
|------|------|
| data_conf | 字段完整度 + 质量惩罚 |
| source | 是否触发 failover（0.70 vs 1.0） |
| stale | 数据年龄指数衰减（tau=3天） |
| drift | PSI 因子分布漂移 |
| fragility | ±eps 扰动下决策敏感度 |
| agreement | 规则/元模型/镜像周期三者分歧 |

**聚合方式**：0.6 × min(分量) + 0.4 × 几何均值（最弱链偏置）

| 模式 | 阈值 | 行为 |
|------|------|------|
| NORMAL | ≥ 0.80 | 全信号 |
| CAUTION | 0.55-0.80 | 信号有效但不确定性升高 |
| DEGRADED | < 0.55 | 熔断，需要人工确认 |

---

## 8. 镜像系统

`mirror/strategy.py`，`build_mirror_plan()` 三个独立 sleeve，各有周期状态机：

| Sleeve | 上限 | 防御触发 |
|--------|------|---------|
| MSTR/QQQ | 15% | MSTR < EMA20 或 BTC < MA200 或 VIX > 30 |
| QQQ/FNGU | 20% | VIX > 30 或 QQQ 趋势破坏 |
| SOXX/SOXL | 30% | 衰退信号或 QQQ/SOXX 同破 |

镜像系统**无硬阀门**，纯参考，不影响逃顶决策。

---

## 9. 生产运行方式

### 日常入口

```bash
# 日常生产运行（实际生产在 .hermes，不是 repo）
PYTHONPATH=src python3 scripts/run_daily_package.py --live --commit-state

# Shadow 模式（测试用，不写入生产 archive）
PYTHONPATH=src python3 scripts/run_daily_package.py --as-of 2026-06-11 --skip-refresh

# Web 仪表板（端口 8766，从 repo 代码运行）
bash scripts/serve_escape_8766_repo.sh
# 或等价：
PYTHONPATH=src python3 -m hermes_escape_top.cli serve --host 127.0.0.1 --port 8766 --as-of latest
```

### 测试套件

```bash
# 390+ 测试，约 62 秒
PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

> **注意**：运行 `score_pipeline` 或 `serve` 会触发 `bootstrap_history`，会改写 `data/history/*.csv`。提交前必须执行 `git checkout -- data/history/` 还原，绝不 `git add -A`。

---

## 10. 配置文件详解

### `src/hermes_escape_top/config/config.json`（唯一生效的运行时配置）

关键字段：

| 字段 | 当前值 | 说明 |
|------|--------|------|
| `status_thresholds.EXIT` | 75 | 校准于 2026-06-08（从65改为70再到75） |
| `status_thresholds.DEFENSIVE_EXIT` | 70 | 同上 |
| `sell_fraction_mode` | `"continuous"` | 已部署：线性插值，消除阶梯跳 |
| `routing.defcon3.MSTR` | `"BTC-USD"` | 门控通过（+1.90pp CAGR，已部署） |
| `routing.defcon1` | BOXX50/DBMF30/GLD20 | 三腿门控通过（+1.59pp CAGR，已部署） |
| `features.use_suspect_valve_guard` | `true` | 门控通过，已部署 |
| `features.use_scored_missing_weight` | `true` | 门控通过，已部署（+0.062 OOS目标） |
| `features.use_partial_factor_eval` | `true` | 门控通过，已部署（回测无影响，live鲁棒） |
| `features.use_decision_stabilizer` | `false` | **门控失败**：OOS目标低于基线，保持关 |
| `features.use_hm2_buffer` | `false` | **回测否决**：中位前向收益骗人，保持关 |
| `features.data_real_rate` (A10) | `true` | 已部署（FRED DFII10） |
| `features.data_dollar` (A11) | `true` | 已部署（FRED DTWEXBGS） |
| `features.data_defensive_rotation` (A15) | `true` | 已部署（XLP+XLU+XLV / XLY+XLI+XLF） |

### `src/hermes_escape_top/integration_config.py`

集成引擎参数的单一来源（Phase II-IV 渐进式上线用）：
- 置信度脊柱参数（tau_stale=3，weakest_weight=0.60，normal=0.80，caution=0.55）
- 风险引擎参数（HAR-RV，EWMA λ=0.94，vol_budget=35%，CVaR budget=8%）
- Sizing 参数（dd_aversion=3.0，kelly 默认关，solver=slsqp_or_grid）
- 验证参数（n_groups=6，n_test=2，pbo_max=0.50，bootstrap_n=2000）

---

## 11. 主要文件一览

### 数据层 `core/data/`

| 文件 | 职责 |
|------|------|
| `base.py` | `Field`（含 value/source/as_of/is_proxy/latency_days/quality_penalty）和 `SymbolSnapshot` 数据契约 |
| `store.py` | `LocalStore`：CSV 历史读写，dated 归档管理 |
| `market.py` | `MarketData`：统一的快照/历史访问接口 |
| `adapters.py` | `collect_soft_data()`：所有软数据来源的统一采集 |
| `macro.py` | FRED 净流动性（WALCL-TGA-RRP）、VIX3M、VVIX、SKEW、PCR |
| `sentiment.py` | CNN Fear & Greed（stub）、AAII bull%、NAAIM 敞口 |
| `risk_signals.py` | 宏观风险信号：FredPercentileSource（A10/A11/A15等）和 EtfRatioPercentileSource |
| `quality.py` | `analyze_missing_fields()`：missing_weight 和 blind_spot 计算 |
| `sanitize.py` | `is_suspect_on()`：bad tick 检测（结构性零成交量系列自动豁免） |
| `state_store.py` | SQLite 状态存储：历史决策状态、执行确认 |
| `pit.py` | 点时对齐（Point-in-Time）：低频软数据按发布日期对齐，防未来函数 |
| `manifest.py` | 数据版本冻结（SHA256 manifest），保证回测可复现 |
| `failover.py` | 多源降级：主源失败时自动切换备源 |

### 特征层 `core/features/`

| 文件 | 职责 |
|------|------|
| `indicators.py` | EMA20/50、MA200、RSI14、MACD、ATR14、Chandelier(22,4.5)、AVWAP、CMF20、MFI14、AD 线 |
| `normalize.py` | 滚动百分位（窗口252，min60）、z-score |
| `volatility.py` | EWMA 波动预测、基准中位数、相对波动缩放器 |
| `regime.py` | 四状态机制分类：LOW_VOL_TREND/CHOP/HIGH_VOL/CRISIS + 退出迟滞（≥3天） |
| `context.py` | `MarketContext`：多资产相关性 + 相对强弱 |

### 评分层 `core/scoring/`

| 文件 | 职责 |
|------|------|
| `scorer.py` | `score_symbol()`：核心评分函数，组装 A/B/C/D → 硬阀门 → make_verdict |
| `registry.py` | `FactorRegistry`：`FactorDefinition(name, module, max_score, fn)` + 批量评估 |
| `module_a.py` | A1-A16：宏观/流动性/情绪因子定义（含 A10/A11/A15 已部署风险因子） |
| `module_b.py` | B1-B6：个股过热因子（RSI、EMA乖离、动量、期权、社交(stub)、估值(unwired)） |
| `module_c.py` | C1-C10：技术破位因子（EMA破位、MACD、分散日、Chandelier、Minervini等） |
| `module_d.py` | D-M/D-F/D-S：品种特有风险因子（MSTR/FNGU/SOXL 各6类） |
| `hard_valves.py` | `evaluate_hard_valves()`：H-M1-M6、H-F1-F7、H-S1-S8 触发逻辑，含 suspect 缓冲 |
| `result.py` | `ScoreResult`：完整评分结果数据类（含 explain 链） |
| `factors_risk.py` | A9-A19 风险信号因子定义（含 FRED 和 ETF 比率来源），通过 data_* flag 门控 |

### 决策层 `core/decision/`

| 文件 | 职责 |
|------|------|
| `verdict.py` | `make_verdict(VerdictInput)` → 状态/卖出比例/原因；`status_from_score()` 阈值映射 |
| `action_intents.py` | `build_action_context()`：为 WebUI 生成可读的行动意图 |
| `signal_journal.py` | 历史信号记录，提供 `trading_days_since_last_sell()` 给再入场锁 |

### 组合层 `core/portfolio/`

| 文件 | 职责 |
|------|------|
| `risk_engine.py` | `build_risk_state()`：HAR-RV 实现波动预测 + EWMA 相关矩阵（λ=0.94）+ Ledoit-Wolf 收缩 + CVaR 95% |
| `sizing_optimizer.py` | `optimize_targets()`：SLSQP/网格混合约束优化，输出 `SizingDecision` |
| `risk_budget.py` | `compute_portfolio_risk()`：gross_scaler ≤ 1.0（风险控制只减不加） |
| `invariants.py` | R3 不退化检验：中位 sleeve 永不比低位更激进（最终防线） |
| `sizing.py` | `size_portfolio()` 备用路径（optimizer 失败时 fallback） |
| `tax.py` | Wash-sale 和税损收割逻辑 |

### 回测层 `core/backtest/`

| 文件 | 职责 |
|------|------|
| `harness.py` | `ValidationHarness`：CPCV、PBO（防过拟合概率）、Bootstrap CI、DSR |
| `run_full.py` | 2018-2026 全窗口回测编排 |
| `simulator.py` | 含摩擦成本（5bps）的净值曲线模拟 |
| `replay.py` | 确定性历史评分回放（同 input 必然同 output） |
| `metrics.py` | Calmar、Sharpe、最大回撤、换手率、insurance_ratio |
| `reports.py` | JSON + Markdown 回测报告输出 |

### 路由层 `core/routing/`

| 文件 | 职责 |
|------|------|
| `capital_routing.py` | `route_capital()`：DEFCON 1/2/3 判断逻辑，输出 routing_explain |
| `leg_proxy.py` | 路由决策的组件代理腿 |

### 再入场层 `core/reentry/`

| 文件 | 职责 |
|------|------|
| `plan.py` | `build_reentry_plan()`：三锁评估 + T1/T2/T3 批次状态 |
| `tracker.py` | T1/T2/T3 状态机（MACD穿越/近20日高点/市场252日高点逻辑） |
| `auto_confirm.py` | 从 IBKR 执行记录推断执行确认 |
| `store.py` | SQLite 再入场状态持久化 |

### 顶层流水线 `pipeline.py`（生产入口）

`score_pipeline()` 的完整流程（按代码顺序）：

1. 加载配置 + LocalStore + MarketData
2. 构建快照宇宙（trade + market + radars + components + routing）
3. 采集软数据（FRED/AAII/NAAIM/PCR/VIX/ETF比率等）
4. 构建 SOFT 快照（统一注入软数据字段）
5. 计算当日机制（QQQ+VIX 输入 → LOW_VOL_TREND/CHOP/HIGH_VOL/CRISIS）
6. Suspect 检测（`use_suspect_valve_guard` 门控）
7. 读取历史决策状态（`use_decision_stabilizer` 门控）
8. 对每个 trade 品种调用 `score_symbol()` → ScoreBundle
9. 计算 target_weights + 组合风险预算
10. `_optimize_sizing()` → SizingOptimizer → SizingDecision
11. `route_capital()` → 路由决策
12. `build_reentry_plan()` → 再入场状态
13. `build_mirror_plan()` → 镜像参考配置
14. 计算后验 PnL（posterior_pnl）
15. IBKR 对账（只读）
16. 生成 payload（含 input_hash 保证可复现性）
17. 写 audit_log + signal_journal + state_db

### Web 层 `web/`

| 文件 | 职责 |
|------|------|
| `server.py` | HTTP 服务：GET `/`（仪表板）、POST `/api/score`（触发评分）、GET `/api/health_status` |
| `render.py` | 1600+ 行主仪表板 HTML/CSS/JS 渲染（分数面板/因子细节/路由计划/再入场状态/数据质量热图） |
| `mirror_render.py` | 镜像仪表板渲染（周期决策/各 sleeve 配置/规则检查） |
| `health.py` | `compute_health()`：数据新鲜度/manifest/数据质量/IBKR/缓存状态 → OK/DEGRADED/CRITICAL |
| `refresh.py` | 评分刷新编排 + M4 上线门控 |

### 诊断/门控脚本 `scripts/`

| 脚本 | 用途 |
|------|------|
| `run_daily_package.py` | **生产日常入口**，含 OHLCV 刷新 + 软数据刷新 + 评分 + 状态提交 |
| `backtest_flag_sweep.py` | Flag 参数扫描（每变体独立进程，防 OOM） |
| `flag_gate.py` | 13折 WF + PBO + DSR 门控（接受 argv 候选列表） |
| `run_gate.sh` / `run_routing_gate.sh` | 门控 shell 包装脚本 |
| `data_quality_audit.py` | 36个品种数据质量全审计 |
| `calibrate_next3_v2.py` | 阈值校准（读预计算 Backtest_*.json 缓存，扫描阈值组合） |
| `diagnose_mstr_hard_valves.py` | MSTR 硬阀门频率 + 前向收益诊断 |

---

## 12. 防过拟合原则

系统经历了大量因子探索后得出的核心教训：

1. **所有参数变更必须通过 13 折 WF + PBO 门控** — 门控失败的一律保持 OFF（F1/F2 稳定器、H-M2缓冲、NAAIM/PCR收紧均已失败）
2. **A 模块已饱和**（cap=20，A10/A11/A15 已填满）— 再加因子 = whipsaw
3. **系统处于局部最优**：6 年窗口的因子调整已耗尽且过拟合风险高
4. **真正新信号的来源**：轴 D MSTR 链上数据（CoinMetrics，免费，可回填，正交）；清洁的 arm-then-fire 重构
5. **median 前向收益会骗人**：要看 in-system 真实路径（H-M2 缓冲教训）

---

## 13. 当前性能基线与路由部署态（2026-06-11）

| 指标 | 值 | 来源 |
|------|------|------|
| 当前路由部署态 | DEFCON1 `BOXX50/DBMF30/GLD20`；DEFCON3 `SOXL->SOXX, FNGU->QQQ, MSTR->BTC-USD` | `src/hermes_escape_top/config/config.json` |
| 路由 freshness | FRESH: config routing block matches `BOXX50/DBMF30/GLD20` and `MSTR->BTC-USD` | config routing block + `_defcon3_note` 校验 |
| 路由门控依据 | ④ SOXL/FNGU are clean 3x→1x same-thesis de-levers. MSTR→BTC-USD: drops mNAV premium+single-name risk, keeps crypto thesis (live equiv: IBIT). Gate-approved 2026-06-10: combo variant, 13-fold WF PBO=0.31, OOS Δ+0.117, CAGR +1.90pp vs baseline. DEFCON1: BOXX50/DBMF30/GLD20 — gold adds inflation-hedge leg orthogonal to cash+trend (gate PBO=0.31, CAGR +1.59pp standalone). Rollback: MSTR→QQQ, DEFCON1 BOXX0.7/TREND0.3, remove extra_legs. | config `_defcon3_note` |
| routing-gate 本地产物 | `building/reports/routing_gate/` absent in this worktree | 本地文件检查 |
| 当前含 combo 对照基线 CAGR | 17.38% | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |
| 当前含 combo 对照基线 Max Drawdown | -13.77% | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |
| 当前含 combo 对照基线 Sharpe | 1.223 | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |
| 当前含 combo 对照基线 Calmar | 1.262 | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline row |
| 历史 capeff 参照 CAGR | 15.84% | `building/reports/capeff/baseline_deployed.json` |
| 部署 PBO | 0.153846 | `building/reports/Calibration_RiskFactors_2026_06_08.json` |
| 测试数量 | 401 `def test_*` | 静态统计 |
| 分支 | `hermes-docs` | git |

---

## 14. 关键设计原则（红线）

1. **永不下单** — 所有 IBKR 配置 `readonly: true`，代码无任何下单路径
2. **缺数据 ≠ 安全** — `missing_weight` 强制升级防御状态，blind_spot 触发额外惩罚
3. **硬阀门优先级最高** — 任何硬阀门触发 = 即时 100% EXIT，绝不被分数覆盖
4. **所有 flag 默认 OFF** — 新功能必须通过 PBO 门控后人工翻转，绝不静默上线
5. **确定性可复现** — 相同 input 必然相同 output；audit_log 附 input_hash；回测绑定 data_manifest_id
6. **R3 不退化** — 中位 sleeve 永不比低位 sleeve 更激进（sizing_optimizer 最终强制检查）
7. **人工门** — M4 shadow→live 切换需要人工翻转；所有 feature flag 需人工确认
8. **运行时数据不进 repo** — `data/history/*.csv`、`data/archive/`、`.hermes/` 均 gitignore

---

## 15. 文档导读顺序

想深入了解某一方面时，按此顺序读：

1. `docs/00_MASTER_OVERVIEW.md` — 整体视图（是什么/怎么用/现在在哪/下一步/红线）
2. `docs/01_FUNCTIONAL_SPEC.md` — 功能权威来源（A/B/C/D 规则/硬阀门/路由/再入场/镜像）
3. `docs/SYSTEM_OVERVIEW.md` — 架构十层图 + 每层验收标准 + 成熟度阶梯
4. `docs/INTEGRATION_ARCHITECTURE.md` — 统一系统：1 脊柱 + 4 引擎 + 1 优化器
5. `docs/FLAG_REGISTRY.md` — 所有 feature flag 的状态、门控结果、回滚路径
6. `building/reports/flag_sweep/GATE_REPORT.md` — 最新门控详情
7. `docs/RISK_FACTORS_CALIBRATION_2026_06_08.md` — A10/A11/A15 校准证据
