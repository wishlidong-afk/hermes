# Hermes 逃顶 + 镜像系统 - Agent 上下文

<!-- HERMES_GOVERNANCE_SNAPSHOT_START -->
```json
{
  "baseline": {
    "effective_end": "2026-07-17",
    "equity_timing": "next_open",
    "evidence_status": "CURRENT_EXECUTION_EVIDENCE",
    "git_commit": "148c8752b5558f59d560db288a9eb155b2096e77"
  },
  "config_version": "escape-top-v3.0-greenfield",
  "disabled_features": [
    "data_cnn_fgi",
    "data_concentration",
    "data_cot_nq",
    "data_credit_etf",
    "data_financial_stress",
    "data_gex",
    "data_hy_oas",
    "data_move",
    "data_mstr_mnav",
    "data_ndx_concentration",
    "data_nfci",
    "data_onchain_mstr",
    "data_yield_curve",
    "use_arm_then_fire",
    "use_b6_mnav_valuation",
    "use_btc_spot_witness",
    "use_cboe_official_indices",
    "use_cd_trend_dedup",
    "use_close_confirmation",
    "use_decision_stabilizer",
    "use_fred_vintage_pit",
    "use_hm2_buffer",
    "use_indicator_cache",
    "use_market_admission_gate",
    "use_meta_label",
    "use_portfolio_risk_budget",
    "use_route_set_transition_buffer",
    "use_status_hysteresis"
  ],
  "enabled_features": [
    "data_aaii",
    "data_cboe_pcr",
    "data_component_breadth",
    "data_defensive_rotation",
    "data_dollar",
    "data_naaim",
    "data_net_liquidity",
    "data_real_rate",
    "data_skew_vvix",
    "use_full_confidence_spine",
    "use_no_advice_state",
    "use_partial_factor_eval",
    "use_regime_multipliers",
    "use_scored_missing_weight",
    "use_soft_data_max_age",
    "use_suspect_valve_guard"
  ],
  "ibkr_readonly": true,
  "module_caps": {
    "A": 20,
    "B": 25,
    "C": 35,
    "D": 20
  },
  "reentry_tranches": [
    0.3,
    0.3,
    0.4
  ],
  "routing_defcon1": {
    "BOXX": 0.5,
    "TREND": 0.3,
    "extra_legs": {
      "IAU": 0.2
    },
    "trend_symbol": "DBMF"
  },
  "schema_version": "hermes-governance-snapshot-v1",
  "status_thresholds": {
    "DEFENSIVE_EXIT": 70,
    "EXIT": 75,
    "REDUCE": 50,
    "TRIM": 35,
    "WATCH": 20
  }
}
```
<!-- HERMES_GOVERNANCE_SNAPSHOT_END -->

> 由代码事实与治理检查生成于 2026-07-14。若本文与代码、配置或最新报告漂移，以代码和 `src/hermes_escape_top/config/config.json` 为准；`scripts/check_governance_consistency.py` 会阻止关键快照静默漂移。

本文给新 agent 一个快速、可执行的项目地图：系统做什么、数据怎样进来、评分怎样变成策略、哪些 flag 已经部署、WebUI 两个端口各负责什么，以及当前性能基线在哪里。

---

## 1. 系统目标

Hermes 是一个防御型、只读、永不自动下单的逃顶系统，主目标资产是 `MSTR`、`FNGU`、`SOXL`。系统每天读取本地历史价格、软数据、IBKR 只读持仓快照，输出：

| 输出层 | 内容 | 事实源 |
|---|---|---|
| 评分 | A/B/C/D 模块分数、硬阀门、最终状态 | `core/scoring/` |
| 仓位 | target weight、sell fraction、confidence spine、risk contribution | `pipeline.py` + `core/portfolio/` |
| 路由 | DEFCON1/2/3 防守资金去向 | `core/routing/capital_routing.py` |
| 再入场 | 时间锁、分数锁、结构锁、T1/T2/T3 状态 | `core/reentry/` |
| 展示 | 8766 escape dashboard（唯一 UI，已吸收工作台/决策历史/数据信任区）；8765 已退役 | `web/` |

红线：Hermes 只生成建议和确认记录，不提交真实订单。所有 IBKR 使用只读语义；`confirm_execution` 只记录人工确认。

---

## 2. 关键入口和所有权

| 路径 | 角色 |
|---|---|
| `src/hermes_escape_top/pipeline.py` | 生产评分入口 `score_pipeline()`；A 轨单写者文件 |
| `src/hermes_escape_top/config/config.json` | 生产配置 SSOT；A 轨单写者文件 |
| `src/hermes_escape_top/web/` | WebUI/可视化与本批 8766 POST 鉴权 |
| `src/hermes_escape_top/core/data/market.py` | 本批新增指标帧缓存，生产 flag 默认 OFF |
| `src/hermes_escape_top/core/data/risk_signals.py` | 软数据源；FRED observations use PIT-safe `date+1` publish dates，标准 observations API 的 `realtime_start` 不作为逐行历史发布时间 |
| `src/hermes_escape_top/core/data/external_sources/` | 外部软数据单写者；profile/SLO、staging、validation、canonical promotion、ledger 和可靠性证据同属一条链 |
| `src/hermes_escape_top/core/data/market_witness.py` | Alpaca SIP 日线 OHLCV shadow witness；只比对、只写 archive 证据，永不晋升 canonical 或进入评分 |
| `src/hermes_escape_top/core/data/coinbase_witness.py` | Coinbase Exchange BTC-USD UTC 日线独立见证；只核对 Yahoo 候选的完成日收盘，不比较成交量、不直接写 canonical |
| `scripts/backtest_flag_sweep.py` | 单 variant 全窗口回测；每次只跑一个进程 |
| `scripts/flag_gate.py` | 读取 equity 曲线做旧版固定变体 OOS/DSR 诊断；授权已冻结，等待正式 IS→OOS PBO gate |
| `scripts/formal_gate.py` | 读取已提交的实验 manifest，执行逐折 IS 选择→OOS PBO、CPCV、经验偏度/峰度 DSR；结果一次性落盘 |
| `scripts/execution_timing_sensitivity.py` | 只读重定价逐日路由权重：legacy close / next open / next close / next-open+滑点；不重跑评分、不改生产 |
| `docs/FLAG_REGISTRY.md` | flag 四态台账 |

工作纪律：

- 不要随意改 `pipeline.py` 或 `config/config.json`。
- 全窗口回测/gate 互斥，一个进程跑完再跑下一个。
- 回测应设置独立 `HERMES_DATA_DIR`，不要直接读写包内 `data/` 的运行态文件。
- 新功能默认 OFF，必须有 byte-identical 证明或 gate 证据。

---

## 3. 数据路径

相对路径由 `config.resolve_path()` 解析；设置 `HERMES_DATA_DIR` 时，`data/history`、`data/soft_history`、`data/archive` 会重定向到隔离根目录。

| 数据层 | 位置 | 说明 |
|---|---|---|
| 日线历史 | `data/history/*.csv` | 价格、成交量、代理合成行、底层股票流指标 |
| 软数据历史 | `data/soft_history/*.csv` | FRED、AAII、NAAIM、CBOE PCR、COT、mNAV、on-chain lab 等 |
| 运行归档 | `data/archive/` | audit log、state sqlite、manifest、refresh run、mirror/reentry/flow sqlite |
| 生成报告 | `building/reports/` | backtest、gate、baseline、research notes |

当前核心数据事实：

- `market_symbols` 含 `IAU`，金腿执行符号已经从 GLD 换为 IAU。
- `component_proxies` 为 FNGU/SOXL 穿透股票资金流提供底层股票 CMF/MFI/AD slope。
- FRED observations use PIT-safe `date+1` publish dates；这是当前生产路径，有 key 与 CSV fallback 走相同语义。ALFRED output-type-3 精确事件库与真实 `realtime_start` as-of 回放已经实现并保留为研究/取证能力，但 `fred-vintage-pit-v1` 正式 gate 因 CPCV OOS 退化和 MaxDD 恶化而拒绝，`features.use_fred_vintage_pit` 必须保持 false。
- 标准 observations API 的 `realtime_start` 是查询 vintage 元数据，不足以证明每条历史观测的真实首次发布时间，因此不用于逐行 PIT 对齐。

外部数据自动化现状：

| 源 | canonical | 生产入口 | PIT/可见时间 | 运维边界 |
|---|---|---|---|---|
| `dollar` / `real_rate` / `fred_net_liquidity` | production legacy `*.csv`；research-only 独立 `*_vintage.csv` | 默认 FRED API/Graph CSV；Dollar 的 DTWEXBGS 额外由 Federal Reserve Board H.10 同序列见证；研究路径为 ALFRED exact vintage event store | 生产观测日 `+1d`；研究路径为真实 `realtime_start` | Dollar 两条官方路径日期/值不一致或任一路径不可用时冻结旧 canonical；`fred-vintage-pit-v1` 已拒绝，生产 flag 保持 OFF |
| `cboe_equity_pcr` | `soft_history/cboe_equity_pcr.csv` | CBOE daily HTML | 观测日 `+1d` | 解析/比率校验失败时保留上一份 canonical |
| `cboe_vix` / `cboe_vix3m` / `cboe_vix9d` / `cboe_skew` / `cboe_vvix` | `history/_VIX*.csv` / `_SKEW.csv` / `_VVIX.csv` | CBOE official daily history CSV；Yahoo witness-only | 仅已完成美股交易日；未见证尾部不晋升 | 2026-07-14 live 已开启，repo 默认 OFF；`backfill()` 内层禁止 Yahoo 双写，截断/缺日/证据漂移保留旧 canonical |
| `cot_nq` | `soft_history/cot_nq.csv` | CFTC public API | 周二观测、周五公开 | flag OFF 时不影响生产健康/决策覆盖 |
| `occ_equity_pcr` | `soft_history/occ_equity_pcr.csv` | OCC weekly report | 周五 week-ending、周六公开 | 当前 inactive，只做迁移/替代源证据 |
| `btc_funding_basis` | `soft_history/btc_funding_basis.csv` | Deribit，OKX fallback | 交易所 UTC 时间戳归日 | 增量刷新不再把历史 real 行降成 proxy |
| `btc_spot_witness` | `history/BTC_USD.csv` 的准入证据 | Coinbase Exchange public BTC-USD 1D candles；Yahoo 仍是候选 writer | 仅完成的 UTC 日；日期相同且 close 差异 <=1% 才晋升 | live 自 2026-07-14 为 ON（repo 默认 OFF）；缺失/失配冻结旧 canonical，成交量口径不参与判断 |
| `naaim_exposure` | `soft_history/naaim_exposure.csv` | 官方公共 XLSX；可配置订阅 XLSX；official-file import 兜底 | issue `+1d` | ledger 显式记录通道；订阅成功立即标记 ready，公共通道只有在 2026-08-01 后仍有成功证据才解除迁移告警，人工文件只算 fallback |
| `aaii_sentiment` | `soft_history/aaii_sentiment.csv` | AAII 结果页 → AAII 官方 Insights RSS → official-file import | 结果页按 reported `+1d`；RSS 只按自身 artifact `pubDate` 可用，不向前回填 | Imperva 不再是自动化单点；RSS 可能比结果页晚约 2 天，两条官方发布面均失败时才需人工文件 |

- 06:45 全量预检，07:05 只重试当日失败/证据未就绪的源，07:10 daily 优先复用当日完整 ledger，不连续重打限流源。
- 所有外部软数据先写 raw/staging，通过 schema + semantic validation 后才原子晋升；成功 ledger 绑定 canonical SHA-256、最新日期、来源 URL 和 PIT 规则。
- canonical 字节与最新成功 ledger 不一致时显示 `EVIDENCE_DRIFT`，不会把人工改写重新认证为 OK。
- AAII 结果页受阻时自动切换官方 Insights RSS，ledger 记录实际 URL 与 XML 指纹；AAII/NAAIM 下载文件按 SHA-256 去重，已消费或已失败的旧文件不会在每次预检被当成新候选。
- 可靠性按 `Asia/Shanghai` 自然日去重；同日失败后重试成功只算一个成功日，避免重试次数虚增成功率。transport/parse/validation/promotion 中 `promotion=UNCHANGED` 是成功检查而不是失败；任何 30/90 日比率在样本少于 5 时显示 `INSUFFICIENT_EVIDENCE`，不把 0%/100% 冒充稳定统计。
- Alpaca SIP 见证只对比 Yahoo/local canonical 的最近 OHLCV，写 `market_witness_*.json`；`NO_WITNESS`/`FETCH_ERROR` 不改评分、不改 `input_hash`。
- Coinbase BTC 见证属于 canonical admission 而非评分因子：0.5%-1.0% close 差异标黄但可晋升，>1.0% 或缺日冻结旧值；当前 UTC 日延后且不制造健康红灯。

---

## 4. 数据守卫与质量解释

| 层 | 守卫 | 代码事实 |
|---|---|---|
| L1 刷新完整性 | refresh 前后做 history integrity scan，发现跨线/漂移则拒绝评分 | `web/refresh.py::_history_integrity_scan` |
| L2 manifest SSOT | `data_manifest_latest.json` 与 history CSV 校验；漂移可重冻结，GET health 可显示 | `core/data/manifest.py`、`web/refresh.py::_refresh_manifest` |
| L3 运行降级 | health 汇总 cache、交易日陈旧、manifest、data_quality、软数据 stale、IBKR 状态 | `web/health.py::compute_health` |
| L4 外部源证据 | ledger 绑定 canonical hash/PIT/来源，30/90 日可靠性按日去重 | `core/data/external_sources/` |
| L5 独立行情见证 | 美股/ETF 用 Alpaca SIP；BTC 用 Coinbase Exchange 完成 UTC 日 close；均无自动 failover | `core/data/market_witness.py`、`core/data/coinbase_witness.py` |

软数据 SLO 由 `features.use_soft_data_max_age` 控制。开启后，超龄软数据会被降为 missing，进入 missing-weight/blind-spot 路径，而不是继续当作新鲜信号评分。

8766 将数据质量拆成四个不混合的维度：行情完整度、来源真实性、时效性、评分置信权重覆盖。最后一项直接从当次 `scores[*].confidence_missing_weight` 统计：每个标的先归一化为 100 分置信权重面，再在标的间等权汇总；它不是因子数量覆盖率，也不用另一份手工因子清单。IBKR 持仓与 SIP 资金流是辅助证据，不计入该指标。

---

## 5. 评分骨架

评分对象是 `MSTR`、`FNGU`、`SOXL`。每个标的经过：

1. `MarketData.snapshot()` 读取历史并派生指标。
2. `collect_soft_data()` 读取 PIT 软数据。
3. `score_symbol()` 汇总 A/B/C/D 模块。
4. `evaluate_hard_valves()` 处理硬阀门和 pending/buffered 状态。
5. `verdict` 将分数转成 `HOLD/WATCH/TRIM/REDUCE/DEFENSIVE_EXIT/EXIT`。
6. sizing、routing、reentry、action intents 生成用户可执行建议。

模块 cap：

| 模块 | cap | 当前代码定义 / 可达容量 | 含义 |
|---|---:|---|---|
| A | 20 | 50 / 50，超过 cap 的 30 分会被截断 | 宏观、流动性、市场广度、情绪 |
| B | 25 | 定义 26；MSTR 可达 21，FNGU/SOXL 可达 26 后截为 25 | 标的过热、估值、期权压力；B5 是 0 分 placeholder，MSTR B6 默认 OFF |
| C | 35 | 36 / 36，超过 cap 的 1 分会被截断 | 趋势破坏、急跌、支撑破坏、分布压力 |
| D | 20 | 20 / 20 | 标的自身、雷达、BTC/底层股票穿透风险 |

机器生成的逐标的、逐因子 SSOT：`building/reports/factor_capacity/FACTOR_CAPACITY_INVENTORY.md`。治理检查会在因子定义、flag 或 cap 改变但清单未再生时失败；不要再手算 B 的“16/21/25/26”。

`features.use_regime_multipliers=true` 时，`scorer.py` 会按 regime 调整模块权重。该 flag 默认 ON 是为了匹配 2026-06-10 前的无条件行为。

---

## 6. C 模块 C1-C12 当前表

代码事实源：`core/scoring/module_c.py`。注意：当前代码只实现 C6、C7、C8、C9、C10、C11、C12；C1-C5 没有独立 FactorDefinition，相关风险主要由硬阀门、A 模块和 D 模块覆盖。

| 编号 | factor_id | max | 当前状态 | 触发语义 |
|---|---|---:|---|---|
| C1 | n/a | 0 | 未实现 | 旧文档槽位，不得假装存在 |
| C2 | n/a | 0 | 未实现 | 旧文档槽位，不得假装存在 |
| C3 | n/a | 0 | 未实现 | 旧文档槽位，不得假装存在 |
| C4 | n/a | 0 | 未实现 | 旧文档槽位，不得假装存在 |
| C5 | n/a | 0 | 未实现 | 旧文档槽位，不得假装存在 |
| C6 | `C6_SHARP_DROP` | 5 | live | MSTR 2 日跌幅 <= -12% 得 5；杠杆 ETF <= -22% 得 5，<= -15% 得 3，<= -8% 得 1 |
| C7 | `C7_AVWAP_PLATFORM_SUPPORT` | 4 | live | 跌破 20D support 或 20D peak-anchored AVWAP |
| C8 | `C8_DISTRIBUTION_PRESSURE` | 4 | live | 25 日分布日 >=6 得 4，>=5 得 3，>=4 得 2 |
| C9 | `C9_CHANDELIER_BREAK` | 5 | live | close < 22D Chandelier 4.5x ATR |
| C10 | `C10_MACRO_TREND_STRUCTURE` | 10 | live | close<EMA50、Minervini 结构破坏、150/200D 支撑破坏叠加 |
| C11 | `C11_MA220_REBUILD_GAP` | 4 | live | close <= MA220 得 4；距 MA220 小于 3% 得 1 |
| C12 | `C12_VOL_EXPANSION` | 4 | live | 20D realized vol >=120% 得 4，>=85% 得 3，>=60% 得 1 |

---

## 7. 硬阀门

事实源：`core/scoring/hard_valves.py`。

| 标的 | 阀门族 | 例子 |
|---|---|---|
| MSTR | H-M1..H-M6 | MSTR close<=MA200、-15% 且低于 EMA10、BTC below MA50 + MSTR 两日低于 EMA20、Chandelier stop 等 |
| FNGU | H-F1..H-F7 | QQQ/FNGS/NYFANG MA200 破位、单日/两日急跌、三日低于 EMA50、VIX 曲线压力 |
| SOXL | H-S1..H-S8 | QQQ/SOXX/SMH/SOX MA200 破位、急跌、SOXX/SMH 三日低于 EMA50、峰值回撤与 Chandelier |

特殊状态：

- `use_suspect_valve_guard=true` 时，疑似坏 bar 上的阀门进入 `pending_ids`，不直接强平。
- `use_hm2_buffer=false` 当前未部署；若开启，单独 H-M2 可从硬 EXIT 降为 buffer 状态。
- `hard_valve_state.candidates` 已输出 current/threshold/距离，用于 8766 全景阀门面板。

---

## 8. DEFCON 路由

事实源：`core/routing/capital_routing.py`，以下是代码 OR 链，不能用旧文档推断。

先决条件：只有 `score.status in {REDUCE, DEFENSIVE_EXIT, EXIT}` 或存在硬阀门时才 route；否则 `DEFCON=NONE`。

### DEFCON1: 宏观/流动性核风险

满足任一条件即进入 DEFCON1：

- A 模块总分 `A >= 12`
- `A1 + A5 + A7 + A8 >= 8`
- 任一核心 A 因子单独打满：`A1>=4` 或 `A5>=4` 或 `A7>=4` 或 `A8>=4`

当前资金腿：

| leg | weight | 来源 |
|---|---:|---|
| BOXX | 50% | `routing.defcon1.BOXX` |
| DBMF | 30% | `routing.defcon1.TREND` + `trend_symbol=DBMF` |
| IAU | 20% | `routing.defcon1.extra_legs.IAU` |

备注：gate 证据来自 GLD combo；2026-06-12 执行符号从 GLD 换成 IAU，配置说明认为两者同 underlying、相关性约 0.999，属于展示/对账符号替换，不重新 gate。若需要回滚，IAU -> GLD。

### DEFCON2: 内部破坏/硬阀门

DEFCON1 未命中后，满足任一条件进入 DEFCON2：

- D 模块分数 `D >= 10`
- 存在硬阀门
- `C8 >= 3`
- `C6 >= 3`

默认去 `BRK.B`。若 BRK.B 防守腿 degraded，则回退 `BOXX`。degraded 条件：

- BRK.B close <= MA200
- 或 BRK.B/SPY 60 日相关性 >= 0.85

### DEFCON3: 常规减仓

DEFCON1/2 未命中时，按标的映射：

| risk symbol | destination |
|---|---|
| SOXL | SOXX |
| FNGU | QQQ |
| MSTR | BTC-USD |

MSTR -> BTC-USD 的实际 live 等价说明是 IBIT；回测用 BTC-USD 保留 crypto thesis 并去掉 MSTR 单名/mNAV premium 风险。

---

## 9. 当前生产 flag 部署态

生产 `config.json` 的核心部署态：

| flag | 当前值 | 状态 |
|---|---:|---|
| `use_scored_missing_weight` | true | live，F5/F6 missing 字段按已实现分数比例调整 |
| `use_suspect_valve_guard` | true | live，疑似坏 bar 不直接触发硬阀门 |
| `use_partial_factor_eval` | true | live，partial_ok 因子可在部分字段存在时评分 |
| `use_soft_data_max_age` | true | live，软数据超龄降 missing |
| `use_full_confidence_spine` | true | live，fragility/disagreement 接入 sizing |
| `use_no_advice_state` | true | live（2026-06-14）；critical 字段缺失→NO_ADVICE/sell0，不再伪装 100 分 EXIT。历史 close 零缺失=no-op 安全网 |
| `use_regime_multipliers` | true | live，保持历史无条件 regime multiplier 行为 |
| `use_indicator_cache` | false | 生产默认 OFF；本批 backtest harness 打开，byte-identical 已证明 |
| `use_market_admission_gate` | false | repo 默认 OFF；live runtime 自 2026-07-14 为 ON，美股/ETF行情须经 Yahoo + Alpaca SIP 双源一致才晋升 |
| `use_btc_spot_witness` | false | repo 默认 OFF；live runtime 自 2026-07-14 为 ON，BTC-USD 的 Yahoo 候选须经 Coinbase 完成 UTC 日 close 见证 |
| `use_fred_vintage_pit` | false | Rejected；OFF 四日期/六落盘产物严格等价；正式 gate 因 CPCV OOS Δ -0.077120 与 MaxDD 恶化 1.73pp 拒绝，禁止翻闸或原参数重跑 |
| `data_onchain_mstr` | false | rejected/parked |
| `data_mstr_mnav` | false | parked |
| `use_b6_mnav_valuation` | false | rejected/parked |
| `data_cot_nq` | false | candidate 失败后保持 OFF |

六个主部署 flag 是 `use_scored_missing_weight`、`use_suspect_valve_guard`、`use_partial_factor_eval`、`use_soft_data_max_age`、`use_full_confidence_spine`、`use_no_advice_state`。`use_regime_multipliers` 是兼容性 live flag。

---

## 10. WebUI（8766 单端口）

8765 工作台已于 2026-06-15 退役（launchd `com.hermes.workbench` unload），其决策视图已并入 8766。

| 端口 | 入口 | 用途 |
|---|---|---|
| 8766 | `web/server.py` + `web/render.py` | 唯一 UI：策略操作台、决策历史条、Evidence Strip、硬阀门雷达、持仓对账、数据信任区、refresh/confirm 写端点；M4 与 IBKR demo 写入口永久返回 410 |
| ~~8765~~ | ~~`web/workbench.py`~~ | 已退役；功能并入 8766 |

运维：发布前 `scripts/predeploy_smoke.py`（FRED publish_date/源可用/决策行无 NA/manifest/软源回归）拦假数据；审计日志日运行轮转（`rotate_audit_log`，>100MB 归档 gz 后压缩主文件）。

8766 POST 鉴权的唯一政策（威胁模型：服务仅绑定 loopback，不经反向代理或对外暴露）：

- 所有写端点的 `Host` 必须是 localhost/127.0.0.1/::1；`Origin` 若存在，也必须是本机 loopback。
- 危险端点 `/api/m4_golive`、`/api/confirm_execution` 还必须提供 `HERMES_CONFIRM_TOKEN`；无 token 或错 token 返回 HTTP 403。
- 低风险的数据刷新/重算端点 `m4_shadow`、`m4_backfill`、`refresh_manifest`、`refresh_soft_data`、`ibkr_demo_snapshot`、`refresh_score`、`refresh_positions`、`ibkr_live_check` 仅要求 loopback，不要求 token；它们不下单、不改变生产路由。
- 锁被其他 daily/刷新持有时，写端点返回 HTTP 409，不启动第二个 writer。
- 若 8766 未来绑定非 loopback、经反向代理或暴露到其他主机，在暴露前必须将全部 mutating POST 升级为 token 鉴权并补齐 CSRF/代理信任边界，不得直接沿用当前政策。

---

## 11. 当前性能基线

> **CURRENT EXECUTION EVIDENCE：**baseline 绑定 gate-code commit `02a1953`、已提交的有效 live-config 快照、当前 history manifest 与 soft-history 指纹；可作为预注册 formal gate 的 next-open 对照，但不授权任何配置翻闸。完整来源以确定性 gzip 归档，治理检查会核对解压后 SHA-256。

| 当前场景 | CAGR | MaxDD | Sharpe | 定位 |
|---|---:|---:|---:|---|
| **next_open** | **15.58%** | **-20.83%** | **1.064** | 当前正式 baseline headline |
| legacy_close | 16.61% | -18.83% | 1.121 | 历史/理论上界 shadow |
| next_close | 16.71% | -16.05% | 1.128 | 延迟一交易日敏感性 |
| next_open + 25bps | 7.77% | -26.36% | 0.585 | 执行压力场景 |

- 窗口：2018-01-01→2026-07-14，有效 2,143 个交易日。
- 全量开盘覆盖：89.81% 观测、2,182 行显式建模、BTC 首日未使用缺口 1；执行所需 10,033 行缺失 0。
- `building/reports/flag_sweep/baseline.json` 已标记 `CURRENT_EXECUTION_EVIDENCE`；code/config/manifest/soft-history 任一变化都会让它失效并阻断新 gate。
- 完整证据与路径见 `docs/BASELINE_CURRENT.md`。

### 历史参照（STALE）

以下旧 flag-sweep/gate 产物不匹配当前代码、数据或执行口径，且旧 gate 没有逐折 IS 选择。数字只作历史诊断，不得据此翻新 flag 或 routing。

历史 flag-sweep baseline 使用 `features.use_indicator_cache=true` 的回测配置，生产 config 仍 OFF。FRED 单系列 PIT 修正已进入代码。

| 历史报告 | CAGR | MaxDD | Sharpe | OOS 后半区比例（非正式 PBO） | DSR 诊断 |
|---|---:|---:|---:|---:|---:|
| pre-v4 flag-sweep baseline (historical record) | 16.97% | -13.58% | 1.215 | n/a | n/a |
| `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline | 16.97% | -13.58% | 1.215 | 0.31 | 1.189 |
| `building/reports/flag_sweep/GATE_REPORT.md` baseline | 16.97% | -13.58% | 1.215 | 0.31 | 1.179 |

表中 16.97%、旧 17.38% / -13.77% / Sharpe 1.223 和更旧 15.84% capeff baseline 均只保留历史语境；当前基线已经由上方 cache v4 / next-open 记录取代。

成交时点方法层已于 2026-07-11 完成：`legacy_close` 保留为历史/理论上界，当前 baseline 以 `next_open` 为头条，另固定输出 `next_close` 和 next-open+25bps stress。正式实验产物协议已升为 cache v4，`variant_equity.json` 必须声明并承载 `equity_timing=next_open`；旧 v3/legacy 曲线不能进入 formal gate。旧 `Backtest_FULL_2018_2026.json` 的只读方法验收实现 legacy 指标/换手完全一致，但因源产物无当前 provenance，报告被锁为 `METHODOLOGY_ONLY`，不得当作当前基线。报告路径：`building/reports/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`；完整方法说明：`docs/history/2026-07-11_execution_timing_sensitivity.md`。

指标帧缓存 byte-identical 证据：

- 报告：`building/reports/indicator_cache_byte_identical_2026_06_13.json`
- 日期：2022-01-03、2024-04-19、2026-05-29、2026-06-11
- 4/4 `input_hash` 相同，状态相同
- 小样本 runtime：OFF 8.763s，ON 5.764s，约 1.52x

---

## 12. 测试与验证

当前回归结果：2026-07-13 数据质量候选分支全套 `845 passed / 0 failed`。此数绑定候选代码节点 `692f175`；后续任何行为改动必须重跑，不得把旧测试数当作健康证明。

标准命令：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

本批新增/触达的 focused 覆盖：

| 文件 | 覆盖 |
|---|---|
| `test_market_indicator_cache.py` | flag OFF 不缓存；flag ON 跨 as_of 复用指标帧 |
| `test_phase10_adapters.py` | FRED API/CSV 均采用 `date+1` publish_date；source build_frame 不覆盖 PIT 日期 |
| `test_phase15_integration.py` | 危险写端点 token 通过/拒绝；低风险 refresh 仅 loopback；busy 409 不调用第二个 writer |
| `test_validation_harness.py` | 单配置 PBO 不再伪造 1.0；多配置向量仍可计算 |
| `test_flag_sweep_cache.py` | gate/backtest 配置打开 `use_indicator_cache` |
| `test_external_source_profiles.py` | config SLO SSOT、active/parked 源和迁移截止日 |
| `test_external_source_runner.py` | 失败不晋升、canonical/ledger 漂移、可靠性按日去重 |
| `test_external_source_market_soft.py` | CBOE/CFTC/OCC/BTC adapter 解析、语义校验和 PIT |
| `test_external_source_fred.py` | FRED raw query-vintage 证据、归一化 `date+1`、抓取时刻不改 source input hash |
| `test_decision_input_coverage.py` / `test_run_receipt_writer.py` | 评分置信权重覆盖与四维质量证据 |
| `test_market_witness.py` | Alpaca OHLCV shadow 对比、不晋升和失败保全 |

---

## 13. 已知 parked / rejected

| 项 | 状态 | 原因 |
|---|---|---|
| `data_onchain_mstr` | OFF/rejected | CoinMetrics inflow/netflow 两个 survivor gate 未严格改善 baseline |
| `data_mstr_mnav` | OFF/parked | mNAV source 可诊断，但 B6 消费 gate 失败 |
| `use_b6_mnav_valuation` | OFF/rejected | full CAGR 改善但 OOS objective 和 MaxDD 未过 gate |
| `use_decision_stabilizer` / `use_status_hysteresis` / `use_close_confirmation` | OFF/rejected | OOS 不优，部分增加 MaxDD |
| `use_hm2_buffer` | OFF/rejected/parked | 单 H-M2 缓冲思路未部署 |
| `data_cot_nq` | OFF/rejected | 历史诊断中 OOS<=base 且 OOS 后半区比例>=0.5；旧结果不属于正式 PBO |

---

## 14. Agent 操作建议

1. 先读 `config/config.json` 和目标代码，不要相信旧报告的自然语言。
2. 涉及评分、路由、仓位，必须说明 flag 状态和是否进生产路径。
3. 涉及 backtest/gate，使用独立 `HERMES_DATA_DIR`，一次一个进程。
4. 涉及 WebUI POST，遵守第 10 节的分级鉴权：全部端点限 loopback，只有 go-live 和 execution confirmation 额外要求 token。
5. 任何“看似 no-op”的缓存或 PIT 修正，都要用 `input_hash` 或 gate 报告证明。
