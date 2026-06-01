# escape-top Skill 搭建日志

**搭建时间**: 2026-05-26
**源文件**: `/Users/liweishi/Desktop/hermes_mstr_fngu_soxl_escape_top_prompt_副本.md` (668行)
**Skill 位置**: `/Users/liweishi/.hermes/skills/investment/escape-top/SKILL.md`
**分类**: investment
**当前版本**: v2.4

## 搭建规则

- ✅ 严格按照源 md 逐段转换，未做自由发挥
- ✅ 四模块 100 分制完整保留：A(大盘20) / B(过热25) / C(技术35) / D(专属20)
- ✅ 三标的独立评分逻辑完整（MSTR/FNGU/SOXL 各用专属 D 模块）
- ✅ 硬触发规则 15 条完整（每标的 5 条 + 冷却期规则）
- ✅ 卖出比例映射完整（MSTR vs FNGU/SOXL 两套 + 提升一级规则）
- ✅ 输出格式模板完整（9 个必填区块）
- ✅ 10 条严禁事项完整
- ✅ 11 条强制原则完整

## 触发词

- 逃顶 / escape top
- MSTR 逃顶 / FNGU 逃顶 / SOXL 逃顶
- 高波动标的减仓

## 文件清单

| 文件 | 路径 |
|---|---|
| SKILL.md | `/Users/liweishi/.hermes/skills/investment/escape-top/SKILL.md` |
| BUILD_LOG.md (本文件) | `/Users/liweishi/.hermes/skills/investment/escape-top/BUILD_LOG.md` |

## 验证状态

- ✅ Skill 创建成功
- ✅ YAML frontmatter 完整 (name/description/version/triggers)
- ✅ Skill 路径可发现 (investment/escape-top)

## v1.1 升级记录

**升级时间**: 2026-05-26

本次直接在源文件 `/Users/liweishi/.hermes/skills/investment/escape-top/SKILL.md` 上升级。

### 新增内容

- ✅ 新增“Python 预处理 + JSON 数据包 + Hermes/LLM 裁决”实盘架构
- ✅ 明确职责边界：Python 负责数据、指标、硬触发、状态；Hermes 负责裁决、解释、报告
- ✅ 新增推荐部署目录结构：`collect_data.py` / `score_engine.py` / `state.json` / `reports` / `orders` / `logs`
- ✅ 新增 `daily_score_precheck.json` 最小输入 schema
- ✅ 新增 `state.json` 最小状态 schema
- ✅ 新增状态流转规则：`HOLDING -> WATCH -> EXITED -> COOLDOWN`
- ✅ 强化硬规则优先级：`hard_trigger.triggered=true` 时 Hermes 不得降级
- ✅ 明确 Hermes 不直接下单，只能输出 `orders_preview`
- ✅ 固定 WATCH 档卖出比例为 `0%`，消除 `0-10% / 0-15%` 的执行歧义
- ✅ 输出模板新增：输入来源、状态文件、硬规则优先声明、状态更新建议、orders_preview
- ✅ 严禁事项新增：禁止直接下单、禁止 state 缺失时解除冷却期、禁止 LLM 重算 Python 指标

### 当前状态判断

- ✅ Prompt/Skill 层面：完整
- ✅ 实盘架构规范：已补齐
- ⚠️ 工程自动化层面：仍需另建实际脚本，例如 `collect_data.py`、`score_engine.py`、`state.json` 初始化文件和测试样例

## v1.2 工程系统搭建记录

**搭建时间**: 2026-05-26

本次不再只写 Markdown，已直接搭建可运行系统。

### 新增文件

| 文件 | 用途 |
|---|---|
| `config.json` | 标的、雷达、组件股、IBKR 只读端口、风险参数配置 |
| `state.json` | MSTR/FNGU/SOXL 状态、冷却期、上次动作 |
| `scripts/escape_top_system.py` | 核心采集、指标、评分、报告、订单预览引擎 |
| `scripts/collect_data.py` | 只采集 raw 数据 |
| `scripts/score_engine.py` | 对 raw 数据评分 |
| `scripts/run_daily.py` | 一键采集 + 评分 |

### 已验证

- ✅ `python3 -m py_compile` 通过
- ✅ `scripts/run_daily.py` 已成功执行
- ✅ 已生成 `data/daily_raw_data_2026-05-22.json`
- ✅ 已生成 `data/daily_score_precheck_2026-05-22.json`
- ✅ 已生成 `reports/daily_report_2026-05-22.md`
- ✅ 已生成 `orders/orders_preview_2026-05-22.json`
- ✅ CBOE Daily Market Statistics 抓取成功：Total/Index/Equity PCR 均可入库
- ✅ yfinance 历史 CSV 缓存已生成
- ⚠️ 本次 IBKR Gateway 未连接，系统已降级为无持仓模式，没有中断

### 当前工程完成度

- ✅ 本地可运行系统：已完成
- ✅ 数据采集：yfinance + CBOE + IBKR 只读尝试已完成
- ✅ 指标计算与硬触发：已完成
- ✅ JSON/报告/订单预览产物：已完成
- ⚠️ 自动云端定时任务：尚未创建 cron/launchd/systemd
- ⚠️ Alpha Vantage/Tiingo 付费/Key 备用源：尚未接入实盘 key

## v2.0 三大实盘补丁记录

**升级时间**: 2026-05-26

本次根据“最高指挥官 / 老威战术总参谋部”的补丁指令，直接修改 `SKILL.md` 与 `scripts/escape_top_system.py`，目标是修复 V1/V1.2 的三大物理漏洞：

1. SOXL 局部风险被总分稀释。
2. MA200 对 3 倍杠杆票过度滞后。
3. API 数据缺失被静默视为安全。

### 已实装补丁

- ✅ `SKILL.md` 升级到 `version: "2.0"`
- ✅ 新增 `1.4 数据缺失折算规则`
- ✅ 新增有效分公式：`AdjustedScore = RawScore / EffectiveMaxScore * 100`
- ✅ 新增缺失权重表和 `MissingScoreWeight > 30` 盲区惩罚
- ✅ 新增 SOXL 硬触发 `H-S6`
- ✅ `H-S6`: SOXL 从近 60 日最高点回撤 <= -25%，且收盘价跌破 EMA50，则 EXIT 100%
- ✅ 新增 `8.4 强制越权与局部熔断`
- ✅ `8.4.1`: SOXL `D-S2 >= 4` 且 `C5 >= 3`，最低 TRIM 35%
- ✅ `8.4.2`: SOXL `D 模块 >= 10/20`，防守级别连升两级
- ✅ `8.4.3`: 缺失权重 > 30，所有标的防守级别提升一级
- ✅ 代码中新增 `MISSING_SCORE_WEIGHTS`
- ✅ 代码中新增 `missing_data_analysis()`
- ✅ 代码中新增 `score_item_points()`
- ✅ 代码中新增 `promote_status()` 与固定卖出比例映射
- ✅ 报告输出新增 `RawScore / EffectiveMax / AdjustedScore`
- ✅ 报告输出新增 `MissingWeight`、盲区惩罚、越权规则

### 验证结果

使用已有 raw 数据 `/data/daily_raw_data_2026-05-22.json` 重跑评分：

| 标的 | RawScore | MissingWeight | EffectiveMax | AdjustedScore | v2.0 状态 | 卖出比例 | 触发原因 |
|---|---:|---:|---:|---:|---|---:|---|
| MSTR | 22.0 | 41.0 | 59.0 | 37.29 | EXIT | 100% | H-M1 + H-M4 |
| FNGU | 12.0 | 33.0 | 67.0 | 17.91 | WATCH | 0% | 盲区惩罚 |
| SOXL | 25.16 | 33.0 | 67.0 | 37.55 | REDUCE | 60% | 盲区惩罚 + D-S2 龙头背离 |

### 关键变化

- SOXL 不再被 15-20 分低总分掩盖；D-S2 龙头背离已进入 D 模块并在报告中明确显示。
- SOXL 从 `HOLD/WATCH` 提升到 `REDUCE 60%`，符合“高位震荡 + 3 倍杠杆 + 数据盲区”的保守原则。
- FNGU 因数据盲区从低分状态提升到 WATCH，不再静默视作安全。
- MSTR 硬触发仍最高优先级，直接 EXIT 100%。

### 已生成桌面日记

- `/Users/liweishi/Desktop/escape-top-build-diary.md`

## v2.1 估值分位过热模块记录

**升级时间**: 2026-05-26

本次根据“引入 PE 分位处理过热指标”的要求，直接把估值温度计接入实盘系统。设计原则是：估值分位不是单独硬触发，不能因为 PE 高就机械清仓；但当估值过热与 RSI、EMA 偏离共振时，必须提升防守级别。

### 已实装内容

- ✅ `SKILL.md` 升级到 `version: "2.1"`
- ✅ `scripts/escape_top_system.py` 升级 schema 到 `escape-top-v2.1` / `escape-top-score-v2.1`
- ✅ 新增 `data/valuation_snapshot.json` 读取入口
- ✅ 新增模板文件 `data/valuation_snapshot.example.json`
- ✅ 新增 `config.json -> valuation` 配置块
- ✅ 新增 B6：`PE/mNAV 估值分位，0-5 分`
- ✅ MSTR 不使用普通 PE，使用 `mNAV_premium_percentile` / `premium_percentile`
- ✅ FNGU 使用 FANG+ / FNGS / NYFANG 的 PE 或 Forward PE 历史分位
- ✅ SOXL 使用 SOXX / SMH / SOX 的 PE 或 Forward PE 历史分位
- ✅ 缺失估值分位时记录 `B6 valuation PE/mNAV percentile`
- ✅ `MissingScoreWeight += 5`，不允许把估值缺失当作安全
- ✅ 新增 8.3 估值共振升级：`B6 >= 3` 且 `B1 >= 2` 且 `B2 >= 2`，防守级别提升一级
- ✅ Markdown 日报新增“估值分位”关键数据行

### 当前说明

系统不会伪造 PE 分位。若 `/Users/liweishi/.hermes/skills/investment/escape-top/data/valuation_snapshot.json` 不存在，B6 会按缺失数据处理；如果把外部估值源或手工模型写入该文件，系统会立刻参与评分。

## v2.2 全量数据补全记录

**升级时间**: 2026-05-26

本次目标是消除 `MissingWeight 38~46` 的盲区，把 `build_dataset` 中硬编码为 `None` 的所有外部数据项逐一补全。新增 `enrich_data.py` 补全模块 + 缓存机制 + 自动估值快照生成。

### 已实装内容

- ✅ 新增 `scripts/enrich_data.py` — 全量数据补全模块
- ✅ CNN Fear & Greed 自动抓取（CNN graphdata API + alternative.me fallback）
- ✅ NDX 宽度自动计算（读取 history 缓存，计算 >50DMA/>200DMA 比例）
- ✅ FRED 宏观数据自动拉取（DXY/10Y/TGA/HY利差，含10日变化）
- ✅ FRED 不可用时 yfinance fallback（DXY/10Y）
- ✅ 社交热度自动估算（yfinance news count → z-score proxy）
- ✅ PE/mNAV 估值分位自动生成 `valuation_snapshot.json`
- ✅ OpenInsider 内部人交易检测（读取现有 cron 输出）
- ✅ 新增 `data/enrichment_cache.json` — 缓存机制，避免评分时重复拉取
- ✅ `escape_top_system.py` 的 `build_dataset` 接入补全数据
- ✅ `build_dataset` 优先读缓存 → fallback 实时拉取

### MissingWeight 变化对比

| 标的 | v2.1 MissingWt | v2.2 MissingWt | Δ | 盲区惩罚 v2.1 | 盲区惩罚 v2.2 |
|---|---|---|---|---|---|
| MSTR | 46 | **31** | -15 | True | True |
| FNGU | 38 | **23** | -15 | True | **False ✅** |
| SOXL | 38 | **23** | -15 | True | **False ✅** |

### 已补全数据项

| 数据项 | 权重 | v2.2 状态 | 来源 |
|---|---|---|---|
| CNN Fear & Greed | 2 | ✅ 58.6 (Greed) | CNN API |
| A2 cboe_equity_pcr | 4 | ✅ 0.55 | CBOE 抓取 |
| A3 NDX 宽度 | 4 | ✅ 50DMA=84.6%, 200DMA=76.9% | 本地history计算 |
| A5 DXY 10日 | 1 | ✅ +1.12% | yfinance |
| A5 10Y 10日bp | 1 | ✅ +16bp | FRED |
| A5 TGA | 1 | ✅ $781B | FRED |
| A5 HY利差 | 1 | ✅ 2.78% | FRED |
| B5 社交热度 | 4 | ✅ MSTR z=5, SOXL z=5 | yfinance news |
| B6 估值分位 | 5 | ✅ FNGS=95%, SOXX=95%, MSTR mNAV=92% | yfinance PE |

### 仍缺失项（需外部API/付费数据）

| 数据项 | 权重 | 原因 |
|---|---|---|
| A2 AAII | 2 | 每周发布，需专门爬虫 |
| A2 NAAIM | 4 | 每周四发布 |
| B4 期权数据 | 6 | 需付费期权链API |
| C7 AVWAP | 4 | 需手工标注突破日 |
| D-M3/M4/M5 | 11 | MSTR专属外部数据 |
| D-F4/D-S4 | 6 | 财报日历/政策新闻 |

### 新增文件

| 文件 | 用途 |
|---|---|
| `scripts/enrich_data.py` | 全量数据补全模块 |
| `data/enrichment_cache.json` | 补全数据缓存 |
| `data/valuation_snapshot.json` | 自动生成估值快照 |

### 日常使用

```bash
# 每日收盘后一键运行（自动补全 + 评分）
scripts/run_daily.py

# 手动刷新补全缓存（收盘后跑一次）
python3 scripts/enrich_data.py

# 仅重评分（使用已有缓存）
python3 scripts/score_engine.py --raw data/daily_raw_data_YYYY-MM-DD.json
```

## v2.3 缺数据代理 + 明确指令卡记录

**升级时间**: 2026-05-26

本次针对三个实盘问题修复：

1. 缺数据导致盲区。
2. 邮件输出不够清楚。
3. 报告只有分析，没有明确指令。

### 已实装内容

- ✅ `SKILL.md` 升级到 `version: "2.3"`
- ✅ `escape_top_system.py` 输出 schema 升级到 `escape-top-v2.3` / `escape-top-score-v2.3`
- ✅ `enrich_data.py` 真正写入 `data/enrichment_cache.json`
- ✅ 旧 enrichment cache schema 失效时自动重建，避免读旧缓存
- ✅ AAII Bull/Bear 用 CNN + CBOE PCR + NDX 宽度 + QQQ 偏离透明推算
- ✅ NAAIM 用 NDX 宽度 + QQQ 偏离 + VIX 透明推算
- ✅ FRED 无 API key 时改用 public CSV，保留 yfinance DXY/10Y 兜底
- ✅ NDX 宽度新增 10 日变化推算
- ✅ B4 期权热度接入 yfinance option chain；FNGU 可用 QQQ/FNGS 兜底，SOXL 可用 SOXX/SMH 兜底
- ✅ C7 使用 20 日平台低点 + 近 20 日高点锚定 VWAP 代理
- ✅ D-M3 使用 mNAV 估值快照评分
- ✅ D-M4 使用 BTC 10 日涨幅、波动率、RSI、EMA 状态做加密杠杆代理
- ✅ D-M5 接入 OpenInsider cron 输出；无内部人卖出时也算有数据
- ✅ D-F4 用 FANG+ 成分股新闻关键词代理财报/指引风险
- ✅ D-S4 用半导体链新闻关键词代理政策/地缘/指引风险
- ✅ `orders_preview` 新增明确语义：`SELL` / `SIGNAL_ONLY` / `NO_POSITION` / `NONE`
- ✅ 新增 `action_plan`，每只标的输出明确指令、订单状态、核心原因和执行说明
- ✅ `format_escape_top_plain.py` 改为直接读取 JSON，不再解析 Markdown
- ✅ `assemble_report.sh` 改为发送 JSON 驱动的“逃顶今日指令卡”

### 验证结果

使用 `/data/daily_raw_data_2026-05-22.json` 重跑：

| 标的 | RawScore | MissingWeight | EffectiveMax | AdjustedScore | 状态 | 卖出比例 | 订单语义 |
|---|---:|---:|---:|---:|---|---:|---|
| MSTR | 42.0 | 0.0 | 100.0 | 42.0 | EXIT | 100% | NO_POSITION |
| FNGU | 24.0 | 0.0 | 100.0 | 24.0 | WATCH | 0% | NONE |
| SOXL | 39.16 | 0.0 | 100.0 | 39.16 | REDUCE | 60% | NO_POSITION |

说明：三只标的 `MissingWeight` 已降为 0。AAII/NAAIM 使用代理推算，所以数据置信度保持 `Medium`，不冒充无条件 High。

## v2.4 3-3-4 战略预备队再建仓记录

**升级时间**: 2026-05-26

本次根据“高位斩仓后战略预备队现金池分批右侧再注入”的要求，把逃顶系统从单纯减仓框架升级为“逃顶 + 再建仓双向闭环”。核心原则：逃顶主系统仍然只负责卖出/减仓；再建仓只能由独立 `reentry_plan` 子程序输出 `BUY_PREVIEW`，不直接下单。

### 已实装内容

- ✅ `SKILL.md` 升级到 `version: "2.4"`
- ✅ `escape_top_system.py` 输出 schema 升级到 `escape-top-v2.4` / `escape-top-score-v2.4`
- ✅ 新增 `reentry_plan`：逐票输出 Phase0、T1、T2、T3、现金池动作、原因、止损/保护线
- ✅ Phase0 三锁：`Days_Since_Last_Sell >= 11`、`Total_Score < 19`、`C < 5 且 D 背离解除`
- ✅ T1 侦察火力：主雷达站上 EMA20 + MACD 零轴附近金叉，买入现金池 30% 预览
- ✅ T2 确认火力：T1 浮盈 + 主雷达突破 20 日最高收盘 + 站上 EMA20，买入现金池 30% 预览
- ✅ T3 主力压阵：T1/T2 浮盈 + QQQ 或 SPY 创 252 日最高收盘，买入现金池 40% 预览
- ✅ T3 防守分支：若 T1/T2 浮盈但大盘未创 252 日新高，最后 40% 保留在 BOXX/QQQ
- ✅ `state.json` 新增 `reentry` 字段：`stage / cash_pool_pct / t1_entry_price / t2_entry_price / t3_entry_price / stop_loss`
- ✅ `state_suggestions` 修复：已经进入现金池后不再因为风险信号仍在而反复重置 11 天冷却期
- ✅ `format_escape_top_plain.py` 与 `format_escape_top_html.py` 均展示 3-3-4 再建仓计划
- ✅ `assemble_report.sh` 操作建议区新增 3-3-4 摘要，并标记引擎为 escape-top v2.4
- ✅ 桌面操作文档更新：`/Users/liweishi/Desktop/逃顶.md`

### 当前验证结论

使用 `/data/daily_raw_data_2026-05-22.json` 重跑：

| 标的 | 逃顶状态 | 卖出比例 | 再建仓指令 | 现金池动作 | 原因 |
|---|---|---:|---|---:|---|
| MSTR | EXIT | 100% | LOCKED_SELL_RISK_ACTIVE | 0% | 逃顶/减仓信号仍在 |
| FNGU | WATCH | 0% | NO_CASH_POOL | 0% | state.json 未记录 last_exit_date |
| SOXL | REDUCE | 60% | LOCKED_SELL_RISK_ACTIVE | 0% | 逃顶/减仓信号仍在 |

结论：v2.4 当前没有触发任何买回。系统判断正确：MSTR 和 SOXL 仍处于逃顶/减仓风险；FNGU 没有确认的战略现金池来源，因此不允许凭空生成买入。

## v2.5 / NEXT-3 校准补完记录

**升级时间**: 2026-06-01

本次根据 GitHub `docs/CODEX_GUIDANCE.md` 与 `building/STATUS.md` 的最新版本，继续推进 NEXT-3 参数扫描与正式校准，并同步修复回测/测试链路。

### 已实装内容

- ✅ 新增 `scripts/calibrate_next3_v2.py`，基于 full-proxy 2018-2026 walk-forward + real-only 2025-2026 敏感性进行校准。
- ✅ 校准从“训练窗口贪心最优”改为“固定高原选择”：低 below-median OOS 频率优先，避免选尖峰。
- ✅ 选出候选参数 `EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20`。
- ✅ 新增 `config/artifacts/calibration_v2.json` 与 `reports/Calibration_v2.md`。
- ✅ 新增 `reports/NEXT3_CALIBRATION_LOG.md`，记录门控、指标、验证和剩余治理约束。
- ✅ 新增 `tests/test_next3_calibration.py`，覆盖 PBO、rank percentile、阈值网格和 fixed highland 排序。
- ✅ 优化 `core/routing/leg_proxy.py`，避免 `DBMF -> trend_synth` 在校准循环中重复重建。
- ✅ 修复 `tests/golden/test_v25_parity.py` 的浮点尾差误报，并重新生成 P0 合成历史后的 v25 golden fixture。

### 校准验收

| 验收项 | 结果 |
|---|---|
| Deployment fixed PBO | 0.1538，PASS |
| Train-greedy PBO | 0.6154，NOT PASSED，仅作为过拟合警报保留 |
| Full-proxy 2018-2026 | CAGR 17.54%，MaxDD -28.01%，Sharpe 0.8595 |
| Real-only 2025-2026 | CAGR 42.48%，MaxDD -10.63%，Sharpe 1.7273 |
| Real-only rank | 0.7692，PASS |

### 测试结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_next3_calibration hermes_escape_top.tests.test_next0_data_foundation hermes_escape_top.tests.test_phase8_routing`：14 tests OK。
- ✅ `python3 -m unittest discover -s tests`：11 tests OK。
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：90 tests OK。

### 当前结论

NEXT-3 标记为 `DONE / M3-COMPLETE / STABLE-HIGHLAND-PASSED`。生产/live 开关仍保持关闭；不得采用逐窗口贪心最优参数上线。

## P4 ConfidenceSpine 骨架记录

**升级时间**: 2026-06-01

本次继续从 P3/P4 后续施工中选择 P4 的最小可验收地基：公共契约 + 置信脊柱。该改造不改变当前评分/裁决结果，只为后续把数据质量、故障转移、漂移、脆弱度、多源分歧汇入统一 `decision_confidence` 做准备。

### 已实装内容

- ✅ 新增 `core/contracts.py`
  - `Field`
  - `Verdict`
  - `ConfidenceState`
  - `RiskState`
  - `SizingDecision`
- ✅ 新增 `core/confidence/spine.py`
  - `compute_confidence(...) -> ConfidenceState`
  - 组件：data/source/stale/drift/fragility/agreement
  - 缺失子信号按 0.5 中性不确定处理并写 note，不默认为安全
  - 模式输出：NORMAL / CAUTION / DEGRADED
- ✅ 新增 `tests/test_confidence_spine.py`

### 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_confidence_spine hermes_escape_top.tests.test_next3_calibration`：8 tests OK。
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：94 tests OK。
- ✅ `python3 -m unittest discover -s tests`：11 tests OK。

### 当前结论

P4 状态推进为 `IN-PROGRESS / PHASE0-CONTRACTS-SPINE-DONE`。下一步建议：RiskEngine 最小骨架或将 `ConfidenceState` 透传到只读报告。

## P4 GitHub 快照本地落地记录

**升级时间**: 2026-06-01

本次根据 GitHub `wishlidong-afk/hermes` 最新 `building/source_snapshots/P4_*`，把远端已经写入 building 的 P4 Phase 0-I + Pipeline 快照真正同步到本地 `.hermes` 实现，并修到全测试通过。

### 已同步组件

- ✅ Audit exporter
- ✅ Drift monitor
- ✅ FactorLab
- ✅ Governance
- ✅ Input guardrails：sanitize / failover
- ✅ MarketContext
- ✅ Integration config
- ✅ Unified pipeline
- ✅ Reentry tracker
- ✅ RiskEngine
- ✅ SizingOptimizer
- ✅ Tax awareness
- ✅ ValidationHarness

### 本地兼容修复

- ✅ `integration_config` 从 `hermes_escape_top/config/integration_config.py` 调整为 `hermes_escape_top/integration_config.py`，避免和既有 `config.py` 模块冲突。
- ✅ Python 3.9 日期字面量修复：`date(2026, 06, 1)` → `date(2026, 6, 1)`。
- ✅ `RiskEngine.downside_corr` 使用 full-sample correlation 作为尾部相关的保守 floor。
- ✅ `SizingOptimizer` shadow-mode expected-return proxy 调整，确保 confidence shrinkage 可被测试验证，且 R3 clamp 仍保持。
- ✅ `MarketContext` 测试改用 `.loc`，消除 pandas chained assignment 警告。

### 验证结果

- ✅ 焦点测试：49 tests OK。
- ✅ 包内全量：244 tests OK。
- ✅ golden 回放：11 tests OK。

### 当前结论

P4 状态推进为 `IN-PROGRESS / PHASE0-I-PIPELINE-LOCAL-SYNCED`。下一步建议：跑 Phase II shadow 对照，将 `core/pipeline.py` 接真实 store/scorer，产出 shadow-vs-current 报告。

## P5 Phase II Shadow 对照记录

**升级时间**: 2026-06-01

本次在 P4 统一管线落地后，继续推进 Phase II 只读影子对照。目标是让 `score_pipeline(...)` 接本地真实历史 store，同时复用既有 backtest 历史分数/裁决输入，比较新版 RiskEngine + SizingOptimizer 与旧 backtest sizing 的差异。

### 已实装内容

- ✅ 新增 `scripts/phase2_shadow_compare.py`
  - 读取 `reports/Backtest_FULL.json`
  - 默认回放最近 20 个交易日
  - 输出 `reports/PhaseII_Shadow_Compare.json`
  - 输出 `reports/PhaseII_Shadow_Compare.md`
- ✅ RiskEngine 数值稳定补丁
  - return series / DataFrame 统一数值化并过滤 `NaN/inf`
  - CVaR 向量乘法改用 `np.dot`，规避 macOS Accelerate 假阳性 RuntimeWarning
  - 新增非有限 return 输入单测
- ✅ SizingOptimizer SLSQP 例行裁剪告警屏蔽

### Shadow 对照结果

- rows evaluated: 20 / requested 20
- errors: 0
- R3 violations: 0
- max abs weight delta: 0.2747
- confidence modes: NORMAL × 20
- 最近 20 日多数出现 `EXTREME_CORR`，新版 shadow gross scaler 显著低于旧 backtest gross scaler，说明新风险层更保守。

### 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_risk_engine hermes_escape_top.tests.test_sizing_optimizer`：31 tests OK。
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：245 tests OK。
- ✅ `python3 -m unittest discover -s tests`：11 tests OK。

### 当前结论

P5/Phase II 状态推进为 `IN-PROGRESS / SHADOW-REPLAY-20D-DONE`。生产/live 开关仍保持关闭。下一步建议：扩展 shadow 窗口、解释 `EXTREME_CORR` 收缩来源，并在 Phase III 前完成风险预算参数校准。

## P5 Phase II 扩窗与相关闸敏感性记录

**升级时间**: 2026-06-01

本次继续推进 P5，把 20 日 shadow 对照扩到 252 个交易日，并把 `EXTREME_CORR` 从一个黑盒标签拆成可解释指标：普通相关均值、下行相关均值、ratio score、惩罚前 gross、惩罚后 gross。

### 已实装内容

- ✅ `RiskEngine.estimator_meta` 新增相关闸解释字段：
  - `corr_mean`
  - `downside_corr_mean`
  - `downside_corr_ratio_score`
  - `corr_elevated_threshold`
  - `corr_extreme_threshold`
  - `gross_before_corr_penalty`
  - `extreme_corr_penalty`
- ✅ `scripts/phase2_shadow_compare.py` 升级：
  - 252 日扩窗 replay
  - Risk Bindings / Correlation Regimes 统计
  - Corr Diagnostics
  - Most Defensive Rows
  - Interpretation 段落
- ✅ 新增 `scripts/phase2_corr_sensitivity.py`
  - 只读重算 correlation-regime penalty 层
  - threshold × penalty 网格敏感性
  - 输出 `PhaseII_Corr_Sensitivity.md/json`
- ✅ SizingOptimizer 风险 gross 接线
  - `risk_state.gross_scaler` 纳入仓位上限
  - 新增 `RISK_GROSS` binding 标签
  - shadow expected-return proxy 与 `dd_aversion` 对齐，避免 HOLD 袖套无 alpha 模型时被错误压到 0

### 252 日 Shadow 结果

- rows evaluated: 252
- errors: 0
- R3 violations: 0
- max abs weight delta: 0.1592
- confidence modes: NORMAL × 252
- avg shadow gross: 0.7229
- min shadow gross: 0.4111
- EXTREME_CORR share: 78.57%
- avg ordinary corr mean: 0.5135
- avg downside corr mean: 0.5567
- avg downside/ordinary ratio score: 115.2734

### 相关闸敏感性

- 当前默认 `threshold=92 / penalty=0.70`：hit share 78.57%，avg gross 0.7229。
- 只读 review candidate `threshold=110 / penalty=0.70`：hit share 40.48%，avg gross 0.8273，min gross 0.5770。
- 结论：当前 92 阈值偏保守，Phase III 前应以 110/0.70 或 120/0.80 作为校准候选进入完整回测，而不是直接上线。

### 当前结论

P5 状态推进为 `IN-PROGRESS / SHADOW-252D-CORR-SENSITIVITY-DONE`。生产/live 开关仍保持关闭。下一步建议：把相关闸候选参数接入 backtest sensitivity，而非只看 shadow gross。

## P5 Phase II Full Backtest Sensitivity 记录

**升级时间**: 2026-06-01

本次继续把相关闸候选从“shadow gross 敏感性”推进到“完整资金曲线 + walk-forward/PBO”验证。脚本仍为只读 shadow，不翻任何 live 开关。

### 已实装内容

- ✅ 新增 `scripts/phase2_full_backtest_sensitivity.py`
  - 读取 `Backtest_FULL_2018_2026.json` 的历史评分行
  - 每日跑一次统一 pipeline 风控缓存
  - 对 `threshold=[92,100,110,120,130,140,150]` × `penalty=[0.70,0.80,0.90]` 做 21 场景完整资金曲线
  - 输出 `PhaseII_Full_Backtest_Sensitivity.md/json`
- ✅ 性能优化
  - 场景 sizing 默认使用确定性的 `R3 × confidence × risk_gross` 上界投影
  - 价格面板只构建一次
  - 内部快速模拟器预计算日收益矩阵，避免二次复杂度回测
  - 保留 `--exact-optimizer` 给小窗口 SLSQP 复核
- ✅ Walk-forward 治理字段
  - train-greedy PBO
  - 每个固定参数的 OOS below-median share
  - 每个固定参数的 mean OOS rank
- ✅ 新增 `test_phase2_full_backtest_sensitivity.py`

### Full Backtest Sensitivity 结果

- rows evaluated: 2113
- errors: 0
- scenario count: 21
- R3 violations: 0
- baseline old backtest：Final $403,631.36 / CAGR 18.13% / MaxDD -27.60% / Sharpe 0.8818
- review candidate `threshold=110 / penalty=0.70`：
  - hit share: 39.71%
  - avg gross: 0.8447
  - min gross: 0.3595
  - Final: $401,635.03
  - CAGR: 18.06%
  - MaxDD: -22.47%
  - Sharpe: 1.0115
  - DSR: 0.8791
  - Fixed OOS below-median share: 0.3077
  - Mean OOS rank: 8.7692 / 21
- train-greedy PBO: 0.6154，说明逐窗口贪心选参仍然不可上线。

### 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_phase2_full_backtest_sensitivity`：5 tests OK
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：252 tests OK
- ✅ `python3 -m unittest discover -s tests`：11 tests OK（仅 urllib3/LibreSSL 环境警告）

### 当前结论

P5 状态当时推进为 `IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE`。`110/0.70` 可以作为 Phase III 前的 review candidate，但仍不能自动上线；后续 P6 已补完 dry-run comparator，Phase III scaler 替换仍需人工审 WARN 与人工开关。

## P5 Exact Optimizer Spot-check 记录

**升级时间**: 2026-06-01

为验证 full-window sensitivity 默认使用的快速上界投影是否偏离 SLSQP 精确优化，本次给脚本补了 `--start/--end/--suffix/--exact-optimizer`，可对指定窗口生成独立报告，避免覆盖主报告。

### 已实装内容

- ✅ `phase2_full_backtest_sensitivity.py` 新增：
  - `--start` / `--end` 日期过滤
  - `--suffix` 独立输出文件后缀
  - `exact_optimizer` 元数据落盘
- ✅ 新增单测：
  - date filter
  - suffix sanitizer
  - fast simulator 时序

### 抽样窗口

| 窗口 | 模式 | rows | errors | R3 | Final | CAGR | MaxDD | Sharpe | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020-01-03→2020-07-02 | exact | 126 | 0 | 0 | $113,421.98 | 29.17% | -9.08% | 1.3104 | 12.9647 |
| 2020-01-03→2020-07-02 | fast | 126 | 0 | 0 | $113,421.97 | 29.17% | -9.08% | 1.3104 | 12.9647 |
| 2022-01-03→2022-07-01 | exact | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 |
| 2022-01-03→2022-07-01 | fast | 125 | 0 | 0 | $96,392.78 | -7.01% | -6.73% | -1.0068 | 2.0904 |
| 2024-01-03→2024-07-03 | exact | 126 | 0 | 0 | $140,828.27 | 99.82% | -8.38% | 3.1997 | 19.7482 |
| 2024-01-03→2024-07-03 | fast | 126 | 0 | 0 | $140,828.27 | 99.82% | -8.38% | 3.1997 | 19.7482 |
| 2026-01-05→2026-05-29 | exact | 101 | 0 | 0 | $134,157.91 | 110.23% | -7.57% | 3.7111 | 26.6084 |
| 2026-01-05→2026-05-29 | fast | 101 | 0 | 0 | $134,157.91 | 110.23% | -7.57% | 3.7111 | 26.6084 |

### 结论

四个抽样窗口（2020 疫情、2022 压力、2024 牛市、2026 近端）exact 与 fast 仅有浮点级微差，R3 全部为 0，说明当前 `R3 × confidence × risk_gross` 快速投影在代表窗口与 SLSQP 精确优化路径一致。下一步可进入 dry-run 验收包设计。

## P5 Dry-run Acceptance Pack 记录

**升级时间**: 2026-06-01

- ✅ 新增 `reports/P5_DRY_RUN_ACCEPTANCE_PACK.md`
- ✅ 汇总 baseline vs 110/0.70 candidate
- ✅ 汇总 walk-forward governance、exact spot-check、human gate checklist
- ✅ 明确结论：可进入 shadow dry-run package，不可 live promotion

后续状态：daily old-vs-new dry-run comparator 已在 P6 完成；下一步改为人工审阅 WARN 日期，再决定是否进入 scaler migration。

## P6 Phase III Dry-run Comparator 记录

**升级时间**: 2026-06-02

本次把 P5 acceptance pack 里的 `Daily old-vs-new dry-run comparator` 从 TODO 补成可运行、可验收的只读干跑工具。

### 已实装内容

- ✅ 新增 `scripts/phase3_dry_run_compare.py`
- ✅ 新增 `tests/test_phase3_dry_run_compare.py`
- ✅ 逐日比较旧链路与候选 `threshold=110 / penalty=0.70`：
  - old target weights
  - candidate target weights
  - old route leg weights
  - candidate route leg weights
  - per-symbol delta
  - route leg delta
  - old/new turnover 与 delta
  - risk binding reason
  - `PASS` / `WARN` / `BLOCK`
- ✅ 生成 `reports/PhaseIII_Dry_Run_Comparator.md/json`
- ✅ 生成 smoke 报告 `reports/PhaseIII_Dry_Run_Comparator_smoke.md/json`
- ✅ 新增 `reports/P6_PHASE3_DRY_RUN_COMPARATOR_LOG.md`

### 252 日结果

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
| PASS | 128 |
| WARN | 124 |
| BLOCK | 0 |
| max abs symbol delta | 0.1293 |
| avg max abs symbol delta | 0.0425 |
| max abs route leg delta | 0.2802 |
| avg abs turnover delta | 0.0382 |
| max abs turnover delta | 0.4022 |
| avg old/new turnover | 0.2244 / 0.2285 |

### 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_phase3_dry_run_compare`：7 tests OK
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：260 tests OK
- ✅ `python3 -m unittest discover -s tests`：11 tests OK（仅 urllib3/LibreSSL 环境警告）

### 当前结论

P6 dry-run comparator 状态为 `DONE / HUMAN-GATE-READY`。候选链路没有 BLOCK/R3 硬伤，但 WARN 日期需要人工复核；live 开关继续保持关闭，不能自动上线。

## P7 Phase III WARN Review 记录

**升级时间**: 2026-06-02

本次把 P6 的 124 个 WARN 做成可审阅的人审前分析包，目标是回答：WARN 是不是集中在可解释的风险体制里？候选链路相对旧链路有没有明显收益拖累？是否存在新的 BLOCK 级问题？

### 已实装内容

- ✅ 新增 `scripts/phase3_warn_review.py`
- ✅ 新增 `tests/test_phase3_warn_review.py`
- ✅ 新增 `reports/PhaseIII_WARN_Review.md/json`
- ✅ 新增 `reports/P7_PHASE3_WARN_REVIEW_LOG.md`
- ✅ 对 WARN 做原因分类、月份分布、最大差异日排序
- ✅ 用本地价格面板计算 old route vs candidate route 的 1/5/10 交易日前瞻收益差

### 结果摘要

| 指标 | 结果 |
|---|---:|
| rows evaluated | 252 |
| PASS | 128 |
| WARN | 124 |
| WARN share | 49.21% |
| BLOCK | 0 |
| EXTREME_CORR WARN | 102 |
| ROUTE_LEG_DELTA WARN | 50 |
| TURNOVER_DELTA WARN | 28 |
| SYMBOL_DELTA WARN | 20 |
| LOW_GROSS WARN | 16 |
| WARN 1d candidate-old avg | -0.00% |
| WARN 5d candidate-old avg | -0.05% |
| WARN 10d candidate-old avg | -0.29% |

### 验证结果

- ✅ `python3 -m unittest hermes_escape_top.tests.test_phase3_warn_review`：4 tests OK
- ✅ `python3 -m unittest discover -s hermes_escape_top/tests`：264 tests OK
- ✅ `python3 -m unittest discover -s tests`：11 tests OK（仅 urllib3/LibreSSL 环境警告）

### 当前结论

P7 状态为 `DONE / WARN-REVIEW-PACK-DONE`。没有新增 R3/BLOCK 硬伤，但 WARN 10 日平均有轻微机会成本，readiness 仍为 `REVIEW_REQUIRED`；live promotion 继续保持 `BLOCKED`。
