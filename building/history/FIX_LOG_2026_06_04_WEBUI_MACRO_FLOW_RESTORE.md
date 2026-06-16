# Fix Log — 2026-06-04 WebUI 宏观评分与底层资金流恢复

## 背景

用户指出新版 8766 WebUI 缺少两块老页面已有的信息：

- `每日处置指令` 上方需要展示主要宏观模块评分。
- 三个策略卡下方需要展示 MSTR / FNGU / SOXL 相关底层持仓资金流入流出情况。

## 已完成

### 1. Pipeline payload 增加 flow 数据

文件：

- `src/hermes_escape_top/pipeline.py`

新增：

```text
payload["flow"]
```

结构沿用既有资金流契约：

- `flow.symbols`
  - MSTR / FNGU / SOXL 自身 CMF20、MFI14、A-D slope、5 日估算净流。
- `flow.component_baskets`
  - FNGU 成分篮子。
  - SOXL 成分篮子。

同时让 `flow_snapshot()` 复用同一个 `_flow_payload()` helper，避免页面、CLI、测试以后出现两套资金流算法。

### 2. 新增主要宏观模块评分区

文件：

- `src/hermes_escape_top/web/render.py`

位置：

```text
System Health 下方
Escape Decisions / 今日处置指令 上方
```

展示内容：

- A 模块总分：`得分 / 可用总分`
- 是否触发 `BOXX 宏观核爆阈值`
- Regime
- VIX percentile
- QQQ close / MA200
- A 模块逐指标表：
  - 指标 ID
  - 得分
  - 解释
  - 缺失字段

### 3. 新增底层持仓资金流入/流出监控

文件：

- `src/hermes_escape_top/web/render.py`

位置：

```text
MSTR / FNGU / SOXL 三个策略卡下方
```

展示内容：

- MSTR 自身资金流。
- FNGU 主要成分资金流。
- SOXL 主要成分资金流。

字段：

- severity
- CMF20
- MFI14
- 5 日估算净流
- 流出天数

排序：

- `SEVERE / ABNORMAL / WATCH` 优先展示在表格上方。

视觉：

- 资金流出为红色。
- 资金流入为绿色。
- 异常程度用 badge 标识。

## 8766 本地验收

刷新：

```bash
POST http://localhost:8766/api/refresh_score
```

结果：

```text
has_flow=True
flow_baskets=['FNGU', 'SOXL']
data_quality=HIGH
```

页面标记：

```text
主要宏观模块评分: true
A Macro Module: true
底层持仓资金流入/流出监控: true
CMF20: true
MFI14: true
5日净流: true
NVDA: true
NFLX: true
SOXL 资金流: true
```

浏览器已实际打开 `http://localhost:8766/` 验证，宏观区在处置指令上方，资金流区在三张策略卡下方。

## 测试

Targeted tests:

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase3_scoring.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 13 tests in 88.695s
OK
```

Full tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 320 tests in 256.889s
OK
```

注：本轮 full tests 耗时偏长，原因是当前 IBKR Gateway/TWS 端口在多次测试中出现 read-only 连接超时；测试仍全部通过，系统按预期 fallback 到 snapshot。

## 剩余风险

- 资金流是基于 OHLCV 推导的 CMF/MFI/A-D slope 与 5 日 signed dollar-flow proxy，不是券商逐笔真实资金流。
- IBKR 当前时刻有超时，页面显示可能为 `snapshot`，但宏观评分和底层资金流不依赖 IBKR live。
