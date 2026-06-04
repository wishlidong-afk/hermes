# Fix Log — 2026-06-04 src 同步与 review 修复

## 背景

上一轮逐行审查发现 GitHub `src/hermes_escape_top` 与本地完整实现
`~/.hermes/skills/investment/escape-top/hermes_escape_top` 存在事实源分裂：

- GitHub `src` 只有部分模块，`hermes_escape_top.pipeline` 无法独立 import。
- SizingOptimizer 的 CVaR 正态分位实现使用了不存在的 `math.erfinv`。
- E12 流动性 cap 把美元 ADV 又乘了一次价格。
- P10 已批准的相关性参数 `threshold=110 / penalty=0.90` 没有进入 GitHub 默认配置。
- sizing 配置字段与 optimizer 实际读取字段不一致。
- 本地旧逃顶 UI 和镜像 UI 都默认抢 `8766`，互链端口也错位。

## 修复内容

### 1. GitHub `src` 补齐成本地可运行包

从本地 `.hermes` 完整包迁移缺失模块到 GitHub `src/hermes_escape_top`：

- `config.py` 与 `config/config.json`
- `core/data/*`
- `core/scoring/*`
- `core/decision/*`
- `core/routing/capital_routing.py`
- `core/reentry/plan.py`
- `mirror/*`
- `ibkr/*`
- backtest/replay/posterior/reporting 模块
- package tests
- 必要离线历史 fixture：`data/history/*.csv`
- 必要软数据历史 fixture：`data/soft_history/*.csv`
- `data/archive/data_manifest_latest.json`

结果：GitHub `src` 不再依赖本机 `.hermes` 才能 import pipeline。

### 2. RiskEngine 分位数修复

文件：`src/hermes_escape_top/core/portfolio/risk_engine.py`

- 将 Cornish-Fisher 分位数从 `math.erfinv` 改为 `statistics.NormalDist().inv_cdf()`。
- 对 `p` 做 `[1e-9, 1-1e-9]` clamp，避免边界概率炸掉。

### 3. SizingOptimizer 修复

文件：`src/hermes_escape_top/core/portfolio/sizing_optimizer.py`

- 引入本地更新版 optimizer。
- Kelly 默认关闭，必须显式配置 `kelly.enabled=True` 且提供校准后的 `kelly.p_act` 才能启用。
- 删除冗余 normal-CVaR solver 约束，CVaR 由 RiskState 的历史模拟 scaler 进入 upper bounds。
- E12 liquidity cap 拆成：
  - `adv20_shares`
  - `adv20_notional`
- 防止美元 ADV 被再次乘以价格。
- grid fallback 泛化到任意维度，避免只适配 3-leg 的隐性假设。

### 4. Pipeline 配置与 confidence 修复

文件：`src/hermes_escape_top/pipeline.py`

- `_optimize_sizing` 现在传入：
  - `leg_returns`
  - `liquidity_data`
  - `as_of`
  - `signal_journal_path`
- 流动性数据同时输出 `adv20_shares` 和 `adv20_notional`。
- 新增 `_risk_engine_config()`，把旧 `portfolio.corr_regime_pct` 规范化为 RiskEngine 当前 schema。
- 新增 `_sizing_optimizer_config()`，把 legacy flat sizing 字段规范化为 optimizer 实际读取的 nested schema。
- ConfidenceSpine 改为读取真实：
  - missing-weight data confidence
  - history staleness
  - signal journal PSI drift
- optimizer fallback 不再静默，触发 `RuntimeWarning`，并尝试写入 fallback decision 的 `explain`。
- posterior PnL 的 `portfolio_value` 从配置读取 `portfolio.netliq` 或 `initial_capital`，不再硬编码唯一来源。
- 加入本地已有的 read-only IBKR reconciliation payload 降级逻辑。

### 5. 默认参数对齐 P10

文件：

- `src/hermes_escape_top/integration_config.py`
- `src/hermes_escape_top/config/config.json`

更新：

- `corr_regime_extreme_ratio = 110`
- `corr_regime_elevated_ratio = 80`
- `extreme_corr_penalty = 0.90`
- sizing schema 改为 optimizer 实际读取结构：
  - `kelly.enabled = false`
  - `kelly.frac = 0.30`
  - `liquidity.max_liquidation_days = 3`
  - `liquidity.participation_rate = 0.10`
  - `mu_mode = proxy`

### 6. 旧 WebUI 本地端口修复

本地文件：

- `~/.hermes/scripts/mirror_reference_web.py`
- `~/.hermes/scripts/start_mirror_reference_monitor.sh`
- `~/.hermes/web/mirror_reference/index.html`
- `~/.hermes/web/escape_top_strategy/index.html`

结果：

- 旧逃顶 UI 保持 `8766`
- 镜像参考 UI 改为 `8767`
- 两个页面互链同步为：
  - 逃顶 -> `http://127.0.0.1:8767/`
  - 镜像 -> `http://127.0.0.1:8766/`

## 验证结果

### import / compile

```bash
PYTHONPATH=src python3 - <<'PY'
from hermes_escape_top.pipeline import score_pipeline
from hermes_escape_top.config import load_config
print('top-pipeline-import-ok', callable(score_pipeline))
print(load_config()['version'])
PY
```

结果：通过。

```bash
PYTHONPATH=src python3 -m compileall -q src/hermes_escape_top
```

结果：通过。

### targeted tests

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_sizing_optimizer.py \
  src/hermes_escape_top/tests/test_risk_engine.py \
  src/hermes_escape_top/tests/test_pipeline.py
```

结果：

```text
Ran 49 tests in 1.389s
OK
```

### full package tests

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 311 tests in 42.454s
OK
```

备注：测试期间 IBKR gateway 未连接，read-only fallback 测试会打印连接拒绝提示；最终测试仍通过。

## 剩余注意事项

- 当前同步了必要 `data/history` fixture，未把本地 353MB 全量 archive 全部塞进 GitHub。
- `pytest` 命令在本机不可用，所以验证使用 Python 标准库 `unittest`。
- 本地旧 WebUI 修改在 `~/.hermes`，不属于 GitHub repo 跟踪文件；本 fixlog 记录了线下改动，后续若需要可把 UI 脚本纳入 GitHub 的正式运维目录。
