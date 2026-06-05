# ACCEPTANCE TARGETS 2026-06-05：下一组 5 项任务

## 总原则

- IBKR 仍然只读，绝不下单。
- 自动 T1/T2/T3 的含义是自动读取成交记录并写入确认状态，不是自动买卖。
- 所有新增能力必须能测试、能落库、能在 WebUI 或 payload 里看见。

## 1. IBKR executions 自动确认 T1/T2/T3

验收目标：

- 新增只读 executions adapter，能从 IBKR live 读取最近成交；断线时降级到本地 snapshot。
- 成交记录包含 `exec_id / symbol / side / shares / price / time / account / source`。
- 当当前 reentry plan 为 `T1/T2/T3` 且发现对应标的近期 BUY 成交时，自动写入 `execution_confirmations`。
- 自动确认必须去重，重复刷新不得无限追加同一笔成交确认。
- payload 中展示 `execution_sync`，包括 source、status、matched confirmations、inserted/skipped。
- WebUI 仍显示确认状态，且来源可区分 `manual_web` 与 `ibkr_executions`。

## 2. `/api/confirm_execution` token 保护

验收目标：

- 若配置或环境变量提供 token，则 `/api/confirm_execution` 必须校验。
- token 可从 `X-Hermes-Token` header 或 JSON body 的 `token` 传入。
- 错误 token 返回 JSON：`ok=false`、`status=UNAUTHORIZED`，不得写库。
- 若未配置 token，则保持 localhost 本地开发可用，但日志/响应要明确这是本地无 token 模式。

## 3. Pipeline 测试隔离

验收目标：

- 新增/修改的 pipeline 测试不得写 repo 里的 `data/archive/hermes_state.sqlite`。
- 测试应使用临时 archive dir，并断言 state db 位于 temp 目录。
- 测试结束后 repo 只允许出现运行刷新导致的缓存变动，不应由单元测试制造主库污染。

## 4. 状态库 retention

验收目标：

- 新增 retention 函数，能限制 `score_runs / refresh_runs / ibkr_snapshots / calibration_logs / execution_confirmations` 保留数量。
- 删除旧 `score_runs` 时，关联的 `decisions / factor_values / data_sources / posterior_pnl / reentry_states` 必须同步清理。
- 默认 retention 不影响日常运行；测试可以用很小阈值验证清理。
- retention 操作不删除最新 run。

## 5. Factor explain registry

验收目标：

- 新增 factor 解释字典，至少覆盖当前 A/B/C/D 核心 factor id。
- 每个 factor score dict 追加：
  - `professional_explain`
  - `plain_explain`
  - `data_hint`
- WebUI drilldown 能显示通俗解释，不再只显示计算字符串。
- 未登记的 factor 必须有安全 fallback，不导致评分失败。

## 统一验收命令

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
```

通过标准：全量测试 OK，8766/8768 健康检查 OK，刷新 payload 中能看到 `execution_sync`、`ibkr_history`、`calibration_history`。
