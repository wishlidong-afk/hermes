# Fix Log — 2026-06-04 新系统逃顶 WebUI 重搭

## 背景

用户要求基于当前 package 新系统，参考此前老版逃顶 WebUI，重新搭建 8766 WebUI，并且必须连接到新系统里的真实数字，而不是旧缓存或旧字段。

本轮处理范围：

- GitHub repo: `/Users/liweishi/Documents/github/hermes`
- 本地生产 skill: `/Users/liweishi/.hermes/skills/investment/escape-top`
- WebUI port: `8766`

## 已完成

### 1. WebUI 完整重搭为新系统驾驶舱

文件：

- `src/hermes_escape_top/web/render.py`
- 已同步到本地生产目录：
  `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/web/render.py`

新页面核心区块：

- `Hermes Escape Top / Hermes 逃顶驾驶舱` 顶部驾驶舱
- `System Health / Portfolio Risk / 系统状态`
- `Escape Decisions / 今日处置指令`
- `IBKR Reconciliation / 持仓对账`
- `Posterior Ideal P/L / 理想仓位上一交易日盈亏`
- `Mirror Reference / 镜像参考`
- `Audit Detail / 数据质量`
- 折叠式 `M4 迁移控制台 / 运维工具`

每个 MSTR / FNGU / SOXL 卡片现在直接读取 package payload：

- `scores`
- `module_scores`
- `factor_scores`
- `hard_valve_hits`
- `sizing`
- `routing`
- `reentry`
- `posterior_pnl`
- `portfolio_risk`
- `data_quality`
- `regime`
- `snapshots`
- `ibkr`

### 2. 修复审计缓存缺 IBKR 字段

文件：

- `src/hermes_escape_top/pipeline.py`
- 已同步到本地生产目录。

问题：

- 原先 `score_pipeline()` 在写 `audit_log.jsonl` 后才追加 `payload["ibkr"]`。
- 结果是 WebUI 的 `GET /api/score` 读最新审计缓存时，可能没有 IBKR 持仓数字。

修复：

- 将 `write_audit_record()` 和 `append_signal_journal()` 移到 IBKR reconciliation 之后。
- 现在刷新后的审计缓存会包含完整 `payload["ibkr"]`。

### 3. 修复 Web server 线程内 IBKR live 读取

文件：

- `src/hermes_escape_top/ibkr/positions.py`
- 已同步到本地生产目录。

问题：

- `ThreadingHTTPServer` 的请求 handler 在线程中执行。
- `ib_insync` 在非主线程导入/构造时需要当前线程存在 asyncio event loop。
- 旧逻辑会回退到 snapshot，并在 WebUI 上显示旧快照。

修复：

- 在导入 `ib_insync.IB` 之前先确保当前线程存在 event loop。
- 读取成功后保持 read-only，不下单。
- 线程最小复现已验证：

```text
thread source tws
error None
```

### 4. 8766 后台运行方式

已用 detached screen 启动：

```bash
screen -dmS hermes-escape-8766 zsh -lc 'cd /Users/liweishi/Documents/github/hermes; export PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top; python3 -m hermes_escape_top.cli serve --as-of 2026-05-29 --host 127.0.0.1 --port 8766 >> /tmp/hermes_escape_top_8766.log 2>&1'
```

健康检查：

```text
http://localhost:8766/health -> {"ok":true}
```

当前监听：

```text
127.0.0.1:8766
screen session: hermes-escape-8766 (Detached)
```

## 实测数据

`POST /api/refresh_score` 已确认返回 live IBKR：

```text
source=tws
account_id=U18122312
net_liq=$84,632.40
quality=HIGH
```

页面首屏显示：

- `Data HIGH`
- `IBKR tws`
- `Regime LOW_VOL_TREND`
- `NetLiq $84,643.38`

注：NetLiq 会随 IBKR 实时快照轻微变化，以上为本轮验收时刻读数。

## 浏览器验收

应用内浏览器打开：

```text
http://localhost:8766/
```

确认核心标记全部存在：

```text
Hermes Escape Top: true
Hermes 逃顶驾驶舱: true
System Health: true
Portfolio Risk: true
Escape Decisions: true
IBKR Reconciliation: true
更新策略数据: true
MSTR/FNGU/SOXL: true
```

页面按钮：

- `更新策略数据` 可触发刷新接口。
- 页面刷新后仍显示 `IBKR tws`。

## 验证

### Targeted tests

```bash
python3 -m py_compile \
  src/hermes_escape_top/ibkr/positions.py \
  src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/web/render.py \
  src/hermes_escape_top/web/server.py

PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_ibkr_positions.py \
  src/hermes_escape_top/tests/test_ibkr_reconcile.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 22 tests
OK
```

### Full tests

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 320 tests in 49.103s
OK
```

## 剩余风险

- 当前 WebUI 是 read-only 监控和建议系统，仍然不会下单。
- `as_of` 仍按当前启动命令固定为 `2026-05-29`，后续若要作为每日生产页，应由 daily runner 或自动启动脚本传入最新交易日。
- 浏览器插件对 `http://127.0.0.1:8766/` 有过一次导航策略失败，但 `http://localhost:8766/` 已验证可正常打开。
