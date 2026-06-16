# FIX_LOG 2026-06-05：十项易用性与准确性优化落地

## 背景

用户要求先输出完整优化 MD 并推送到 GitHub，然后开始修复十个方向。本轮先提交了
`building/OPTIMIZATION_PLAN_2026_06_05_ALL_TEN.md`，随后开始把十项中的关键地基落到代码：

1. 统一状态数据库，避免前端、缓存、IBKR、评分结果互相脱节。
2. 将“评分/硬阀门/动作指令”拆成三层，减少页面里混杂判断。
3. 在 WebUI 顶部加入今日操作台，一屏看到是否需要处置、去向、金额、股数。
4. 数据质量从单一 `MEDIUM/HIGH` 文案升级为来源级拆解。
5. 每次刷新写入 refresh run 审计，明确历史刷新、评分、flow、IBKR 是否跑过。
6. IBKR stale/snapshot 状态进入动作置信度，不再静默当作实时。
7. 后验/理想持仓 PnL 写入统一库，为模型校准留痕。
8. 执行确认表预留，后续可接成交回报/手工确认，避免 T1/T2/T3 凭空推进。
9. WebUI 增强中文解释与通俗解释，点击展开可以看到建议失效条件。
10. 针对路由资产补齐快照 universe，BOXX/BRK.B/QQQ/SOXX 等防守去向也可计算市价股数。

## 代码变更

| 文件 | 变更 |
|---|---|
| `src/hermes_escape_top/core/data/state_store.py` | 新增统一 SQLite 状态库，写入 score runs、decisions、factors、data sources、refresh runs、IBKR snapshots、posterior PnL、calibration logs、execution confirmations。 |
| `src/hermes_escape_top/core/decision/action_intents.py` | 新增用户可执行动作层，生成唯一动作、目标资产、金额、股数、置信度、核心原因、失效条件。 |
| `src/hermes_escape_top/pipeline.py` | 接入状态库、动作意图、数据质量拆解、执行确认读取，并将 BOXX/BRK.B 等路由资产纳入快照。 |
| `src/hermes_escape_top/web/refresh.py` | 刷新链路改为步骤化审计，记录 history/score/flow/IBKR 每一步状态并落库。 |
| `src/hermes_escape_top/web/render.py` | 新增“今日操作台”、数据质量来源明细、每标的动作建议、三层决策解释、执行确认行。 |
| `src/hermes_escape_top/tests/test_state_store_and_actions.py` | 新增状态库与动作层测试。 |
| `.gitignore` | 忽略本地运行生成的 `hermes_state.sqlite`，避免把实时状态缓存误提交。 |

## 验收结果

### 单元测试

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 333 tests in 67.191s
OK
```

### 定向测试

```bash
PYTHONPATH=src python3 -m unittest \
  src/hermes_escape_top/tests/test_state_store_and_actions.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py
```

结果：

```text
Ran 10 tests
OK
```

### 样例评分落库检查

对 `2026-06-04` 跑评分并检查统一库：

| 检查项 | 结果 |
|---|---|
| `score_runs` | 有记录 |
| `decisions` | 有记录 |
| `factor_values` | 有记录 |
| `data_sources` | 有记录 |
| `posterior_pnl` | 有记录 |
| `calibration_logs` | 有记录 |
| `ibkr_snapshots` | 有记录 |
| `execution_confirmations` | 表已存在，当前为空，等待真实成交/手工确认接入 |

样例动作层输出：

| 标的 | 动作 |
|---|---|
| FNGU | `REDUCE_AND_ROUTE` |
| MSTR | `SELL_AND_ROUTE` |
| SOXL | `REDUCE_AND_ROUTE` |

### WebUI 现场验收

| 端口 | 检查项 | 结果 |
|---|---|---|
| `8766` | `/health` | `{"ok":true}` |
| `8768` | `/health` | `{"ok":true,"app":"mirror"}` |
| `8766` | `POST /api/refresh_score` | `as_of=2026-06-04`，`refresh_status=DEGRADED`，`score_run_id=41` |
| `8768` | `POST /api/refresh_score` | `as_of=2026-06-04`，`refresh_status=DEGRADED`，`score_run_id=42` |
| `8766` | 页面顶部操作台 | 已显示 `state_db=hermes_state.sqlite · run=42` |
| `8766` | 今日动作 | MSTR/FNGU/SOXL 三张动作卡正常显示目标资产、金额、股数、置信度 |
| `8768` | 镜像页 | IBKR 总资产、镜像目标仓位、周期判断、建议处置正常显示 |

本次 `DEGRADED` 不是刷新失败，而是 IBKR 当前来源为 `snapshot` 且 `snapshot_stale=True`。系统会继续展示建议，但把动作置信度降级并明确标红，符合“旧数据不能伪装实时”的要求。

## 现场发现并修复的问题

| 问题 | 根因 | 修复 |
|---|---|---|
| `refresh_status.status` 返回为空 | `web/refresh.py` 只写步骤，没有写总状态字段。 | 增加总状态：只要 flow missing、IBKR degraded 或任一步 error，则总状态为 `DEGRADED`。 |
| 页面顶部 `state_db=NA · run=NA` | `pipeline.py` 先写 audit cache，后写 state DB，导致页面读取的 audit payload 没有 state。 | 调整为先写 `write_state_snapshot`，再写 audit cache，使页面和接口使用同一份带状态的 payload。 |
| runtime 启动失败 | Hermes agent venv 缺少 `pandas`。 | 改用本轮测试同款系统 Python 启动 `8766/8768`。 |

## 当前可验收点

- WebUI 不再只显示一个模糊数据置信度，而是能展示来源级拆解：价格、软数据、资金流、IBKR。
- 用户点击策略更新时，刷新链路会写入 `refresh_runs`，可以追踪到底哪一步成功或缺失。
- 每个标的都有独立动作卡：状态、处置动作、目标防守资产、目标金额、参考股数、核心原因、建议失效条件。
- `IBKR source=snapshot/stale` 会降低动作置信度，避免旧持仓快照被当作实时数据。
- `execution_confirmations` 已预留，后续接 IBKR executions 后可让 3-3-4 再建仓与真实成交同步。

## 剩余风险

| 风险 | 说明 | 后续建议 |
|---|---|---|
| IBKR live 不稳定 | 本轮代码能标记 stale/snapshot，但不能修复 Gateway 断线本身。 | 增加 IBKR executions 拉取与人工确认按钮。 |
| 软数据仍有代理/延迟 | PCR 等外部源会被封锁或延迟，当前只能拆解并惩罚。 | 增加备用供应商与源优先级。 |
| 执行确认未接交易回报 | 当前只建表并读取最新确认，未自动写入成交。 | 增加 `/api/confirm_execution` 与 executions adapter。 |
| 真实前端按钮验收仍需重启 runtime | 代码仓库已通过测试，仍需同步 `.hermes` 后重启 8766/8768 做页面验收。 | 本日志后续步骤执行 runtime 同步与接口检查。 |
| runtime 同步方式 | 裸 `rsync --delete` 会覆盖 package 内运行态 data。 | 后续同步应排除 `data/archive/*.sqlite` 和运行时 cache，只同步代码。 |

## 结论

本轮已经把“能看、能更新、能解释、能留痕”的核心地基补上。下一步重点不再是继续堆页面，而是接入真实 execution confirmation、提升软数据源质量，并把模型校准从展示型日志升级为可回测的版本化实验台。
