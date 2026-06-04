# Fix Log — 2026-06-04 run_daily / WebUI / data-interface remediation

## 背景

本轮用户要求“全都改”，并特别要求：

- 继续参考此前 review 意见修复当前系统。
- WebUI 做回此前可看、可点、可更新的样式。
- 数据接口接新的包引擎数据源。
- 核查 `run_daily.py` 是否已改成调用包引擎，并继续逐行复盘。

本轮同时处理 GitHub 仓库与本地生产目录：

- GitHub repo: `/Users/liweishi/Documents/github/hermes`
- 本地生产 skill: `/Users/liweishi/.hermes/skills/investment/escape-top`

## run_daily.py 核查结论

本地生产目录中的切换属实：

- `scripts/run_daily.py` 已是 package shim。
- `scripts/run_daily.py.monolith_backup` 存在，保留旧单体入口：
  `from escape_top_system import main`
- 当前 `run_daily.py` 会调用：
  `scripts/run_daily_package.py --live --commit-state`

## 已修复

### 1. score_pipeline 支持 shadow 隔离

文件：

- `src/hermes_escape_top/pipeline.py`
- 本地同步到 `.hermes/.../hermes_escape_top/pipeline.py`

修复：

- `score_pipeline(as_of, shadow=False)` 新增 `shadow` 参数。
- shadow 模式下审计日志写入 `data/shadow/archive/audit_log.jsonl`。
- shadow 模式下 signal journal 写入 `data/shadow/signal_journal.jsonl`。
- 正式模式仍写生产 archive/signal journal。
- reentry 的 `days_since_last_sell` 仍读取生产 signal journal，避免影子运行污染小黑屋判断。

### 2. run_daily_package.py 变成真正可上线运行器

文件：

- `src/hermes_escape_top/scripts/run_daily_package.py`
- 本地同步到 `.hermes/.../scripts/run_daily_package.py`

修复：

- 同时兼容 GitHub repo 布局与本地 `.hermes` skill 布局。
- subprocess 自动注入正确 `PYTHONPATH`。
- 不再默认使用日历今天；未传 `--as-of` 时自动选择当前缓存里最新共同交易日。
- `--commit-state` 已实现，不再是文档占位。
- live + commit 会写 `state.json`，shadow 模式不会改生产 state。
- state suggestions 新增：
  - `current_state`
  - `next_state`
  - `reason`
  - `cooldown_days_left`
  - `sell_pct`
  - `hard_triggered`
- 订单预览接入 IBKR 对账快照：
  - 如果有真实股数，输出只读卖出股数和估算金额。
  - 如果 IBKR 不在线，明确显示 `SIGNAL_ONLY`，不假装知道股数。
- 资金路由文字不再空白，支持多目的地：
  - `BOXX 70% + DBMF 30%`
  - `BRK.B`
  - 对应 1 倍标的降维。
- 兼容日报 JSON、订单预览 JSON、Markdown 报告继续写入根目录 `data/reports/orders`。

### 3. GitHub 根目录新增稳定入口

文件：

- `scripts/run_daily.py`
- `scripts/run_daily_package.py`

修复：

- GitHub repo 现在也有根目录运行入口，部署/runbook 不需要知道 `src/hermes_escape_top/scripts/...` 内部路径。
- 根 `run_daily.py` 只做 live + commit shim。
- 根 `run_daily_package.py` 只透传到 package runner，不复制业务逻辑。

### 4. WebUI 后端路径与接口统一

文件：

- `src/hermes_escape_top/web/server.py`
- 本地同步到 `.hermes/.../hermes_escape_top/web/server.py`

修复：

- 自动识别 repo 布局和本地 skill 布局。
- `GET /` 只读最新包审计缓存，不隐式跑评分。
- `GET /api/score` 只读缓存。
- `POST /api/refresh_score` 才执行 `score_pipeline()`。
- 恢复旧 UI 所需的 `/api/m4_backfill`：
  - 刷新 OHLCV。
  - 尝试用 monolith backup 生成基准。
  - 再跑包引擎影子对比。
- M4 shadow subprocess 同样注入正确 `PYTHONPATH`。
- `M4 go-live` 在 repo 无根 `run_daily.py` 时可创建 shim；有旧文件时先备份。

### 5. WebUI 前端恢复旧样式并接新接口

文件：

- `src/hermes_escape_top/web/render.py`
- 本地同步到 `.hermes/.../hermes_escape_top/web/render.py`

修复：

- 保留此前旧式 M4 迁移控制台：
  - 今日影子对比
  - 补基准并对比
  - 上线切换
  - 最近影子运行历史
  - 最新影子预检结果
- 顶部新增“更新策略数据”按钮。
- 页面显示 `cache hit / no cache`。
- 刷新按钮调用 `POST /api/refresh_score`，完成后 reload。
- 页面继续展示：
  - System Health
  - Escape Decisions
  - Optimizer Detail
  - Factor Scores
  - Audit Detail
  - Portfolio Risk
  - Mirror Reference
  - Posterior Ideal P/L
  - IBKR Reconciliation

### 6. 本地生产目录补齐此前 GitHub fixes

同步文件：

- `ibkr/positions.py`
- `ibkr/reconcile.py`
- `core/data/quality.py`
- `core/scoring/module_b.py`
- `core/scoring/scorer.py`

补齐内容：

- IBKR Gateway 不在线时先 TCP preflight，再 fallback 到 position cache，避免连接噪音。
- route legs 按 `sleeve_cap - target_weight` 计算，并支持多目的地路由。
- 数据质量 penalty 按来源分组去重，避免同一缺口重复扣分。
- B6 valuation 缺失进入 missing-weight，不再默认安全 0 分。

## 验证

### GitHub repo 编译

```bash
python3 -m py_compile \
  src/hermes_escape_top/scripts/run_daily_package.py \
  src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/web/server.py \
  src/hermes_escape_top/web/render.py \
  scripts/run_daily.py \
  scripts/run_daily_package.py
```

结果：OK

### GitHub repo 全量测试

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 317 tests in 41.371s
OK
```

### 本地生产目录全量测试

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m unittest discover \
  -s /Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/tests \
  -p 'test_*.py'
```

结果：

```text
Ran 311 tests in 40.792s
OK
```

### 本地 shadow run

```bash
/Users/liweishi/.hermes/skills/investment/escape-top/scripts/run_daily_package.py --skip-refresh
```

结果摘要：

- 自动选择最新共同缓存交易日：`2026-06-02`
- `score_pipeline(..., shadow=True)` 成功。
- 写入：
  - `data/shadow/daily_score_precheck_2026-06-02.json`
  - `orders/shadow/orders_preview_2026-06-02.json`
  - `reports/shadow/daily_report_2026-06-02.md`
- 无 IBKR 连接拒绝噪音。
- `data_quality.level = HIGH`
- `data_quality.overall_score = 86.55`
- 路由文字已正确显示：
  - `MSTR EXIT 100% -> BOXX 70% + DBMF 30%`
  - `FNGU REDUCE 60% -> BOXX 70% + DBMF 30%`
  - `SOXL REDUCE 60% -> BOXX 70% + DBMF 30%`

### commit-state 临时目录模拟

用临时目录 monkeypatch `BASE_DIR` 验证 `commit_state()`：

结果：

```text
MSTR -> COOLDOWN, last_exit_date=2026-06-02
FNGU -> HOLDING
SOXL -> WATCHING
```

未改正式 `state.json`。

### WebUI 临时端口验证

启动：

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m hermes_escape_top.cli serve --host 127.0.0.1 --port 8776 --as-of 2026-06-02
```

浏览器验证：

- 页面标题：`Hermes Escape Top`
- 顶部按钮：`更新策略数据`
- 缓存状态：`cache hit`
- 页面包含：`M4 迁移控制台`
- 页面包含：`补基准并对比`
- 页面包含：`Escape Decisions`
- 页面包含：`Optimizer Detail`
- 页面包含：`IBKR Reconciliation`

接口验证：

```bash
curl -X POST http://127.0.0.1:8776/api/refresh_score \
  -H 'Content-Type: application/json' \
  -d '{"as_of":"2026-06-02"}'
```

结果摘要：

- `schema = escape-top-greenfield-phase3-score-v1`
- `as_of = 2026-06-02`
- `scores = FNGU / MSTR / SOXL`
- `audit_log_path = .../hermes_escape_top/data/archive/audit_log.jsonl`
- 当前 IBKR 未在线，返回结构化 snapshot/unavailable 信息，不再喷底层连接日志。

## 重要说明

- 本轮没有提交真实订单。
- 本轮没有为了测试而改正式 `state.json`。
- WebUI 的“更新策略数据”会正式写 package audit/signal journal；这是显式按钮行为，不再由 GET 页面触发。
- 本地缓存最新共同交易日是 `2026-06-02`，说明行情缓存仍需通过刷新链条推进到最新美股交易日。
- IBKR 当前没有 TCP listener，因此只能验证 fallback/cache/read-only 逻辑；真实 Gateway 在线拉取仍需在 IBKR 打开时再验收。

## 剩余风险 / 下一步

- 如果希望 WebUI 的“更新策略数据”也先刷新 OHLCV，需要在按钮旁再加一个“全量同步数据+评分”按钮，避免普通刷新耗时过长。
- 当前 `state.json` 正式提交只在 daily live runner 的 `--commit-state` 下执行；WebUI 刷新不提交状态，这是有意隔离。
- `monolith_backup` 只存在本地生产目录；GitHub repo 没有旧单体源码，repo 内的补基准按钮在没有 backup 时会明确失败。
