# FIX LOG — 2026-06-05 — WebUI 全量刷新链路与资金流数据库固化

## 背景

用户在 8766/8768 页面点击刷新后看到数据没有变化，尤其资金流仍像是 5 月底数据。

实际复现结果：

- 8768 点击“更新镜像数据”后，IBKR 能更新到 `tws`，但行情 `as_of` 仍停在 `2026-06-02`。
- 8766 点击“更新策略数据”后，页面仍是 `as_of=2026-05-29`。
- 资金流与页面 as_of 绑定，因此旧 as_of 会导致资金流也停在旧日期。

根因：

- 前端按钮把当前页面里的旧 `as_of` 发回服务端。
- 服务端 `POST /api/refresh_score` 只调用 `score_pipeline(as_of)`，没有先刷新 OHLCV 历史。
- `GET /` 没带 query 时使用服务启动时的固定默认日期，8766 之前一直是 `2026-05-29`。
- flow 只在 payload/audit 中临时出现，没有单独 SQLite 固化表。

## 修复内容

### 1. 新增全量刷新协调器

文件：

- `src/hermes_escape_top/web/refresh.py`

功能：

- `refresh_score_with_market_data(requested_as_of="latest")`
  - 先判断核心历史是否新鲜。
  - 如果核心历史陈旧，则调用 `backfill()` 刷新 38 个标的。
  - 自动选择核心标的共同最新交易日作为 `effective_as_of`。
  - 再调用 `score_pipeline(effective_as_of)`。
  - 返回 `refresh_status`，包含：
    - `history_refreshed`
    - `effective_as_of`
    - `latest_by_symbol`
    - `symbols_requested`
    - `symbols_updated`

核心日期锚定：

- `MSTR`
- `FNGU`
- `SOXL`
- `QQQ`
- `SOXX`
- `SPY`
- `^VIX`

避免可选代理指数把最新日期拖回旧日期。

### 2. 增加刷新新鲜度闸

如果核心历史最新日期距离今天不超过 3 个自然日：

- 跳过 Yahoo backfill。
- 直接重算 score/flow/IBKR。

目的：

- 首次从旧数据刷新时仍会拉最新行情。
- 已经更新到最新交易日后，再点击按钮不会反复跑 38 个标的的网络下载。
- WebUI 点击响应更快，避免浏览器等待超时。

### 3. flow SQLite 固化

文件：

- `src/hermes_escape_top/core/data/flow_store.py`

新增：

- `write_flow_snapshot(path, flow_payload)`

数据库：

- `flow_reference.sqlite`
- 表：`flow_snapshots`

字段：

- `as_of`
- `kind`：`symbol` 或 `basket`
- `symbol`
- `severity`
- `payload_json`

Pipeline 接线：

- 文件：`src/hermes_escape_top/pipeline.py`
- 每次 `score_pipeline()` 生成 flow 后写入：
  - `data/archive/flow_reference.sqlite`
- payload 中回填：
  - `flow.db_path`

### 4. 8766/8768 服务端刷新接线

文件：

- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/mirror_server.py`

改造：

- `GET /` 默认读取最新缓存，而不是固定启动日期。
- `POST /api/refresh_score` 调用 `refresh_score_with_market_data("latest")`。
- `POST /api/refresh_positions` 同样走全量刷新链路，避免持仓更新后行情/flow 不同步。

### 5. 前端按钮修复

文件：

- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/mirror_render.py`

改造：

- “更新策略数据/更新镜像数据”发送：
  - `{"as_of":"latest","refresh_history":true}`
- 刷新成功后跳转到：
  - `/?as_of=<payload.as_of>`
- “更新持仓”同样更新后跳转到最新 as_of。
- 资金流区域显示 `flow.db_path`，方便确认 flow 是否已固化数据库。

### 6. 防止账户缓存误提交

文件：

- `.gitignore`

新增忽略：

- `src/data/positions_cache.json`

原因：

- 该文件包含账户号、NetLiq 等本地账户缓存，不应提交到 GitHub。

## 真实刷新结果

在本机 `.hermes` 运行目录实际刷新：

### 8766

```text
8766 as_of=2026-06-04
flow_as_of=2026-06-04
flow_db=/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/flow_reference.sqlite
IBKR source=tws
```

### 8768

```text
8768 as_of=2026-06-04
flow_as_of=2026-06-04
flow_db=/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/flow_reference.sqlite
IBKR source=tws
```

flow SQLite 验证：

```text
2026-06-04|basket|FNGU|ABNORMAL
2026-06-04|basket|SOXL|NORMAL
2026-06-04|symbol|FNGU|NORMAL
2026-06-04|symbol|MSTR|WATCH
2026-06-04|symbol|SOXL|NORMAL
```

浏览器手动点击验证：

- 8766 点击“更新策略数据”后：
  - URL：`http://localhost:8766/?as_of=2026-06-04`
  - 页面包含 `flow_reference.sqlite`
  - 页面包含“底层持仓资金流入/流出监控”
- 8768 点击“更新镜像数据”后：
  - URL：`http://localhost:8768/?as_of=2026-06-04`
  - 页面包含 `flow_reference.sqlite`
  - 页面包含“主要持仓资金流入/流出”

## 当前 MEDIUM 数据质量解释

页面当前显示 `Data MEDIUM`，不是行情或 flow 没刷新。

原因来自软数据扣分：

- CBOE PCR 仍为 proxy。
- component breadth 为 proxy。
- valuation 为 proxy。
- net liquidity 延迟。
- AAII 延迟。
- NAAIM 延迟。

行情、IBKR、flow 均已刷新到 `2026-06-04`。

## 验收

### 编译

```bash
python3 -m py_compile \
  src/hermes_escape_top/web/refresh.py \
  src/hermes_escape_top/web/server.py \
  src/hermes_escape_top/web/mirror_server.py \
  src/hermes_escape_top/web/render.py \
  src/hermes_escape_top/web/mirror_render.py \
  src/hermes_escape_top/core/data/flow_store.py \
  src/hermes_escape_top/pipeline.py
```

结果：通过。

### 测试

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_flow_store.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_phase14_web.py
```

结果：`Ran 9 tests ... OK`

### 服务

```text
8766 health: {"ok":true}
8768 health: {"ok":true,"app":"mirror"}
```

## 同步情况

已同步到本地运行目录：

- 新刷新协调器。
- flow SQLite 写入模块。
- 8766/8768 server。
- 8766/8768 render。
- 6/4 最新历史 CSV。
- `flow_reference.sqlite`
- `soft_adapter_snapshot_2026-06-04.json`

## 剩余风险

- 如果软数据源本身延迟或只能代理，Data 仍可能显示 MEDIUM；这不代表 OHLCV/flow/IBKR 没刷新。
- 首次从很旧日期刷新仍需下载大量标的，可能需要几十秒；更新到最新后重复点击会走新鲜度快路径。
- `positions_cache.json` 含账户缓存，已加入 `.gitignore`，不提交。


## 追加修复：IBKR snapshot 防旧缓存标记

用户继续指出：IBKR 未连上时不能读取非常老的数据，必须遍历/使用最新快照，并把快照固化成数据文件。

改造文件：

- `src/hermes_escape_top/ibkr/positions.py`
- `src/hermes_escape_top/ibkr/reconcile.py`
- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/mirror_render.py`

新增字段：

- `snapshot_age_seconds`
- `snapshot_stale`

行为：

- IBKR live 读取成功：`source=tws`，`snapshot_age_seconds=0.0`，`snapshot_stale=false`，并写入本地 `data/positions_cache.json`。
- IBKR live 短暂抢连失败：读取最新 `positions_cache.json`，但计算快照年龄。
- 如果快照超过默认 15 分钟，API/页面明确标记 `STALE`，并把 stale 原因写入 `error`。
- 8766/8768 的 IBKR 区域展示 `sync`、`age`、`FRESH/STALE`，过期时用 danger 样式提示。

最新真实接口验收：

```text
8766 refresh_score:
  as_of=2026-06-04
  flow_as_of=2026-06-04
  source=snapshot
  net_liq=86005.32
  snapshot_age_seconds≈3s
  snapshot_stale=false
  flow_db=/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/flow_reference.sqlite

8768 refresh_score:
  as_of=2026-06-04
  flow_as_of=2026-06-04
  source=snapshot
  net_liq=86005.32
  snapshot_age_seconds≈3s
  snapshot_stale=false
  flow_db=/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/data/archive/flow_reference.sqlite

8768 refresh_positions:
  source=tws
  net_liq=86005.32
  snapshot_age_seconds=0.0
  snapshot_stale=false
```

说明：两个 WebUI 同时刷新时，IBKR Gateway 偶尔只允许其中一个进程拿到 live session；另一个会读取刚刚写入的 snapshot。现在 snapshot 年龄会被明确展示，旧 snapshot 不会再静默伪装成实时数据。

追加测试：

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_ibkr_positions.py \
  src/hermes_escape_top/tests/test_ibkr_reconcile.py \
  src/hermes_escape_top/tests/test_flow_store.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_phase14_web.py
```

结果：`Ran 26 tests ... OK`
