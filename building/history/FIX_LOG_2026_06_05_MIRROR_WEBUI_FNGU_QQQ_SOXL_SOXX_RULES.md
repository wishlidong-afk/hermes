# FIX LOG — 2026-06-05 — 8768 镜像参考改为 FNGU/QQQ + SOXL/SOXX 双杠杆策略

## 背景

用户要求将 `http://localhost:8768/` 的镜像参考站点按“美股双杠杆 ETF 量化策略合集”更新。

澄清后最终规则为：

- 第一套不是 `QQQ/TQQQ`，而是 `FNGU/QQQ`，使用 QQQ 作为雷达。
- 第二套为 `SOXL/SOXX`，使用 SOXX 作为雷达。
- 继续保留之前 8768 的布局骨架：IBKR、周期判断、推荐处置、理想仓位、后验记录、资金流。

## 本次实现

### 1. 镜像策略引擎改造

文件：

- `src/hermes_escape_top/mirror/strategy.py`

改造：

- 旧三腿 `FNGU_QQQ / SOXL_SOXX / MSTR_QQQ` 改为新两腿：
  - `FNGU_QQQ`
  - `SOXL_SOXX`
- `MirrorLegDecision` 新增：
  - `allocations`：分标的全盘目标权重。
  - `rule_checks`：每条规则是否满足。
  - `metrics`：关键指标读数。
  - `stop_rules`：止损止盈和禁令。
- `build_mirror_plan()` 现在接收 `histories` 与 `as_of`，用于计算：
  - 近 5/10 日涨幅。
  - 20 日量能放大倍数。
  - 连续上涨天数。
  - SOXX 相对 SPY 的 20 日相对强弱。
  - 高开低走放量 K 线。

### 2. FNGU/QQQ 规则

雷达：`QQQ`

入场/强趋势检查：

- QQQ 收盘 > EMA20。
- QQQ 收盘 > EMA50。
- EMA20 > EMA50。
- 近 5 日涨幅 >= 3%。
- 成交量放大 >= 20%。
- VIX < 25。
- RSI14 < 70。
- MACD 多头。
- 连续 3 日上涨。

仓位解释：

- 原表格权重解释为“策略桶内权重”，再乘以 `FNGU/QQQ` 桶上限 20%。
- 强趋势：QQQ 60% + FNGU 50%，映射为全盘 `QQQ 12% + FNGU 10%`。
- 弱趋势：QQQ 70% + FNGU 20%，映射为全盘 `QQQ 14% + FNGU 4%`。
- 震荡市：QQQ 80% + FNGU 0%，映射为全盘 `QQQ 16%`。
- 风险预警：QQQ 50% + FNGU 0%，映射为全盘 `QQQ 10%`。

止损止盈纪律已写入 WebUI：

- FNGU 单笔亏损 >= 8% 强制止损。
- QQQ 跌破 EMA20：清 FNGU，QQQ 降至风险预警配置。
- FNGU 盈利 15% 减 50%，盈利 25% 清仓。
- QQQ 盈利 8% 减 30%，盈利 15% 减 50%。
- FNGU 单次持仓不超过 15 个交易日。
- 禁止震荡市长持 FNGU。

### 3. SOXL/SOXX 规则

雷达：`SOXX`

入场/强繁荣检查：

- SOXX 收盘 > EMA50。
- SOXX 收盘 > MA200。
- EMA50 > MA200。
- 近 10 日涨幅 >= 8%。
- 成交量放大 >= 30%。
- SOXX 相对 SPY 的 20 日 RS > 1.1。
- RSI14 < 75。
- MACD 多头。
- 连续 5 日上涨。

仓位解释：

- 原表格权重解释为“策略桶内权重”，再乘以 `SOXL/SOXX` 桶上限 30%。
- 强繁荣：SOXX 40% + SOXL 60%，映射为全盘 `SOXX 12% + SOXL 18%`。
- 弱繁荣：SOXX 50% + SOXL 50%，映射为全盘 `SOXX 15% + SOXL 15%`。
- 震荡周期：SOXX 100% + SOXL 0%，映射为全盘 `SOXX 30%`。
- 衰退周期：SOXX 30% + SOXL 0%，映射为全盘 `SOXX 9%`。

逃顶/风控：

- SOXX 跌破 EMA50 且 3 日未收回：进入 `DECLINE`。
- 高开低走大 K 线 + 成交量放大 2 倍：进入风险预警。
- VIX > 30：进入风险预警。
- PE 分位 > 80% 作为规则说明保留，但当前未接入真实 PE 分位数据，不做硬触发。

### 4. 后验 P/L 支持多标的分配

文件：

- `src/hermes_escape_top/core/backtest/posterior.py`

改造：

- `mirror_posterior_pnl()` 支持 `allocations` 聚合。
- 多标的组合时，按每个标的目标权重分别计算上一交易日 P/L，再合并成一条策略桶 P/L。

### 5. Pipeline 接线

文件：

- `src/hermes_escape_top/pipeline.py`

改造：

- `build_mirror_plan(snapshots, config, histories=histories, as_of=as_of)`。
- 让镜像策略能使用真实历史序列计算量能、涨幅、连续上涨与相对强弱。

### 6. 8768 WebUI 更新

文件：

- `src/hermes_escape_top/web/mirror_render.py`

改造：

- 页面只展示两套策略：
  - `QQQ / FNGU 双轮驱动`
  - `SOXX / SOXL 半导体`
- 每个策略卡新增：
  - 主动作。
  - 理想总资金。
  - 策略桶上限。
  - 分标的目标金额、参考价、建议股数。
  - 雷达数据。
  - 规则检查。
  - 止损止盈与禁令。
- 总目标仓位动态来自当前决策，不再固定写死 65%。

## 当前真实数据输出

默认 `as_of=2026-06-02`，刷新 8768 后结果：

| 策略桶 | 周期 | 主动作 | 全盘目标 | 分配 |
|---|---|---|---:|---|
| FNGU_QQQ | CHOP | QQQ | 16.0% | QQQ 16.0% |
| SOXL_SOXX | CHOP | SOXX | 30.0% | SOXX 30.0% |

解释：

- 当前规则判定为震荡/动能不足。
- 两套策略均清杠杆 ETF，只保留底层 ETF。
- 镜像总目标仓位为 50.0%。

## 验收

### 编译

```bash
python3 -m py_compile \
  src/hermes_escape_top/mirror/strategy.py \
  src/hermes_escape_top/core/backtest/posterior.py \
  src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/web/mirror_render.py \
  src/hermes_escape_top/tests/test_phase12_mirror.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：通过。

### 镜像单测

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase12_mirror.py \
  src/hermes_escape_top/tests/test_mirror_web.py
```

结果：`Ran 5 tests ... OK`

### Web/镜像集成测试

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_phase12_mirror.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py
```

结果：`Ran 11 tests ... OK`

### 真实页面快照

```bash
PYTHONPATH=src python3 -m hermes_escape_top.cli \
  mirror-dashboard --as-of 2026-06-02 --output /tmp/hermes_mirror_new_rules.html
```

确认包含：

- `QQQ / FNGU 双轮驱动`
- `SOXX / SOXL 半导体`
- `规则检查`
- `止损止盈与禁令`
- `理想化持仓配比`

### 8768 服务验收

服务：

- `http://localhost:8768/`
- screen session：`hermes-mirror-8768`

健康检查：

```json
{"ok":true,"app":"mirror"}
```

刷新接口：

```text
FNGU_QQQ CHOP QQQ 0.16 {'QQQ': 0.16}
SOXL_SOXX CHOP SOXX 0.3 {'SOXX': 0.3}
```

浏览器验收：

- 页面顶部显示 `Mirror target 50.0%`。
- 第一张卡为 `QQQ / FNGU 双轮驱动`，状态 `CHOP`，主动作 `QQQ`。
- 第二张卡为 `SOXX / SOXL 半导体`。
- 规则检查和止损止盈折叠区可见。

## 同步情况

已同步到本地运行目录：

- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/mirror/strategy.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/core/backtest/posterior.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/pipeline.py`
- `/Users/liweishi/.hermes/skills/investment/escape-top/hermes_escape_top/web/mirror_render.py`

## 剩余风险

- PE 分位尚未接入真实数据，当前只作为纪律说明，不参与硬触发。
- 单笔亏损、持仓天数、分批止盈需要真实交易批次/成本/建仓时间数据库支持；当前 WebUI 已展示纪律，但不做自动计算。
- 当前 IBKR 来源仍为 snapshot；若 Gateway/TWS 在线，点击“更新持仓”会尝试同步最新持仓。

