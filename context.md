# Hermes 逃顶 + 镜像系统 - Agent 上下文

> 维护于 2026-06-19（手工，依据代码；非脚本自动生成）。若本文与代码、配置或最新报告漂移，以代码和 `src/hermes_escape_top/config/config.json` 为准。

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
| `src/hermes_escape_top/core/data/risk_signals.py` | 软数据源；FRED 单系列已改用 API `realtime_start` 作为 PIT `publish_date` |
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
- FRED 单系列 backfill 在有 key 时使用 FRED API `realtime_start`，避免周频数据被误当成次日可见。
- `fetch_fred_graph_csv` fallback 不含 `realtime_start`，只能保留旧 `date+1` 语义。

---

## 4. 三层数据守卫

| 层 | 守卫 | 代码事实 |
|---|---|---|
| L1 刷新完整性 | refresh 前后做 history integrity scan，发现跨线/漂移则拒绝评分 | `web/refresh.py::_history_integrity_scan` |
| L2 manifest SSOT | `data_manifest_latest.json` 与 history CSV 校验；漂移可重冻结，GET health 可显示 | `core/data/manifest.py`、`web/refresh.py::_refresh_manifest` |
| L3 运行降级 | health 汇总 cache、交易日陈旧、manifest、data_quality、软数据 stale、IBKR 状态 | `web/health.py::compute_health` |

软数据 SLO 由 `features.use_soft_data_max_age` 控制。开启后，超龄软数据会被降为 missing，进入 missing-weight/blind-spot 路径，而不是继续当作新鲜信号评分。

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

| 模块 | cap | 含义 |
|---|---:|---|
| A | 16 | 宏观、流动性、市场广度、情绪 |
| B | 25 名义 / 21 当前可达 | 标的过热、估值、期权压力；B5 stub，MSTR B6 默认 OFF |
| C | 20 | 趋势破坏、急跌、支撑破坏、分布压力 |
| D | 20 | 标的自身、雷达、BTC/底层股票穿透风险 |

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
| 8766 | `web/server.py` + `web/render.py` | 唯一 UI：策略操作台、决策历史条、Evidence Strip、硬阀门雷达（新触发标"待明日确认"）、持仓对账（陈旧快照弱化）、数据信任区、refresh/golive/confirm 写端点 |
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

> **STALE RESEARCH EVIDENCE：**以下 flag-sweep 产物不匹配当前代码/数据 fingerprint，且旧 gate 没有逐折 IS 选择。数字只作历史诊断，不得据此翻新 flag 或 routing。

历史 flag-sweep baseline 使用 `features.use_indicator_cache=true` 的回测配置，生产 config 仍 OFF。FRED 单系列 PIT 修正已进入代码。

| 历史报告 | CAGR | MaxDD | Sharpe | OOS 后半区比例（非正式 PBO） | DSR 诊断 |
|---|---:|---:|---:|---:|---:|
| `building/reports/flag_sweep/baseline.json` | 16.97% | -13.58% | 1.215 | n/a | n/a |
| `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` baseline | 16.97% | -13.58% | 1.215 | 0.31 | 1.189 |
| `building/reports/flag_sweep/GATE_REPORT.md` baseline | 16.97% | -13.58% | 1.215 | 0.31 | 1.179 |

表中 16.97%、旧 17.38% / -13.77% / Sharpe 1.223 和更旧 15.84% capeff baseline 均只保留历史语境；当前 baseline 要等正式 gate 与成交时点模型完成后重建。

成交时点方法层已于 2026-07-11 完成：`legacy_close` 保留为历史/理论上界，未来 baseline 以 `next_open` 为头条，另固定输出 `next_close` 和 next-open+25bps stress。旧 `Backtest_FULL_2018_2026.json` 的只读方法验收实现 legacy 指标/换手完全一致，但因源产物无当前 provenance，报告被锁为 `METHODOLOGY_ONLY`，不得当作当前基线。报告路径：`building/reports/execution_timing/EXECUTION_TIMING_SENSITIVITY.md`；完整方法说明：`docs/history/2026-07-11_execution_timing_sensitivity.md`。

指标帧缓存 byte-identical 证据：

- 报告：`building/reports/indicator_cache_byte_identical_2026_06_13.json`
- 日期：2022-01-03、2024-04-19、2026-05-29、2026-06-11
- 4/4 `input_hash` 相同，状态相同
- 小样本 runtime：OFF 8.763s，ON 5.764s，约 1.52x

---

## 12. 测试与验证

当前回归结果：741 passed（2026-07-11）。

标准命令：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q
```

本批新增/触达的 focused 覆盖：

| 文件 | 覆盖 |
|---|---|
| `test_market_indicator_cache.py` | flag OFF 不缓存；flag ON 跨 as_of 复用指标帧 |
| `test_phase10_adapters.py` | FRED API `realtime_start` -> `publish_date`；source build_frame 不覆盖 PIT 日期 |
| `test_phase15_integration.py` | 危险写端点 token 通过/拒绝；低风险 refresh 仅 loopback；busy 409 不调用第二个 writer |
| `test_validation_harness.py` | 单配置 PBO 不再伪造 1.0；多配置向量仍可计算 |
| `test_flag_sweep_cache.py` | gate/backtest 配置打开 `use_indicator_cache` |

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
