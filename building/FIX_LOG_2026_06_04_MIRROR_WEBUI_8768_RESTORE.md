# FIX LOG — 2026-06-04 — 镜像参考 WebUI 8768 恢复

## 背景

用户要求把此前独立的“镜像参考”网站恢复回来，固定运行在 `http://localhost:8768/`，并保持此前布局思路：

- 顶部可一键切换到逃顶主站 `8766`。
- 页面主体聚焦镜像策略，而不是逃顶主站。
- 展示 IBKR 持仓、周期判断、推荐处置、理想持仓、模型校准/后验记录。
- 使用新系统 package payload 和当前数据接口。

## 本次搭建内容

### 1. 新增独立镜像渲染器

文件：

- `src/hermes_escape_top/web/mirror_render.py`

实现：

- `render_mirror_dashboard(payload)`：生成独立镜像参考 HTML。
- `write_mirror_dashboard(payload, output_path)`：支持静态快照输出。
- 固定展示三条镜像腿：
  - `FNGU_QQQ`：`QQQ / FNGU 科技动能`，目标上限 20%。
  - `SOXL_SOXX`：`SOXX / SOXL 半导体`，目标上限 30%。
  - `MSTR_QQQ`：`MSTR / QQQ 比特币贝塔`，目标上限 15%。
- 按 IBKR `net_liq` 优先计算理想目标金额；没有 IBKR 时回退到后验组合值。
- 展示：
  - 周期判断与推荐处置。
  - 当前选择标的。
  - 理想资金比例、金额、市价股数。
  - 雷达数据：收盘、EMA20、MA200、MA220、60 日回撤。
  - IBKR 持仓。
  - 理想化持仓配比。
  - 上一交易日理想 P/L。
  - 主要持仓资金流入/流出。

### 2. 新增独立镜像服务

文件：

- `src/hermes_escape_top/web/mirror_server.py`

接口：

- `GET /`：镜像参考 WebUI。
- `GET /api/score`：读取缓存 score payload。
- `POST /api/refresh_score`：重跑 `score_pipeline(as_of)` 并返回新镜像数据。
- `POST /api/refresh_positions`：重跑 `score_pipeline(as_of)`，同步 IBKR 持仓/快照数据。
- `GET /health`：健康检查，返回 `{"ok":true,"app":"mirror"}`。

### 3. CLI 接入

文件：

- `src/hermes_escape_top/cli.py`

新增命令：

- `mirror-dashboard --as-of DATE --output PATH`
- `serve-mirror --as-of DATE --host 127.0.0.1 --port 8768`

### 4. 测试补齐

文件：

- `src/hermes_escape_top/tests/test_mirror_web.py`

覆盖：

- 独立镜像页面包含旧布局关键模块：
  - `Hermes 镜像参考`
  - `周期判断与推荐处置`
  - `IBKR 持仓`
  - `理想化持仓配比`
  - `模型校准 / 上一交易日理想 P/L`
  - `主要持仓资金流入/流出`
  - `切换逃顶 8766`
- 独立 mirror server 的 health 与 refresh 接口。

## 本地运行状态

已启动：

- URL：`http://localhost:8768/`
- screen session：`hermes-mirror-8768`
- log：`/tmp/hermes_mirror_8768.log`
- 默认 as_of：`2026-06-02`

当前页面读取结果：

- `Data HIGH`
- `IBKR snapshot`
- `Regime LOW_VOL_TREND`
- `Mirror cap 65.0%`
- IBKR NetLiq：`$84,610.29`
- 镜像选择：
  - `FNGU_QQQ -> FNGU`
  - `SOXL_SOXX -> SOXL`
  - `MSTR_QQQ -> QQQ`

## 验收结果

### 编译

```bash
python3 -m py_compile \
  src/hermes_escape_top/web/mirror_render.py \
  src/hermes_escape_top/web/mirror_server.py \
  src/hermes_escape_top/cli.py \
  src/hermes_escape_top/tests/test_mirror_web.py
```

结果：通过。

### 定向测试

```bash
PYTHONPATH=src python3 -m unittest src/hermes_escape_top/tests/test_mirror_web.py
```

结果：`Ran 2 tests ... OK`

### Web/镜像集成测试

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase12_mirror.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py
```

结果：`Ran 11 tests ... OK`

### 真实快照渲染

```bash
PYTHONPATH=src python3 -m hermes_escape_top.cli \
  mirror-dashboard --as-of 2026-06-02 --output /tmp/hermes_mirror_dashboard.html
```

结果：成功生成 HTML，并包含关键模块。

### 8768 服务验收

```bash
curl -sS http://127.0.0.1:8768/health
```

结果：

```json
{"ok":true,"app":"mirror"}
```

`POST /api/refresh_score` 返回：

- `as_of=2026-06-02`
- `data_quality=HIGH`
- `decisions={'FNGU_QQQ':'FNGU','MSTR_QQQ':'QQQ','SOXL_SOXX':'SOXL'}`
- `ibkr=snapshot`

### 浏览器验收

使用 Codex 内置浏览器打开：

- `http://localhost:8768/`

确认页面可见且包含：

- `Hermes 镜像参考`
- `周期判断与推荐处置`
- `IBKR 持仓`
- `理想化持仓配比`
- `模型校准 / 上一交易日理想 P/L`
- `主要持仓资金流入/流出`
- `切换逃顶 8766`

## 同步情况

已同步到本地运行目录：

- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/web/mirror_render.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/web/mirror_server.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/cli.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/tests/test_mirror_web.py`

## 剩余风险

- 当前 IBKR 来源为 `snapshot`，不是 live TWS。页面可以更新和参考，但是否拿到实时持仓取决于 IBKR Gateway/TWS 在线状态。
- 镜像站点是 advisory only，不含下单能力。
- 8768 与 8766 是两个独立 WebUI，当前共享同一套 package payload、历史数据、IBKR 快照与缓存读取机制。

