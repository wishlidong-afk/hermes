# BUILD TICKETS — 基线续建 NEXT-0 ~ NEXT-6（函数级工单）

> 把系统从"能跑(M0)"推进到"可信、可上线(M3/M4)"的基线路径。
> 复盘修正后的关键路径：先补数据地基与可历史化软数据（降 30%+ 盲区），再做完整回测与参数校准。
> 通用铁律见每单；通用放行关 A1–A8 见末尾。

## 关键路径

```
NEXT-0 数据地基（价格史2018+ / 数据版本化 / 时点对齐）
NEXT-1 可历史化软数据接入（FRED/CBOE/PCR/AAII/NAAIM/BTC微观）→ missing<30
NEXT-2 回测引擎补全（2018→2026 + 成本 + walk-forward + 硬阀门历史触发）
NEXT-3 参数扫描与正式校准（稳健选参 + 每模块达标门）
NEXT-4 纯向前软数据（GEX/CNN/新闻/mNAV）+ dated 归档
NEXT-5 元模型回放 backfill + 训练（解锁门）
NEXT-6 IBKR 只读对账（绝不下单）
```

---

## NEXT-0 数据地基

### N0-T01 价格历史回填到 2018
- `scripts/backfill_history.py::backfill(symbols, start="2018-01-01", end=None, store_dir) -> dict`
- 逻辑：yfinance 拉日线；幂等续拉；列 `date,open,high,low,close,adj_close,volume`；杠杆 ETN 用真实收盘不加损耗；返回起止+缺口。
- 覆盖：MSTR/FNGU/SOXL/QQQ/SPY/^VIX/^VIX3M/^VIX9D/^SKEW/^VVIX/SOXX/SMH/^SOX/FNGS/^NYFANG/BTC-USD + FNGU 9成分 + SOXL 10成分 + 路由腿 BRK-B/BOXX/DBMF/BIL/SHV。
- 验收：`reports/N0_history_coverage.md`（每序列 inception/起止/缺口）。

### N0-T02 路由腿历史代理
- `core/routing/leg_proxy.py::leg_price_series(leg, range)`；`PROXY_MAP`(BOXX 2022 前→BIL/SHV；DBMF 2019 前→trend_synth)。
- 验收：拼接点净值连续；代理段标 is_proxy。

### N0-T03 时点对齐（防前视核心）
- `core/data/pit.py::asof_pick(records, as_of, publish_lag_days=0)`：返回发布日≤as_of 最近一条。
- 验收：周频/8h 频对齐单测；未来发布值 t 时刻取不到。

### N0-T04 数据快照版本化
- `core/data/manifest.py::freeze_manifest(store_dir)`、`verify_manifest(...)`：每文件 sha256+行数+起止+冻结时间。
- 验收：改一行→hash 变→verify 失败；所有回测报告头带 `data_manifest_id`。

---

## NEXT-1 可历史化软数据接入

> 全部继承 `DataSource`，经 N0-T03 对齐，支持 `backfill()`(联网拉历史) 与 `fetch(as_of)`(离线只读)。

| 工单 | 文件::类 | 字段 | 源 | 历史 | 扣分 |
|---|---|---|---|---|---|
| N1-T01 | `macro.py::FredNetLiquidity` | net_liq=WALCL−WTREGEN−RRPONTSYD 的10日变化分位 | FRED API | 多年 | 0 |
| N1-T02 | `macro.py::CboeIndices` | vix_term=VIX/VIX3M, skew_index, vvix, vvix_pctl | ^VIX3M/^SKEW/^VVIX | 多年 | 0 |
| N1-T03 | `flow_pcr.py::PutCallSource` | equity_pcr/index_pcr/pcr_pctl | CBOE CSV | 多年 | 1 |
| N1-T04 | `sentiment.py::AaiiSource` | aaii_bull/bear/spread | AAII 周CSV | 多年 | 1.5 |
| N1-T05 | `sentiment.py::NaaimSource` | naaim_exposure/pctl | NAAIM 周CSV | 多年 | 1.5 |
| N1-T06 | `breadth.py::ComponentBreadth` | pct_above_50/200dma | 本地成分自算 | 是 | 2 |
| N1-T07 | `crypto.py::CryptoFunding` | btc_funding_8h_avg/pctl | 交易所API | 是 | 2 |
| N1-T08 | `crypto.py::CryptoBasis` | btc_basis_annual/pctl | 期货vs现货 | 是 | 2 |
| N1-T09 | `crypto.py::CryptoDvol` | btc_dvol/pctl | Deribit | 是 | 1 |

- 对齐铁律：周频(AAII 周四/NAAIM 周三/WALCL 周四)按发布日；8h(funding)聚合到当日已结算。
- 接线：A5(净流动性)、A2(AAII/NAAIM/PCR)、A3(宽度)、A7(VIX 期限/VVIX)、B4(SKEW/VVIX/PCR)、D-M(BTC 微观)。
- **N1-T10 盲区再基线** `scripts/rebaseline_missing.py`：`2026-05-29` 回放出接入前后 missing 对照。
- **强制验收**：三标的 `missing_weight < 30`；逐字段降权贡献表；可回溯源 2018→2026 覆盖率报告；对齐前视测试。

---

## NEXT-2 回测引擎补全

| 工单 | 文件::函数 | 要点 |
|---|---|---|
| N2-T01 | `backtest/snapshot.py::build_snapshot(as_of, store, cfg)` | 离线≤as_of；warmup 不足→None |
| N2-T02 | `backtest/costs.py::apply_cost(notional, atr_pct, cfg)` | 往返 bps+滑点；ETN 用真实价不加损耗 |
| N2-T03 | `backtest/simulator.py::simulate(decisions, panel, cfg, enable)` | 调仓/成本/mark；路由腿真实收益；R3 clamp 先生效 |
| N2-T04 | `backtest/metrics.py::compute_metrics(equity, bench, trades)` | CAGR/MaxDD/Calmar/Sortino/Sharpe/DD_reduction/CAGR_drag/Insurance_ratio/Turnover |
| N2-T05 | `backtest/labeling.py::eval_labels(signals, price, H, dd)` | 信号后H日最大回撤≥阈→1；假阳性代价 |
| N2-T06 | `backtest/validation.py::walk_forward_splits(...)` | IS 2y/OOS 6m/step 6m；purged+embargo |
| N2-T07 | `backtest/validation.py::deflated_sharpe(returns, n_trials, skew, kurt)` | 多重检验折扣 |
| N2-T08 | `backtest/run_full.py::run_full_backtest(start, end, cfg, enable)` | 先 freeze manifest |
| N2-T09 | `tests/trigger/test_hard_valve_history.py` | 历史已知暴跌全触发、干净上行0误触发 |

- 前置：N0-T01 把核心标的+路由腿回填到 2018-01。
- 指标公式：`Calmar=CAGR/|MaxDD|`；`Sortino=mean(r)·252/(下行std·√252)`；`Insurance_ratio=DD_reduction/max(CAGR_drag,ε)`。
- 防过拟合：walk-forward OOS + purged + DSR。
- 验收：`reports/Backtest_FULL.md`（每标的+组合，曲线/指标/信号质量/IS-OOS/DSR + data_manifest_id）。

---

## NEXT-3 参数扫描与正式校准

| 工单 | 文件::函数 | 要点 |
|---|---|---|
| N3-T01 | `param_sweep.py::sweep(grid, base_cfg, splits)` | 每组参数×每 OOS fold 跑 run_full；网格点数=DSR trials |
| N3-T02/03 | `calibrate.py::objective(...)`、`pick_robust(...)` | `obj=w1·Calmar+w2·Insurance−w3·Turnover`；选稳健高原非峰值 |
| N3-T04 | `calibrate.py` 写 `config/artifacts/calibration_vX.json` | swept_at/range/walk_forward/chosen/oos_metrics/DSR/confidence_notes；config 引用 artifact_ref |
| N3-T05 | `reports/Calibration_vX.md` | 每模块达标门通过/不通过+证据 |

- 扫描矩阵：vol_budget_annual{0.20–0.55}/corr_window{40,60,90}/extreme_corr_penalty{0.6,0.7,0.8}/corr_regime.extreme{88,92,95}/vol_target.floor{0.20,0.25,0.30}/baseline_window{126,252}/hysteresis.exit。
- 达标门：组合(DD_reduction≥15%相对 & Insurance_ratio≥2.0 & Calmar优于B&H)；vol目标(Calmar↑≥10% & Turnover↑≤25% & R3 100%)；评分链(Precision≥0.55/Recall≥0.5/Brier优于基准)；硬阀门(全触发/0误触发)。
- 诚实声明：~6 年历史、折数少；选稳健宽边际，不当"最优"；标低置信。

---

## NEXT-4 纯向前软数据（仅契约+缓存+fixture+dated 归档）

| 字段 | 文件::类 | 历史 | 处理 |
|---|---|---|---|
| GEX | `options.py::GexProxy` | 无深历史 | BS gamma×OI 代理，扣3，输出 gamma_regime |
| IV Rank/Call Wall | `options.py::IvMetrics` | 向前 | 代理 |
| CNN FGI | `sentiment.py::CnnFgi` | 难回溯 | 向前归档 |
| 新闻/社交 z | `news.py::NewsZScore` | 向前 | 代理扣分 |
| MSTR mNAV | `valuation.py::MstrMnav` | 部分可估 | 持仓×BTC价/市值 + 向前归档 |

- 验收：fixture 解析 + 网络失败回退 + offline 0 外呼；BS gamma 对照解析值；无外网标 BLOCKED-PENDING-ENV。

---

## NEXT-5 元模型（解锁门满足才训）

- 解锁门：完成20日标签信号≥300(含回放backfill)、正样本≥40、覆盖体制≥2。
- N5-T01 `backtest/replay_backfill.py`：回放生成带标签信号事件(价格+N1可回溯软数据，缺的带 missing-flag)。
- N5-T02 `meta/features.py`：特征矩阵+missing-flag。
- N5-T03 `meta/train.py`：逻辑回归/GBM + L2 + purged CV → `meta_model_vX.pkl`。
- N5-T04 `scoring/meta_label.py::predict_action_prob`：硬阀门绕过；p_act 作卖出乘子；`use_meta_label` 默认关。
- N5-T05 `reports/calibration_report.md`：普通vs purged 差距、DSR、混淆矩阵/PR/保险成本 + 解锁门检查。
- 验收：仅 purged CV 上报；未达门停在"管线就绪/LOCKED"。

---

## NEXT-6 IBKR 只读对账

- N6-T01 `ibkr/positions.py::read_positions`：股数/市值/成本/未实现/NetLiq；断连读快照标同步时间。
- N6-T02 `ibkr/reconcile.py::reconcile`：实际 vs 理想仓位/股数差异报告。
- N6-T03 `web/render.py`：只读 drilldown。
- 铁律：绝不下单。验收：对账单测 + 断连回退 + UI 不改决策。

---

## 通用放行关 A1–A8（每个 NEXT 都要过）

| 关 | 判据 |
|---|---|
| A1 | 确定性：同输入两次逐位一致；seed 固定；网络数据冻进版本化 CSV |
| A2 | 无前视：时序"未来突变不改过去"断言；回测只用≤as_of；低频按发布日 |
| A3 | 缺数据安全：缺失走 missing_weight/盲区，不补0、不默认安全；missing>30 升级 |
| A4 | 离线纯净：offline_replay_mode 下外呼==0(mock 断言) |
| A5 | 单测：`python3 -m unittest discover` 全绿；新模块行覆盖≥85% |
| A6 | 数据出处：每字段 source/as_of/is_proxy/latency_days/quality_penalty |
| A7 | 报告：产出 `NEXTx_REPORT.md`；更新 `STATUS.md` |
| A8 | 不上线：任何 `features.*`/`use_*` 翻 true 由人决定，Codex 只到达标为止 |

---

## 成熟度对应

| NEXT | 目标成熟度 |
|---|---|
| NEXT-0/1 | M1 看得清(missing<30) |
| NEXT-2 | M2 验得过 |
| NEXT-3 | M3 校得准 |
| NEXT-5 | M5 会学习(条件满足) |
| NEXT-4/6 | 增强 |

> 基线达 M3/M4 后，进阶增强见 `ENHANCEMENTS.md` 与 `INTEGRATION_ARCHITECTURE.md`。
