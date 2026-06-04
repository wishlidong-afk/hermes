# Fix Log — 2026-06-04 WebUI 持仓刷新与总资产框

## 背景

用户要求在 8766 新系统 WebUI 顶部增加一个“更新持仓”按钮，并在 IBKR 对账右侧增加一个展示 IBKR 当前总资产数额的框。

## 已完成

### 1. 顶部新增“更新持仓”按钮

文件：

- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/server.py`

新增按钮：

```text
更新持仓
```

按钮调用：

```text
POST /api/refresh_positions
```

行为：

- 只读触发 package pipeline。
- 重新拉取 IBKR positions。
- 重新生成 `payload["ibkr"]` 对账数据。
- 写入最新 audit cache，页面 reload 后直接显示新持仓数字。
- 不下单，不修改 IBKR 账户。

### 2. IBKR 对账区右侧新增总资产框

文件：

- `src/hermes_escape_top/web/render.py`

新增醒目框：

```text
IBKR 现有总资产 / NetLiq
```

显示字段：

- `net_liq`
- `source`
- `max_abs_delta`

这样不用再从持仓对账小字里找 NetLiq。

### 3. 回归测试补齐

文件：

- `src/hermes_escape_top/tests/test_phase14_web.py`
- `src/hermes_escape_top/tests/test_phase15_integration.py`

新增断言：

- 页面必须包含 `更新持仓`
- 页面必须包含 `IBKR 现有总资产`
- `POST /api/refresh_positions` 必须返回 `ibkr`

## 本地 8766 验收

服务已重启到 detached screen：

```text
screen session: hermes-escape-8766
URL: http://localhost:8766/
```

接口验收：

```text
GET /health -> {"ok":true}
POST /api/refresh_positions
  ibkr_source=tws
  net_liq=$84,635.61
  data_quality=HIGH
```

浏览器验收：

```text
更新持仓: true
IBKR 现有总资产: true
tws: true
```

并已实际点击“更新持仓”按钮，页面 reload 后仍显示 `IBKR tws` 与总资产数字。

## 验证

Targeted tests:

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 6 tests in 11.234s
OK
```

Full tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 320 tests in 50.767s
OK
```
