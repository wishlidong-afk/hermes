# 2026-07-01 IBKR 轻量刷新外部审计方法

## 背景

本批修复目标：`/api/refresh_positions` 只刷新外部 IBKR 持仓层，不再重抓行情、不再运行 `score_pipeline`、不再生成 `manual_rerun` preview，也不覆盖当天官方策略记录。

IBKR stale 已被产品上接受为“外部持仓陈旧，不阻断策略评分”。因此这次按钮只负责让 WebUI 的持仓/对账层拿到最新只读快照。

## 应有行为

1. 点击“更新持仓”：
   - 读取 IBKR/TWS 或本地 positions cache。
   - 用当前官方 payload 的 `sizing` / `routing` 做 reconcile。
   - 写 `ibkr_snapshots` 和 `ibkr_position_overlay.json`。
   - 返回 fresh `ibkr` block。

2. 点击“更新持仓”不得：
   - 调用 `_score_pipeline_locked`。
   - 调用 `backfill_history` 或刷新 OHLCV。
   - 写 `audit_log.jsonl` 的新策略记录。
   - 写 `run_receipt.json`。
   - 生成第二份官方 run 或 `manual_rerun` preview。

3. 默认 dashboard：
   - 策略头条仍来自 official scheduled run。
   - 若 overlay 的 `as_of` 和 `base_input_hash` 与当前官方 payload 匹配，则把 `payload.ibkr` 替换为 overlay 内的新持仓对账。
   - 下一次官方 run 改变 `input_hash` 后，旧 overlay 自动失效。

## 代码审计点

1. 路由接线：
   - `src/hermes_escape_top/web/server.py`
   - `src/hermes_escape_top/web/mirror_server.py`
   - `/api/refresh_positions` 应传 `base_payload=_latest_score_payload(...)`。
   - 默认页和 `/api/score` 应调用 `apply_ibkr_position_overlay(...)`。

2. 轻量刷新实现：
   - `src/hermes_escape_top/web/refresh.py`
   - `refresh_positions_only(...)` 内不得调用 `_score_pipeline_locked`。
   - `refresh_positions_only(...)` 内不得调用 `backfill(...)`。
   - 应写 `IBKR_POSITION_OVERLAY = "ibkr_position_overlay.json"`。

3. State 写面：
   - `src/hermes_escape_top/core/data/state_store.py`
   - `write_ibkr_snapshot(...)` 只插入 `ibkr_snapshots`。
   - retention 只修剪 `ibkr_snapshots`，不得修剪 `score_runs`。

4. UI 行为：
   - `src/hermes_escape_top/web/render.py`
   - `src/hermes_escape_top/web/mirror_render.py`
   - `refreshPositions()` 成功后不应带 `view=preview`。
   - 文案应明确“不重抓行情、不重算官方策略”。

## 推荐命令

```bash
cd /Users/liweishi/Documents/github/hermes

# 1. 静态查调用面
rg -n "def refresh_positions_only|/api/refresh_positions|apply_ibkr_position_overlay|_score_pipeline_locked|backfill\\(" \
  src/hermes_escape_top/web src/hermes_escape_top/core/data/state_store.py

# 2. 关键测试
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_refresh_as_of_gating.py \
  src/hermes_escape_top/tests/test_phase14_web.py \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py \
  src/hermes_escape_top/tests/test_state_store_and_actions.py \
  -q

# 3. 全套件
PYTHONPATH=src:src/hermes_escape_top/tests /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

## Runtime 审计步骤

在 staging 或 live 部署后执行：

```bash
ARCHIVE=/Users/liweishi/.hermes/skills/investment/escape-top/shared/hermes_escape_top/data/archive

before_audit_size=$(wc -c < "$ARCHIVE/audit_log.jsonl")
before_receipt_mtime=$(stat -f %m "$ARCHIVE/run_receipt.json")

curl -s -X POST \
  -H 'Host: 127.0.0.1:8766' \
  -H 'Content-Type: application/json' \
  --data '{"as_of":"latest"}' \
  http://127.0.0.1:8766/api/refresh_positions \
  | tee /tmp/ibkr_refresh_positions.json

after_audit_size=$(wc -c < "$ARCHIVE/audit_log.jsonl")
after_receipt_mtime=$(stat -f %m "$ARCHIVE/run_receipt.json")

echo "audit_size: $before_audit_size -> $after_audit_size"
echo "receipt_mtime: $before_receipt_mtime -> $after_receipt_mtime"
python - <<'PY'
import json
p=json.load(open("/tmp/ibkr_refresh_positions.json"))
print("source=", (p.get("ibkr") or {}).get("source"))
print("refresh_status=", p.get("ibkr_refresh_status"))
assert (p.get("ibkr_refresh_status") or {}).get("score_pipeline") is False
assert (p.get("ibkr_refresh_status") or {}).get("history_refreshed") is False
assert (p.get("ibkr_refresh_status") or {}).get("official_run_written") is False
PY
```

期望：

- `audit_size` 不变。
- `run_receipt.json` mtime 不变。
- `$ARCHIVE/ibkr_position_overlay.json` 存在。
- `/api/refresh_positions` 返回 `ibkr_refresh_status.score_pipeline=false`。
- 8766 默认页仍显示官方 run，不出现“非官方 · 你在看”。

## 失败信号

任一项出现都应判失败：

- 点击“更新持仓”后出现 `view=preview`。
- `audit_log.jsonl` 增长。
- `run_receipt.json` 更新时间变化。
- `ibkr_refresh_status.score_pipeline=true` 或字段缺失。
- `score_runs` 增加但没有执行完整策略刷新授权。
- dashboard 策略头条因持仓刷新改变。

## 已知边界

- 本修复不解决 TWS/Gateway 自身未开启、账号断连或 IBKR API 超时。
- 若 IBKR 返回 snapshot 而非 `source=tws`，WebUI 仍应显示“未连接 live / 沿用快照”。
- overlay 只对同一个 `as_of` 且同一个 `input_hash` 的官方 payload 生效；下一次 official run 后需要重新刷新持仓。
