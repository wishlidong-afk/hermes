# 2026-07-01 R6 原子化部署 + IBKR 轻量刷新外部审计方法

## 审计范围

本文件覆盖两批变更：

1. R6 versioned release：
   - live 目录改为 `releases/<hash>_<stamp>/` + `current` symlink。
   - 部署先 staging smoke，再原子切换 `current`。
   - `previous` 指向上一版。
   - runtime 数据、config、reports、orders 共享，不随代码 release 覆盖。
   - 失败路径应自动 rollback。

2. IBKR 轻量刷新：
   - `/api/refresh_positions` 只刷新外部 IBKR 持仓层。
   - 不重抓行情、不运行 `score_pipeline`、不生成 `manual_rerun` preview、不写官方 run。
   - WebUI 用 overlay 合并最新 IBKR 对账，但策略头条仍来自 official scheduled run。

## 一、R6 原子化部署审计

### 1. 代码审计点

检查：

- `scripts/deploy_to_live.sh`
- `ops/run_daily.sh`
- `ops/serve_dashboard.sh`
- `ops/run_daily.py`
- `ops/verify_live.sh`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/scripts/run_daily_package.py`

关键断言：

- deploy staging 目录必须是 `~/.hermes/skills/investment/escape-top/releases/<hash>_<stamp>/`。
- `current` 必须是 symlink，不能是实体目录。
- `previous` 如存在，也必须是 symlink。
- `current` 切换应使用 `ln -sfn`/临时 symlink + `mv` 这类原子替换方式。
- staging smoke 在 `current` 切换前执行。
- dashboard 在 rsync/stage/switch 前停止，切换后重启。
- deploy 全流程在同一把 `.pipeline.lock` 下执行，不允许 step-by-step 释放再获取。
- `HERMES_RUNTIME_ROOT` 指向 live root，使 release 代码共享 runtime 数据根。
- `data/`、`reports/`、`orders/`、`hermes_escape_top/data`、`hermes_escape_top/config` 在 release 内应是 symlink，不应复制运行态数据本体。
- `.hermes` commit allowlist 应包含 release 代码、`VERSION`、entry scripts、`current`、`previous`、runtime symlink；不应 `git add -A`。

### 2. 静态命令

```bash
cd /Users/liweishi/Documents/github/hermes

rg -n "RELEASES|CURRENT|PREVIOUS|stage_release|switch_current|rollback|HERMES_RUNTIME_ROOT|deploy_git_pathspecs|verify_live" \
  scripts/deploy_to_live.sh ops src/hermes_escape_top

bash -n scripts/deploy_to_live.sh ops/run_daily.sh ops/serve_dashboard.sh ops/verify_live.sh

PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_deploy_to_live.py \
  src/hermes_escape_top/tests/test_ops_entrypoints.py \
  -q
```

### 3. Live 结构审计

```bash
LIVE=/Users/liweishi/.hermes/skills/investment/escape-top
REPO=/Users/liweishi/Documents/github/hermes

readlink "$LIVE/current"
readlink "$LIVE/previous" || true
cat "$LIVE/current/hermes_escape_top/VERSION"
git -C "$REPO" rev-parse --short HEAD

ls -la "$LIVE/current"
ls -la "$LIVE/current/hermes_escape_top"
```

期望：

- `readlink "$LIVE/current"` 输出类似 `releases/<repo_head>_<stamp>`。
- `cat "$LIVE/current/hermes_escape_top/VERSION"` 的 hash 等于 repo HEAD。
- `current/hermes_escape_top/data` 是 symlink。
- `current/hermes_escape_top/config` 是 symlink。
- `current/data`、`current/reports`、`current/orders` 是 symlink。
- legacy `"$LIVE/hermes_escape_top"` 可以存在，但不再是 entrypoint 使用的代码根。

### 4. Dashboard / entrypoint 审计

```bash
curl -s -o /tmp/hermes8766_r6.html -w 'http=%{http_code}\n' http://127.0.0.1:8766/

rg -o "官方 run[^<]*|非官方 · 你在看|as_of=[0-9-]+|Data [A-Z]+|Cache [^< ]+|Regime [A-Z_]+" \
  /tmp/hermes8766_r6.html || true

pgrep -fl '[s]cripts/run_daily|[r]un_daily_package|[m]anual_rerun' || true

git -C /Users/liweishi/.hermes log --oneline -5 -- skills/investment/escape-top/current ':(glob)skills/investment/escape-top/releases/**' bin/run_daily.sh bin/serve_dashboard.sh

git -C /Users/liweishi/.hermes status --short -- \
  skills/investment/escape-top/current \
  skills/investment/escape-top/previous \
  ':(glob)skills/investment/escape-top/releases/**' \
  skills/investment/escape-top/scripts/run_daily.py \
  bin/run_daily.sh \
  bin/serve_dashboard.sh
```

期望：

- 8766 HTTP 200。
- 默认页有 official run 回执。
- 默认页不出现“非官方 · 你在看”。
- 没有正在跑的 daily/manual rerun。
- `.hermes` 对 escape-top deploy allowlist 干净。

注意：`.hermes` 全局可能有其它运行态 dirty 文件，本审计只看 escape-top deploy allowlist。

### 5. Rollback 证据审计

若要做破坏性演练，只能在 staging/测试环境做。生产上不建议为了审计故意触发失败。

测试侧应看：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_deploy_to_live.py::test_rollback_failure_is_loud_and_retains_backup \
  src/hermes_escape_top/tests/test_deploy_to_live.py::test_isolated_success_reaches_single_success_exit \
  -q
```

生产侧如果自然出现 deploy 失败，期望：

- 输出包含 rollback 信息。
- 8766 恢复 200。
- `current` 回到 deploy 前 release。
- `.hermes` 不产生错误成功提交。
- backup tar/目录路径保留在日志中。

## 二、IBKR 轻量刷新审计

### 1. 代码审计点

检查：

- `src/hermes_escape_top/web/refresh.py`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/mirror_server.py`
- `src/hermes_escape_top/web/render.py`
- `src/hermes_escape_top/web/mirror_render.py`
- `src/hermes_escape_top/core/data/state_store.py`

关键断言：

- `/api/refresh_positions` 调用 `refresh_positions_only(..., base_payload=_latest_score_payload(...))`。
- `refresh_positions_only(...)` 内不得调用 `_score_pipeline_locked`。
- `refresh_positions_only(...)` 内不得调用 `backfill(...)`。
- `refresh_positions_only(...)` 写 `ibkr_position_overlay.json`。
- `apply_ibkr_position_overlay(...)` 只在 `as_of` 匹配且 `base_input_hash` 匹配时合并。
- `write_ibkr_snapshot(...)` 只插入/retention `ibkr_snapshots`，不得修剪 `score_runs`。
- `refreshPositions()` 成功后不带 `view=preview`。
- UI 文案明确“不重抓行情、不重算官方策略”。

### 2. 静态命令

```bash
cd /Users/liweishi/Documents/github/hermes

rg -n "def refresh_positions_only|/api/refresh_positions|apply_ibkr_position_overlay|IBKR_POSITION_OVERLAY|_score_pipeline_locked|backfill\\(" \
  src/hermes_escape_top/web src/hermes_escape_top/core/data/state_store.py

PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_refresh_as_of_gating.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_state_store_and_actions.py \
  -q
```

### 3. Runtime 审计步骤

部署后执行：

```bash
ARCHIVE=/Users/liweishi/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive

before_audit_size=$(wc -c < "$ARCHIVE/audit_log.jsonl")
before_receipt_mtime=$(stat -f %m "$ARCHIVE/run_receipt.json")
before_score_runs=$(/Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
import sqlite3
p="/Users/liweishi/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive/hermes_state.sqlite"
with sqlite3.connect(p) as c:
    print(c.execute("select count(*) from score_runs").fetchone()[0])
PY
)

curl -s -X POST \
  -H 'Host: 127.0.0.1:8766' \
  -H 'Content-Type: application/json' \
  --data '{"as_of":"latest"}' \
  http://127.0.0.1:8766/api/refresh_positions \
  | tee /tmp/ibkr_refresh_positions.json

after_audit_size=$(wc -c < "$ARCHIVE/audit_log.jsonl")
after_receipt_mtime=$(stat -f %m "$ARCHIVE/run_receipt.json")
after_score_runs=$(/Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
import sqlite3
p="/Users/liweishi/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive/hermes_state.sqlite"
with sqlite3.connect(p) as c:
    print(c.execute("select count(*) from score_runs").fetchone()[0])
PY
)

echo "audit_size: $before_audit_size -> $after_audit_size"
echo "receipt_mtime: $before_receipt_mtime -> $after_receipt_mtime"
echo "score_runs: $before_score_runs -> $after_score_runs"

/Users/liweishi/.hermes-v3/.venv/bin/python - <<'PY'
import json
p=json.load(open("/tmp/ibkr_refresh_positions.json"))
print("source=", (p.get("ibkr") or {}).get("source"))
print("refresh_status=", p.get("ibkr_refresh_status"))
assert (p.get("ibkr_refresh_status") or {}).get("score_pipeline") is False
assert (p.get("ibkr_refresh_status") or {}).get("history_refreshed") is False
assert (p.get("ibkr_refresh_status") or {}).get("official_run_written") is False
PY

test -f "$ARCHIVE/ibkr_position_overlay.json" && echo overlay_exists
curl -s http://127.0.0.1:8766/ > /tmp/hermes8766_after_ibkr_refresh.html
rg -c "非官方 · 你在看" /tmp/hermes8766_after_ibkr_refresh.html || true
rg -o "官方 run[^<]*|as_of=[0-9-]+|IBKR [^<]*" /tmp/hermes8766_after_ibkr_refresh.html || true
```

期望：

- `audit_size` 不变。
- `run_receipt.json` mtime 不变。
- `score_runs` 数量不变。
- `$ARCHIVE/ibkr_position_overlay.json` 存在。
- `/api/refresh_positions` 返回 `ibkr_refresh_status.score_pipeline=false`。
- `/api/refresh_positions` 返回 `ibkr_refresh_status.history_refreshed=false`。
- `/api/refresh_positions` 返回 `ibkr_refresh_status.official_run_written=false`。
- 8766 默认页仍是 official run，不出现“非官方 · 你在看”。

## 三、全套验证

```bash
cd /Users/liweishi/Documents/github/hermes

/Users/liweishi/.hermes-v3/.venv/bin/python -m py_compile \
  src/hermes_escape_top/web/refresh.py \
  src/hermes_escape_top/web/server.py \
  src/hermes_escape_top/web/mirror_server.py \
  src/hermes_escape_top/core/data/state_store.py

PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

期望当前基线：

- 全套测试绿。
- 允许现有 `Pandas4Warning: Timestamp.utcnow is deprecated`。

## 四、失败信号

任一项出现都应判失败：

- `current` 不是 symlink。
- `current` 指向 hash 与 repo HEAD 不一致。
- release 内 runtime 数据目录是实体目录而非 symlink。
- deploy 失败却打印 `deploy OK`。
- `.hermes` deploy allowlist 有未提交脏项。
- 点击“更新持仓”后出现 `view=preview`。
- 点击“更新持仓”后 `audit_log.jsonl` 增长。
- 点击“更新持仓”后 `run_receipt.json` 更新时间变化。
- 点击“更新持仓”后 `score_runs` 增加。
- `ibkr_refresh_status.score_pipeline` 不是 `false`。
- dashboard 策略头条因持仓刷新改变。

## 五、已知边界

- 本审计不要求 IBKR 必须 live；若 TWS/Gateway 未开，返回 snapshot/disabled 是正确的外部状态。
- IBKR stale 已被接受为外部持仓陈旧，不应阻断策略评分。
- IBKR overlay 只对同 `as_of` 且同 `input_hash` 的官方 payload 生效；下一次 official run 后旧 overlay 自动失效。
- 生产不建议为了验证 rollback 故意破坏 deploy；rollback 行为由 isolated tests 和真实失败日志共同审计。
