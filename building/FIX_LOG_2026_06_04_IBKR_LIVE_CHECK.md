# Fix Log — 2026-06-04 IBKR live check

## 背景

上一轮 WebUI/数据接口修复后，剩余风险是：IBKR Gateway 未在线时只能验证 fallback/cache/read-only 逻辑，不能确认真实 TWS/Gateway live 拉取。

本轮新增一个明确的 read-only live 验收入口。它不会下单，只做：

1. 强制检查 IBKR 来源是否为 `tws`。
2. 只有 `source=tws` 时才继续跑策略刷新。
3. 写 JSON/Markdown 验收报告。
4. WebUI 顶部提供一键 live 验收按钮。

## 已新增

### 1. Live checker 核心模块

文件：

- `src/hermes_escape_top/ibkr/live_check.py`

行为：

- `run_live_check(as_of)`
- 首轮调用 `read_positions(config)`。
- 若返回 `source != "tws"`：
  - 返回 `ok=false`
  - `status=IBKR_NOT_LIVE`
  - 不继续跑 `score_pipeline`
  - 明确提示 cached snapshot 不算 live 验收。
- 若返回 `source == "tws"`：
  - 跑 `score_pipeline(as_of, shadow=False)`
  - 要求评分 payload 里的 `ibkr.source == "tws"`
  - 返回 `LIVE_OK` 或 `SCORE_IBKR_NOT_TWS`
  - 汇总三只标的状态、分数、卖出比例、target weight、route。
- 报告写入：
  - `data/archive/live_checks/ibkr_live_check_<as_of>_<timestamp>.json`
  - `data/archive/live_checks/ibkr_live_check_<as_of>_<timestamp>.md`

### 2. CLI / root script

文件：

- `src/hermes_escape_top/scripts/ibkr_live_check.py`
- `scripts/ibkr_live_check.py`
- `src/hermes_escape_top/cli.py`

用法：

```bash
scripts/ibkr_live_check.py --as-of 2026-06-02
```

或：

```bash
PYTHONPATH=src python3 -m hermes_escape_top.cli ibkr-live --as-of 2026-06-02
```

退出码：

- `0` = `LIVE_OK`
- `2` = 未通过 live 验收，例如 Gateway 未连接。

### 3. WebUI live 按钮

文件：

- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/render.py`

新增接口：

- `POST /api/ibkr_live_check`

新增按钮：

- `IBKR Live 验收`

页面行为：

- 点击后显示：
  - `status`
  - `ok`
  - `source`
  - `account`
  - `net_liq`
  - `error`
  - live check JSON/Markdown 报告路径
- 只有 `LIVE_OK` 时才自动 reload 页面。

## 当前环境实测

当前 IBKR Gateway/TWS 未监听端口，因此 live check 正确失败：

```text
exit_code=2
ok=False
status=IBKR_NOT_LIVE
source=snapshot / unavailable
error=Could not connect to TWS on any of [4001, 4002, 7496, 7497]
```

WebUI 按钮实测结果：

```text
status=IBKR_NOT_LIVE
ok=false
source=snapshot
account=U18122312
net_liq=86202.96
error=Could not connect to TWS on any of [4001, 4002, 7496, 7497]
message=IBKR Gateway/TWS is not live. Cached snapshots are not accepted for live verification.
```

这证明缓存不会被误当成 live。

## 验证

### GitHub targeted tests

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_ibkr_live_check.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 8 tests in 8.228s
OK
```

### GitHub full tests

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 320 tests in 42.034s
OK
```

### 本地生产目录 targeted tests

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m unittest discover \
  -s /Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/tests \
  -p 'test_ibkr_live_check.py'
```

结果：

```text
Ran 2 tests in 0.001s
OK
```

`test_phase14_web.py` 与 `test_phase15_integration.py` 本地也通过。

## 使用提示

Gateway 在线后，直接在 WebUI 点：

```text
IBKR Live 验收
```

或者命令行跑：

```bash
/Users/liweishi/.hermes/skills/investment/escape-top/scripts/ibkr_live_check.py --as-of 2026-06-02
```

只要结果不是 `LIVE_OK`，就不要把这次结果当成真实 IBKR live 验收。
