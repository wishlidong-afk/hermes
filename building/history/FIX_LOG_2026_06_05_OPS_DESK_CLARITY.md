# FIX LOG 2026-06-05：今日操作台可执行表述优化

## 目标

用户反馈：今日操作台三个策略卡片仍然不够清楚，需要直接说明怎么操作、买卖多少股、占总资产多少。

## 改动

- `action_intents` 新增 `trade_plan`：
  - 每个策略袖套拆成 `risk` 风险腿和 `defense_route` 防守去向腿。
  - 每条腿包含目标占总资产比例、目标金额、参考价、目标股数。
- 今日操作台三张卡重写为调仓单：
  - 明确区分“系统裁决”和“实际调仓”。
  - 显示实际买入/卖出方向、股数、金额、占总资产比例。
  - 显示表格列：腿、目标占比/金额、目标股数、当前 IBKR、差额动作。
  - 对 BOXX 等共享防守腿按目标权重比例分摊当前持仓，避免重复计算。
- `.gitignore` 增补运行缓存：
  - `src/data/executions_cache.json`
  - `src/hermes_escape_top/data/archive/live_checks/`

## 验收

命令：

```bash
python3 -m py_compile src/hermes_escape_top/core/decision/action_intents.py src/hermes_escape_top/web/render.py
PYTHONPATH=src python3 -m unittest src.hermes_escape_top.tests.test_phase14_web src.hermes_escape_top.tests.test_phase15_integration
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests
```

结果：

- 相关测试：11 tests OK
- 全量测试：343 tests OK
- 8766 已重启，`/health` OK
- Browser 检查确认今日操作台包含：
  - `系统裁决`
  - `实际调仓`
  - `占总资产`
  - `当前IBKR`
  - 每个策略卡 1 张差额动作表

## 当前页面效果示例

- MSTR：系统裁决清仓并路由，实际调仓显示买入 BOXX 约 110 股，占总资产约 15%。
- FNGU：系统裁决持有/维持，实际调仓显示买入 FNGU 到目标比例。
- SOXL：系统裁决减仓并路由，实际调仓显示 SOXL 与 BOXX 各自目标股数和目标占比。

说明：系统裁决不是交易方向；交易方向按“当前 IBKR 持仓 → 目标仓位”的差额计算。
