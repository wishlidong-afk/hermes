# PLAN REVIEW AND REPAIR 2026-06-05：十项优化对照复盘

## 结论

对照 `building/OPTIMIZATION_PLAN_2026_06_05_ALL_TEN.md` 逐项 review 后，第一次实现已经覆盖了主干，但仍有四个不完整点：

1. 主库 schema 没有独立 `reentry_states` 表。
2. 刷新审计只有 history/score/flow/IBKR，未显式拆出 soft data、audit write、Web payload。
3. `execution_confirmations` 只有表和读取，没有写入接口。
4. 后验校准写了库，但 WebUI 没有展示最近历史。

本轮已全部补齐，并重新通过测试与 8766/8768 运行态验收。

## 十项计划对照验收

| # | 计划项 | 本轮状态 | 证据 |
|---:|---|---|---|
| 1 | 统一主数据库 `hermes_state.sqlite` | DONE | `state_store.py` 写入 score/decision/factor/source/posterior/calibration/reentry/IBKR/confirmation。 |
| 2 | 数据质量可解释面板 | DONE | `data_quality_breakdown` + WebUI source freshness/upgrade-to-HIGH 展示。 |
| 3 | 全链路刷新审计 | DONE | `refresh_runs.steps` 现在包含 `history_refresh / score_pipeline / soft_data_snapshot / flow_snapshot / ibkr_snapshot / audit_write / web_payload`。 |
| 4 | IBKR 快照机制升级 | DONE | `ibkr_snapshots` 持久化，payload/WebUI 显示最近 5 条快照。 |
| 5 | 评分、硬阀门、置信度三权分离 | DONE | `decision_layers` 输出 `risk_temperature / hard_valve_state / action_confidence`。 |
| 6 | 每标的唯一处置指令 | DONE | `action_intents` 输出 action/target/notional/shares/reasons/invalidation。 |
| 7 | T1/T2/T3 与成交确认解耦 | DONE | 新增 `record_execution_confirmation` 与 `/api/confirm_execution`，WebUI 显示确认入口与最近确认。 |
| 8 | 后验校准自动化 | DONE | `calibration_logs` + `calibration_history`，逃顶/镜像页展示最近校准历史。 |
| 9 | WebUI 今日操作台 | DONE | 8766 顶部操作台显示状态库 run、资金去向、三张动作卡。 |
| 10 | 指标框 drilldown 解释 | DONE / 可继续增强 | 核心模块已有 details；后续可把每个 factor id 统一接到解释字典。 |

## 本轮修复明细

| 文件 | 行号 | 修复 |
|---|---:|---|
| `src/hermes_escape_top/core/data/state_store.py` | 11 | `write_state_snapshot` 现在同时写 reentry 状态，并把 `ibkr_history`、`calibration_history` 回填到 payload。 |
| `src/hermes_escape_top/core/data/state_store.py` | 81 | 新增 `record_execution_confirmation`，用于手工/未来 IBKR executions 确认。 |
| `src/hermes_escape_top/core/data/state_store.py` | 162 | 新增 `recent_ibkr_snapshots`。 |
| `src/hermes_escape_top/core/data/state_store.py` | 170 | 新增 `recent_calibration_logs`。 |
| `src/hermes_escape_top/core/data/state_store.py` | 343 | 新增 `_insert_reentry_states`，将建议阶段、T1/T2 状态、确认状态写入主库。 |
| `src/hermes_escape_top/core/data/state_store.py` | 592 | 新增 `reentry_states` 表与索引。 |
| `src/hermes_escape_top/web/refresh.py` | 18 | 刷新函数新增 7 段步骤审计，并输出总状态 `OK/DEGRADED`。 |
| `src/hermes_escape_top/web/server.py` | 413 | 新增 `/api/confirm_execution`，只记录确认，不下单。 |
| `src/hermes_escape_top/web/render.py` | 657 | 逃顶页 IBKR 面板新增最近快照表。 |
| `src/hermes_escape_top/web/render.py` | 732 | 逃顶页后验模块新增最近模型校准记录。 |
| `src/hermes_escape_top/web/mirror_render.py` | 407 | 镜像页 IBKR 面板新增最近快照表。 |
| `src/hermes_escape_top/web/mirror_render.py` | 510 | 镜像页模型校准模块新增最近镜像校准记录。 |
| `src/hermes_escape_top/tests/test_state_store_and_actions.py` | 13 | 新增状态库、校准历史、执行确认测试。 |
| `src/hermes_escape_top/tests/test_phase15_integration.py` | 111 | 新增 `/api/confirm_execution` HTTP 级测试。 |

## 逐段 Review 结论

### `state_store.py`

- `write_state_snapshot`：职责清晰，仍然是唯一状态库写入口；会先插入本次 run，再回填 payload，保证 audit cache 也带 state/history。
- `record_execution_confirmation`：只写确认，不触发订单；缺 symbol/tranche 会抛错，由 Web 层返回 `ok=false`。
- `_insert_reentry_states`：只做快照，不推进状态机；避免“建议阶段”和“真实成交阶段”混淆。
- `_recent_ibkr_snapshots_conn` / `_recent_calibration_logs_conn`：只读最近记录，限制行数，避免 Web payload 过大。
- 风险：SQLite 表只有追加，没有 retention；后续应增加归档/清理策略。

### `web/refresh.py`

- 刷新链路已按人类可读步骤拆开。
- `DEGRADED` 现在表示“可用但有降级”，不是失败。
- 风险：soft/flow/IBKR 实际都在 `score_pipeline` 内完成，步骤耗时不是严格独立耗时；后续若要精确计时，应把 pipeline 进一步拆出可观测 hooks。

### `web/server.py`

- 新确认接口保持 read-only/advisory 体系：只写 SQLite，不调用 IBKR order API。
- 错误会以 JSON 返回，不让前端收到空响应。
- 风险：确认接口当前没有鉴权。本地 localhost 风险较低，但如果未来开放到局域网，必须加 token。

### `web/render.py`

- 今日操作台、IBKR 最近快照、校准历史、成交确认入口都已经在页面上可见。
- 风险：页面仍是 server-rendered HTML 字符串，长期会越来越大；短期可维护，长期建议拆模板。

### `web/mirror_render.py`

- 镜像页补齐了与逃顶页一致的 IBKR 快照和校准历史。
- 风险：镜像页与逃顶页有重复的 IBKR 表格逻辑，后续可抽一个共用 render helper。

### Tests

- 当前新增测试覆盖：状态库写入、reentry 状态、IBKR 历史、校准历史、确认写入、HTTP 确认接口。
- 风险：部分 pipeline 测试仍会写本地 archive DB，属于历史结构遗留；后续应把 config path 完整临时化，减少测试副作用。

## 验收结果

### 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

结果：

```text
Ran 335 tests in 68.197s
OK
```

### 运行态接口

| 端口 | 检查 | 结果 |
|---|---|---|
| 8766 | `/health` | `{"ok":true}` |
| 8768 | `/health` | `{"ok":true,"app":"mirror"}` |
| 8766 | `POST /api/refresh_score` | 7 步审计 OK，`ibkr_history=5`，`calibration_history=12` |
| 8768 | `POST /api/refresh_score` | 7 步审计 OK，`ibkr_history=5`，`calibration_history=12` |
| 8766 | `/api/confirm_execution` | 验收写入成功后已删除 dry-run 记录，避免污染真实状态 |

当前刷新总状态仍为 `DEGRADED`，原因是 IBKR 为 `snapshot/stale`。这符合系统设计：不是隐藏失败，而是明确提示数据降级。

## 后续优化建议

1. **IBKR execution adapter**：接 `reqExecutions` 或 activity statement，把成交确认从手动接口升级成自动同步。
2. **接口鉴权**：如果 8766/8768 未来不只在 localhost 使用，给 `/api/confirm_execution` 加本地 token。
3. **测试隔离**：将 pipeline 测试配置全部临时化，避免写入 repo 下 `data/archive/*.sqlite`。
4. **状态库 retention**：增加 `VACUUM`/归档策略，例如只保留最近 180 天 score_runs，历史压缩到 parquet/jsonl。
5. **统一 render helper**：抽出 IBKR 快照表、校准历史表，减少逃顶和镜像页面重复。
6. **数据质量门控更细**：把 `DEGRADED` 分成 `BROKER_DEGRADED / SOFT_DEGRADED / FLOW_DEGRADED`，让用户更快定位问题。
7. **factor explain registry**：建立因子解释字典，让每个 A/B/C/D 指标都能自动生成专业解释和通俗解释。
8. **refresh hooks**：把 `score_pipeline` 拆出可观测子步骤，获得真实耗时而不是事后分类。
