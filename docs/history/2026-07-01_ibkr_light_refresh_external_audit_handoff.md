# 2026-07-01 IBKR 轻量刷新外审 Handoff

## 状态

本批代码已在 repo 工作区验证通过，准备作为一个独立 commit 交给外部审计；尚未部署到 live。

验证结果：

- 全套测试：`576 passed, 1 warning`
- 允许的 warning：`Pandas4Warning: Timestamp.utcnow is deprecated`
- `git diff --check`：通过
- 关键 Python 文件 `py_compile`：通过

## 审计对象

这批提交包含两类内容：

1. IBKR 轻量刷新实现与测试。
2. 外部审计方法文档。

R6 原子化部署代码本批不改；合并审计文档只要求外审复核 R6 现状。

## 重点文件

代码：

- `src/hermes_escape_top/web/refresh.py`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/mirror_server.py`
- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/mirror_render.py`
- `src/hermes_escape_top/core/data/state_store.py`

测试：

- `src/hermes_escape_top/tests/test_refresh_as_of_gating.py`
- `src/hermes_escape_top/tests/test_phase14_web.py`
- `src/hermes_escape_top/tests/test_phase15_integration.py`
- `src/hermes_escape_top/tests/test_mirror_web.py`
- `src/hermes_escape_top/tests/test_state_store_and_actions.py`

审计文档：

- `docs/history/2026-07-01_ibkr_light_refresh_external_audit.md`
- `docs/history/2026-07-01_r6_atomic_deploy_and_ibkr_light_refresh_audit.md`

## 必核问题

1. `/api/refresh_positions` 是否真的不再跑 `score_pipeline`？
   - 期望：`refresh_positions_only(...)` 内没有 `_score_pipeline_locked(...)` 调用。

2. `/api/refresh_positions` 是否真的不重抓行情？
   - 期望：该函数内没有 `backfill(...)` 调用。

3. 是否不写官方策略记录？
   - 期望：只写 `ibkr_position_overlay.json` 和 `ibkr_snapshots`，不写 `audit_log.jsonl` / `run_receipt.json` / `score_runs`。

4. overlay 是否严格绑定当前官方 payload？
   - 期望：`apply_ibkr_position_overlay(...)` 只在 `as_of` 匹配，且官方 payload 有 `input_hash` 时 overlay 的 `base_input_hash` 必须相同，才合并。

5. WebUI 是否还会把持仓刷新当成 preview？
   - 期望：`refreshPositions()` 成功后不跳 `view=preview`，并显示“不重抓行情、不重算官方策略”。

6. state retention 是否只影响 IBKR 快照？
   - 期望：`write_ibkr_snapshot(...)` 只修剪 `ibkr_snapshots`，不修剪 `score_runs`。

## 推荐审计命令

```bash
cd /Users/liweishi/Documents/github/hermes

git diff --stat HEAD
git diff --check

rg -n "def refresh_positions_only|apply_ibkr_position_overlay|IBKR_POSITION_OVERLAY|_score_pipeline_locked|backfill\\(" \
  src/hermes_escape_top/web/refresh.py

PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_refresh_as_of_gating.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_state_store_and_actions.py \
  -q

PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

## 部署前门槛

外审通过后再部署。部署前应满足：

- repo clean。
- HEAD 已按需要 push。
- 8766 当前 live 仍 200。
- 无 `run_daily` / `manual_rerun` 进程。
- 时间不在 07:00-07:20 daily 窗口。

部署使用 R6 脚本：

```bash
cd /Users/liweishi/Documents/github/hermes
echo N | bash scripts/deploy_to_live.sh
```

部署后按完整合并审计文档做 runtime 验收：

- `audit_log.jsonl` size 不变。
- `run_receipt.json` mtime 不变。
- `score_runs` 数量不变。
- `ibkr_position_overlay.json` 存在。
- 8766 默认页仍是 official run，无 preview 红条。

## 非本批范围

- 不解决 TWS/Gateway 未开启、IBKR API 超时或 IBKR 返回 snapshot。
- 不给 overlay 加 TTL；目前用 `as_of + input_hash` 防跨 run 串味。
- 不修改 R6 deploy 交互式 config gate。
