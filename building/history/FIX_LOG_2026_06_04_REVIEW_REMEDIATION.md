# Fix Log — 2026-06-04 review remediation

## 背景

本轮逐行 review 后，针对逃顶与镜像系统的实盘可用性补了几类缺口：

- IBKR 实际持仓和策略理想持仓的 route leg 对账口径不一致。
- WebUI 的 GET 页面/API 会隐式跑全量评分，刷新语义不清楚。
- 数据质量评分把同一来源的延迟/代理字段重复扣分，导致置信度被过度压低。
- B6 估值过热缺数据时被当成安全 0 分。
- Full backtest 没有走生产 sizing optimizer。
- IBKR Gateway 未开启时，测试和 UI fallback 会产生底层连接噪音。

## 已修复

### 1. IBKR reconciliation route leg 对账

文件：

- `src/hermes_escape_top/ibkr/reconcile.py`
- `src/hermes_escape_top/tests/test_ibkr_reconcile.py`

修复：

- route leg 现在按 `sleeve_cap - target_weight` 计算剩余资金，而不是错误复用高风险标的 `target_weight`。
- 支持 `routing.weights` 多目的地路由，例如 `BOXX 70% + DBMF 30%`。
- `routing.applies=false` 时不会生成 route leg。
- 总 ideal/actual exposure 现在包含 trade symbols 和 route legs。

### 2. IBKR Gateway 断连 fallback 静音

文件：

- `src/hermes_escape_top/ibkr/positions.py`
- `src/hermes_escape_top/tests/test_ibkr_positions.py`

修复：

- 在导入/调用 `ib_insync` 前先做轻量 TCP port preflight。
- TWS/Gateway 端口没有监听时，直接读取最新 `positions_cache.json`。
- 没有缓存时返回 `source=unavailable`，并携带明确 error。
- 新增测试覆盖“端口关闭时不触发 live connect，直接 fallback”。

### 3. 数据质量扣分去重

文件：

- `src/hermes_escape_top/core/data/quality.py`
- `src/hermes_escape_top/tests/test_phase1_data_flow.py`

修复：

- 同一 symbol/source/reason 的 proxy penalty 只扣一次，取该组最大 penalty。
- 同一 symbol/source/latency_days 的 latency penalty 只扣一次，避免 AAII/NAAIM 这类同源字段重复拖垮总置信度。
- 真实 `score_pipeline("2026-05-29")` 验证后，`data_quality.level = HIGH`，`overall_score = 92.55`。

### 4. B6 valuation missing 不再静默安全

文件：

- `src/hermes_escape_top/core/scoring/module_b.py`
- `src/hermes_escape_top/core/scoring/scorer.py`
- `src/hermes_escape_top/tests/test_phase3_scoring.py`

修复：

- `module_b_factors(symbol)` 现在注册 `SOFT.<symbol>_valuation_pctl` 依赖。
- B6 估值缺失会进入 missing-weight / blind-spot 体系，而不是返回 0 分假装安全。

### 5. Full backtest 切到生产 sizing optimizer

文件：

- `src/hermes_escape_top/core/backtest/run_full.py`
- `src/hermes_escape_top/tests/test_phase11_backtest.py`

修复：

- full backtest 从 legacy `size_portfolio` 切到生产 `_optimize_sizing`。
- 回测 rows 保留 `portfolio_risk_legacy_shadow` 作为历史风险预算上下文。
- 测试断言 sizing engine 为 `optimize_targets_v1`。

### 6. Integration harness 传入 optimizer 必要上下文

文件：

- `src/hermes_escape_top/core/pipeline.py`

修复：

- `optimize_targets()` 现在收到 `leg_returns` 和 `liquidity_data`。
- 新增 `_liquidity_data()`，输出 `price / adv20_shares / adv20_notional / netliq`。
- 文档注释从“唯一入口”改为“integration harness”，避免和生产 `hermes_escape_top.pipeline` 入口冲突。

### 7. WebUI 刷新语义改为显式按钮

文件：

- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/tests/test_phase15_integration.py`

修复：

- `GET /` 只读取最新缓存；无缓存时展示空 dashboard 和 `no cache`。
- `GET /api/score` 只读缓存，不再隐式跑全量评分。
- `POST /api/refresh_score` 才执行 `score_pipeline()` 并更新 archive。
- WebUI 顶部新增“更新策略数据”按钮，点击后 POST 刷新并 reload 页面。
- 缓存读取路径改成 `load_config()+resolve_path("archive_dir")`，与评分管线同源。
- 浏览器验证显示：页面 `cache hit`、按钮存在、刷新后仍可显示完整 `Posterior Ideal P/L` 和 `Escape Decisions`。

## 验证

### Targeted tests

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_ibkr_positions.py \
  src/hermes_escape_top/tests/test_ibkr_reconcile.py \
  src/hermes_escape_top/tests/test_phase3_scoring.py \
  src/hermes_escape_top/tests/test_phase1_data_flow.py \
  src/hermes_escape_top/tests/test_phase11_backtest.py \
  src/hermes_escape_top/tests/test_pipeline.py \
  src/hermes_escape_top/tests/test_phase14_web.py
```

结果：

```text
Ran 51 tests in 17.495s
OK
```

### Web / IBKR integration tests

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_ibkr_positions.py \
  src/hermes_escape_top/tests/test_ibkr_reconcile.py
```

结果：

```text
Ran 21 tests in 7.534s
OK
```

### Full package tests

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 317 tests in 41.928s
OK
```

### Real pipeline smoke

```bash
PYTHONPATH=src python3 - <<'PY'
from hermes_escape_top.pipeline import score_pipeline
payload = score_pipeline("2026-05-29")
print(payload["data_quality"])
PY
```

结果摘要：

- `data_quality.level = HIGH`
- `data_quality.overall_score = 92.55`
- A/B/C/D 模块正常出分。
- `MSTR = EXIT`，硬阀门 `H-M1/H-M4`。
- `SOXL = REDUCE`。
- `FNGU = WATCH`。

### Browser smoke

临时启动：

```bash
PYTHONPATH=src python3 -m hermes_escape_top.cli serve --as-of 2026-05-29 --host 127.0.0.1 --port 8776
```

浏览器验证：

- 页面标题：`Hermes Escape Top`
- 顶部按钮：`更新策略数据`
- 缓存徽标：`cache hit`
- 页面包含：`Posterior Ideal P/L`
- 页面包含：`Escape Decisions`
- 点击刷新按钮后页面仍正常回到完整 dashboard。

## 剩余风险

- 当前验证环境没有真实 IBKR Gateway 在线连接；已验证的是端口关闭 fallback 和缓存读取，不等同于实盘 TWS 数据拉取验收。
- B6 valuation 已进入 missing-weight，但高质量估值源仍需要后续接入更稳定的行业/标的估值数据。
- WebUI 刷新按钮当前是同步等待评分；如果未来接入更慢的数据源，建议升级为后台任务 + 进度轮询。
