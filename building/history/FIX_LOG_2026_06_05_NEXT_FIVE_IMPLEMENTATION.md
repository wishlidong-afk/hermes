# FIX LOG 2026-06-05：下一组 5 项验收实现

## 背景

本轮按 `ACCEPTANCE_TARGETS_2026_06_05_NEXT_FIVE.md` 执行 5 项继续搭建任务：

1. IBKR executions 自动确认 T1/T2/T3
2. `/api/confirm_execution` token 保护
3. Pipeline 测试隔离
4. State DB retention
5. Factor explain registry

核心边界：IBKR 仍然只读；自动确认只读取成交并写入本地确认状态，不下单。

## 实现 Milestone

### M1. 验收目标文档

- 新增 `building/ACCEPTANCE_TARGETS_2026_06_05_NEXT_FIVE.md`
- 明确每项验收目标、统一测试命令和 payload/WebUI 可观测字段。

验收状态：完成。

### M2. IBKR executions 只读适配器与自动确认

新增：

- `src/hermes_escape_top/ibkr/executions.py`
- `src/hermes_escape_top/core/reentry/auto_confirm.py`

改动：

- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/core/data/state_store.py`
- `src/hermes_escape_top/config/config.json`

能力：

- read-only 读取 IBKR recent executions。
- 断线时降级读取 `executions_cache.json`，并标记 `source=snapshot/unavailable`。
- 只在 `ibkr.source=tws` 且 executions source 在 `auto_confirm_sources` 里时自动写入确认。
- 当前默认 `auto_confirm_sources=["tws"]`，不会用陈旧 cache 自动推进 T1/T2/T3。
- 只匹配 BUY/BOT 成交，且当前 reentry plan 必须为 eligible 的 T1/T2/T3。
- 写入 `execution_confirmations` 时使用 `external_key` 去重，重复刷新不会无限追加。
- payload 新增 `execution_sync`，并在 `reentry_state.execution_confirmations` 中展示最新确认。

验收状态：完成。

### M3. `/api/confirm_execution` token 保护

改动：

- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/config/config.json`

能力：

- 若环境变量 `HERMES_CONFIRM_TOKEN` 或 config token 存在，则必须校验。
- 支持 `X-Hermes-Token` header 或 JSON body `token`。
- 错误 token 返回：
  - `ok=false`
  - `status=UNAUTHORIZED`
  - `message=missing or invalid confirm token`
- 未配置 token 时保持 localhost 开发可用，响应带 `auth_status=NO_TOKEN_CONFIGURED_LOCAL_ONLY`。
- 错误 token 单测断言 `record_execution_confirmation` 没有被调用。

验收状态：完成。

### M4. Pipeline 测试隔离

改动：

- `src/hermes_escape_top/tests/test_state_store_and_actions.py`

能力：

- 对会写 state DB 的 pipeline 测试生成临时 config。
- `archive_dir` 指向 `TemporaryDirectory`。
- 测试断言 state DB 路径在临时目录内。
- 避免单元测试继续污染 repo 内 `data/archive/hermes_state.sqlite`。

验收状态：完成。

### M5. State DB retention

改动：

- `src/hermes_escape_top/core/data/state_store.py`
- `src/hermes_escape_top/web/refresh.py`
- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/config/config.json`

能力：

- 默认保留策略：
  - `score_runs=500`
  - `refresh_runs=200`
  - `ibkr_snapshots=200`
  - `calibration_logs=1000`
  - `execution_confirmations=500`
- 删除旧 `score_runs` 时同步清理：
  - `decisions`
  - `factor_values`
  - `data_sources`
  - `posterior_pnl`
  - `reentry_states`
- `write_state_snapshot` 与 `write_refresh_run` 都会应用 retention。
- 单测使用小阈值验证只保留最新 run，且 child rows 同步裁剪。

验收状态：完成。

### M6. Factor explain registry

新增：

- `src/hermes_escape_top/core/scoring/explain_registry.py`
- `src/hermes_escape_top/tests/test_factor_explain_registry.py`

改动：

- `src/hermes_escape_top/core/scoring/registry.py`
- `src/hermes_escape_top/web/render.py`

能力：

- 当前 A/B/C/D 核心 factor id 均有固定解释。
- 每个 factor score dict 追加：
  - `professional_explain`
  - `plain_explain`
  - `data_hint`
- 未登记因子按模块 fallback，不会导致评分失败。
- WebUI 的宏观 A 模块和关键触发项 drilldown 展示专业解释、白话解释、数据提示。

验收状态：完成。

### M7. 8766 WebUI 运行态修复

发现：

- 当前 8766 原先跑的是 `~/.hermes/skills/investment/escape-top` 安装版代码，不是 GitHub repo 当前代码。
- 因此页面一开始看不到新增解释字段。

处理：

- 新增 `scripts/serve_escape_8766_repo.sh` 用当前 repo 启动 8766。
- 使用 detached `screen` 托管服务：

```bash
screen -dmS hermes_escape_8766_repo /bin/bash /Users/liweishi/Documents/github/hermes/scripts/serve_escape_8766_repo.sh
```

当前检查：

- `http://localhost:8766/health` 返回 `{"ok":true}`
- 页面标题为 `Hermes Escape Top / Hermes 逃顶驾驶舱`
- 3 个策略卡正常显示
- 页面能看到：
  - `宏观 A 模块评分`
  - `POST /api/confirm_execution`
  - `白话`
  - `数据：`

验收状态：完成。

## 验证命令

```bash
python3 -m py_compile \
  src/hermes_escape_top/pipeline.py \
  src/hermes_escape_top/core/data/state_store.py \
  src/hermes_escape_top/web/server.py \
  src/hermes_escape_top/web/refresh.py \
  src/hermes_escape_top/core/scoring/registry.py \
  src/hermes_escape_top/core/scoring/explain_registry.py \
  src/hermes_escape_top/ibkr/executions.py \
  src/hermes_escape_top/core/reentry/auto_confirm.py \
  src/hermes_escape_top/tests/test_state_store_and_actions.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_factor_explain_registry.py

PYTHONPATH=src python3 -m unittest \
  src.hermes_escape_top.tests.test_state_store_and_actions \
  src.hermes_escape_top.tests.test_phase15_integration \
  src.hermes_escape_top.tests.test_factor_explain_registry

PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests
```

结果：

- 相关测试：18 tests OK
- 全量测试：343 tests OK
- Browser 冒烟：通过

## 剩余风险

- IBKR executions 自动确认依赖 Gateway/TWS 能返回 execution history；不同 IBKR 账户权限和时间过滤可能存在差异，实盘第一次应观察 `execution_sync.executions.error`。
- 当前自动确认只从 `source=tws` 写库，不会用 snapshot 自动推进，这牺牲了一点离线便利性，但避免陈旧成交误推进 T1/T2/T3。
- 8766 现在由 `screen` 会话 `hermes_escape_8766_repo` 托管；若机器重启，需要重新执行 `scripts/serve_escape_8766_repo.sh` 或把它做成正式 LaunchAgent。
- `src/hermes_escape_top/data/archive/flow_reference.sqlite` 是既有运行缓存脏文件，本轮未纳入提交。
