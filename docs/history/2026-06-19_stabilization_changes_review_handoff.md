# Hermes R1-R5 稳固变更复审交接

> 日期：2026-06-19
> 用途：交给另一个 agent 做独立代码复审
> repo：`~/Documents/github/hermes`
> 分支：`hermes-docs`
> 未提交基线 HEAD：`3f48dd3`
> live VERSION：`2beea7d 20260618_205923`
> 状态：工作区有意保留未提交变更；**未 commit、未 deploy、未修改 live/launchd/8766**

---

## 1. 请 Reviewer 先读

1. `context.md`
2. `docs/history/2026-06-18_review_remediation.md`
3. `docs/history/2026-06-19_system_stabilization_ab_plan.md`
4. `docs/history/2026-06-19_stabilization_release_review_method.md`
5. `building/reports/runtime_write_path_audit_2026_06_19.md`
6. `building/reports/pipeline_persistence_equivalence_2026_06_19.json`

复审时不要相信本文的自我评价；请从公开入口追到真实写点，并优先构造反例。

---

## 2. 本批目标与不可变式

本批只修稳固性，不修改策略阈值、因子、权重、路由和 flag 部署态。

必须保持：

1. Hermes 只读且永不自动下单；IBKR `readonly=true`。
2. 任意时刻只有一个生产 writer。
3. 不能通过 `lock_held=True`、可选参数或无效 lease 绕过锁。
4. scheduled run 必须是 `RUNNING -> OK/FAILED`，失败不得遗留旧绿回执。
5. 部署代码切换期间必须全程持有同一把 pipeline lock。
6. 部署任一环节失败，live 必须精确恢复；不得输出 `deploy OK`。
7. verify 只能产生隔离的 `manual_rerun`，不能写 official receipt/state/live audit/SQLite/log。
8. repo 不接收 live 反向写入；`.hermes` git 不提交运行态或敏感数据。

---

## 3. 变更总览

### 3.1 R1：单一写事务

- `score_pipeline()` 变为公开安全入口：自己获取 `<archive_dir>/.pipeline.lock`。
- `_score_pipeline_locked()` 只能接受由 `pipeline_lock()` mint 的 active lease。
- lease 运行时验证私有 capability、active 状态、PID、thread owner 和 lock path。
- daily、Web refresh、IBKR live/demo、CLI、M4、8765 兼容入口均接入同一事务边界。
- Web 非阻塞写入抢锁失败返回 HTTP 409，不启动第二个 writer。
- AST 测试限制 private helper 的合法生产调用方；运行时 lease 才是主守卫。

### 3.2 R1 附属：安全原子写

- CSV 写入先写同目录 temp，再 `os.replace()`。
- 已有文件保留 `S_IMODE`；新 CSV 使用 `0644`。
- 失败时保留旧内容/权限并清理 temp。
- 锁竞争异常与其他 `OSError` 分开，非竞争错误不伪装为 BUSY。

### 3.3 R2：回执与 Health 真相

- scheduled run 开始时原子写 `RUNNING`。
- 评分、产物、diff、state commit 等必需步骤全部成功后才写 `OK`。
- 顶层 `except BaseException` 将任意失败写为 `FAILED` 再 re-raise。
- FAILED 回执替换也失败时，删除旧绿 attestation，让 Health 报 missing/critical。
- Health 根据 `sync_time` 现算 IBKR age，不信冻结的 `snapshot_stale`。
- `RUNNING` 超时变 CRITICAL；OK 回执 26 小时超时变 CRITICAL。
- 26 小时阈值依赖 launchd 每个自然日 07:10 执行（无 `Weekday` 过滤）；行情陈旧仍按交易日。
- Alpaca SIP 是 auxiliary：失败/陈旧使 Health `DEGRADED`，不伪造核心 run FAILED。
- Web banner 区分 RUNNING/FAILED/OK，不让旧绿头条覆盖当日失败。

### 3.4 R3：部署互斥、精确回滚和隔离验证

- `deploy_to_live.sh` 引入显式 fixture test mode；生产模式忽略所有测试路径/故障注入 env。
- 在代码切换前停止 dashboard，避免同步期间惰性 import 半套代码。
- `pipeline_lock_exec` 只 acquire 一次，连续覆盖 backup/sync/config/smoke。
- helper 将同一 open-file-description FD 传给内部 bash 模式。
- 内部模式同时验证：继承 FD 与目标 `.pipeline.lock` 同 inode；新 OFD 非阻塞抢锁必须得到 `EWOULDBLOCK/EAGAIN`。
- 回滚用独立备份 + `rsync --delete`，恢复文件集合、内容、mode、VERSION、入口脚本和原 git index。
- rollback 自身失败输出 `DOUBLE FAILURE`、保留 backup、非零退出，不自动重试。
- `.hermes` commit 失败是 fatal，必须回滚，不打印 OK。
- 部署备份移到 `~/.hermes-deploy-backups/`，不在 `.hermes` git 内。
- verify 克隆 history/soft_history/archive 到临时 APFS 副本，排除 audit 和 `.pipeline.lock`。
- verify 使用真实 `run_daily.sh --deploy-verify`，但将数据根/日志定向临时目录，并验证 `manual_rerun`。

### 3.5 R4：8766 分级鉴权

当前明确威胁模型：8766 只绑定 loopback，不经反向代理或对外暴露。

- 全部 mutating POST 校验 loopback Host/Origin。
- `/api/m4_golive`、`/api/confirm_execution` 额外要求 `HERMES_CONFIRM_TOKEN`。
- refresh/recompute/read-only check 端点在 loopback 下不要求 token。
- 锁冲突返回 HTTP 409，不调用第二个 writer。
- 若未来暴露到非 loopback，上线前必须将全部 mutating POST 升级为 token 鉴权并重做 CSRF/代理信任 review。

### 3.6 R5：repo/live 数据边界

- 删除 deploy 中 live `soft_history` 反向同步 repo。
- NEXT5 只写 `HERMES_DATA_DIR`/live runtime archive，不写 repo `building/logs`。
- `.hermes` 只 stage 明确 allowlist：package Python（排除 tests/config/data）、VERSION、daily/dashboard 入口。
- SQLite、audit/journal、持仓、order preview、logs/reports、backup、token/key/config 不进 commit。
- deploy 开始前若 allowlist 内已有 staged 文件，在停 dashboard 前拒绝执行。

---

## 4. 最后一轮复审后的补强

### 4.1 部署内部 FD 真实性

旧实现只用 bash `eval ": <&$fd"` 检查 FD 已打开，`FD=0` 也可通过。现在：

1. `os.fstat(inherited_fd)` 必须与 `os.stat(lock_path)` 的 dev/inode 一致。
2. lock target 必须是 regular file。
3. 新 `os.open(lock_path, O_RDWR)` 的 OFD 执行 `LOCK_EX|LOCK_NB`。
4. 只有 `EAGAIN/EWOULDBLOCK` 算“锁确实被占用”；其他 `OSError` 全部失败。
5. 如新 OFD 抢锁成功，说明目标未持锁，立即 abort。

新测试传入“指向正确 lock 文件但没有加锁”的真实 FD，必须在备份/同步前拒绝，fixture 零变化。

边界说明：这是防 agent/人工误调内部模式的 guardrail，不是对抗拥有本机同用户代码执行权的恶意调用者的安全边界。请 reviewer 重点检查是否仍存在意外绕过或 TOCTOU。

### 4.2 refresh_score 真实锁 409 回归

新测试不 mock `PipelineBusy`：

1. 主线程持有当前数据根真实 `.pipeline.lock`。
2. 启动临时 HTTP server。
3. loopback 无 token POST `/api/refresh_score`。
4. 断言 HTTP 409、`busy=true`、`as_of=latest`。

手工先验证输出 `REFRESH_409_OK`，随后固化成自动测试。

### 4.3 持久化等价比较器收紧

- 不再全局忽略名为 `payload_hash` 的所有字段。
- 只对 `audit_log.jsonl` 顶层、由易变 `run_ts` 派生的 audit `payload_hash` 定点归一化。
- SQLite 中同名 `payload_hash` 列仍严格比较。
- 报告显式记录：`archive_soft_inputs/write_dated_snapshot` 是评分事务之外的独立命令。
- 收紧后重跑四日期，仍 `all_equal=true`。

---

## 5. 文件级改动清单

### 5.1 修改文件

| 文件 | 变更 |
|---|---|
| `context.md` | 同步 562 测试、8766 分级鉴权、当前稳固架构 |
| `docs/PRODUCTION_RUNBOOK.md` | 单次持锁部署、精确回滚、verify 隔离、每自然日调度、FD guardrail、CSV 权限待办 |
| `ops/run_daily.py` | Alpaca 辅助状态原子写；deploy verify 模式 |
| `ops/run_daily.sh` | 支持 `HERMES_RUN_LOG`；verify 跳过 heartbeat/失败通知 |
| `ops/verify_live.sh` | 临时隔离数据副本；真入口 manual verify；零 live 污染检查 |
| `scripts/deploy_to_live.sh` | fixture 化、dashboard lifecycle、单次锁、精确 backup/rollback、allowlist commit、FD 真实性探测 |
| `src/hermes_escape_top/cli.py` | bootstrap/backfill/freeze/archive-soft/soft-data 命令显式进锁 |
| `src/hermes_escape_top/core/safe_io.py` | active lease、运行时守卫、FD 导出、原子 CSV 保 mode |
| `src/hermes_escape_top/ibkr/live_check.py` | 完整 live-check workflow 单 lease |
| `src/hermes_escape_top/pipeline.py` | 公开安全入口 + private locked helper |
| `src/hermes_escape_top/scripts/check_next5_unlock.py` | 只写 runtime archive，取消 live 回写 repo |
| `src/hermes_escape_top/scripts/run_daily_package.py` | daily 单 lease；RUNNING/OK/FAILED 回执；顶层失败覆盖；commit failure fatal |
| `src/hermes_escape_top/web/health.py` | 动态 IBKR age、receipt 状态机、SIP auxiliary、26h 日历日假设 |
| `src/hermes_escape_top/web/mirror_server.py` | 8765 兼容 refresh 非阻塞抢锁 + 409 |
| `src/hermes_escape_top/web/refresh.py` | refresh 整条链单 lease；manifest/score 不并发写 |
| `src/hermes_escape_top/web/render.py` | RUNNING/FAILED/OK 运行回执横幅语义 |
| `src/hermes_escape_top/web/server.py` | 分级鉴权、全写端点 409、M4/IBKR/refresh 锁接线、Health 附件 |

被修改的既有测试：

- `test_backfill_guard.py`
- `test_ibkr_live_check.py`
- `test_mirror_web.py`
- `test_ops_entrypoints.py`
- `test_phase15_integration.py`
- `test_run_receipt_banner.py`
- `test_run_receipt_writer.py`
- `test_safe_io.py`

### 5.2 新增文件

| 文件 | 用途 |
|---|---|
| `scripts/compare_pipeline_persistence.py` | 四日期 payload + canonical persistence 等价比较 |
| `src/hermes_escape_top/scripts/pipeline_lock_exec.py` | macOS Python `fcntl` 单次持锁执行完整命令 |
| `test_deploy_to_live.py` | 部署 fixture、失败注入、精确回滚、FD 伪造反例 |
| `test_health_truth.py` | IBKR、receipt、SIP 健康真相 |
| `test_next5_runtime_isolation.py` | NEXT5 不回写 repo |
| `test_pipeline_lock_exec.py` | helper 持锁、竞争退出码、子进程 FD 继承 |
| `test_pipeline_transaction.py` | public/private 事务边界、lease 拒绝、AST 调用方 |
| `building/reports/runtime_write_path_audit_2026_06_19.md` | 写入调用图与行为边界 |
| `building/reports/pipeline_persistence_equivalence_2026_06_19.json` | 四日期等价证据 |
| `docs/history/2026-06-19_system_stabilization_ab_plan.md` | R1-R6 方案、A/B 分工和执行状态 |
| `docs/history/2026-06-19_stabilization_release_review_method.md` | 七节点串行 review 规程 |
| `docs/history/2026-06-19_stabilization_changes_review_handoff.md` | 本交接文档 |

---

## 6. 行为证明

### 6.1 四日期等价

报告：`building/reports/pipeline_persistence_equivalence_2026_06_19.json`

| 日期 | equal | input_hash |
|---|---|---|
| 2022-01-03 | true | `5a6700710a603c0a469352c3d24a042f1d437e31b3b1ac8706d171de576e99dc` |
| 2024-04-19 | true | `399176b97668fd0c6531fe7068230bcd93cf388774ba15fe4e357667418c40e5` |
| 2026-05-29 | true | `aecafeea35fee0107b5cfea47552aed3a42ac51a1d14279a32660f0c4c969bbc` |
| 2026-06-11 | true | `c8a26183d683ce5da6100ca6eed1db85aced227b15f7875685083cd8634e2894` |

比较范围：

- payload/status/input_hash
- `hermes_state.sqlite`
- `reentry_state.sqlite`
- `mirror_reference.sqlite`
- `flow_reference.sqlite`
- `audit_log.jsonl`
- `signal_journal.jsonl`

`all_equal=true`。

### 6.2 测试

全套：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

结果：`562 passed, 1 warning in 76.47s`。

唯一 warning 是已存在的 Pandas 弃用提示：`core/data/wso_index.py:77` 使用 `Timestamp.utcnow()`。

其他证据：

- deploy fixture：`12 passed`
- phase15 Web integration：`19 passed`
- Health truth：`6 passed`
- 隔离数据根 system validation：`28/28 pass`（本批早先完整运行）
- `/usr/bin/python3 3.9.6` helper 实测：`LOCK_HELPER_OK`
- 手工真实锁 HTTP 实测：`REFRESH_409_OK`
- `bash -n`：PASS
- `/usr/bin/python3 -m compileall`：PASS
- `git diff --check`：PASS

---

## 7. 已知残余边界

### 7.1 未执行的 live 权限归一化

2026-06-19 只读盘点：

- live `data/` 共 68 个 CSV：49 个 `0600`，19 个 `0644`。
- repo 对应 71 个 CSV 全是 `0644`。
- 当前运行进程与文件同用户，因此这是权限漂移，不是当前可读性故障。
- 新 `atomic_write_csv` 只保留现有 mode，不会自动修复历史 `0600`。
- 必须在受控部署窗口中先记录 path/mode/SHA256，再人工归一化到 `0644`，复核后记录。

本批未修改这些 live 文件。

### 7.2 部署内部锁验证的威胁模型

inode + contention probe 可以防住常见误调，但不是针对本机同用户恶意代码的安全边界。拥有同用户代码执行权的调用者本来就可以直接修改 live。Reviewer 应判断当前 guardrail 是否足以防止 agent/运维误操作。

### 7.3 等价证明范围

- 证明使用 `include_ibkr=False` 保证离线确定性。
- IBKR execution auto-confirm 分支不在四日期等价回放中，但有 `test_state_store_and_actions.py::test_pipeline_auto_confirms_t1_from_ibkr_executions` 覆盖。
- `archive_soft_inputs()` 的 dated snapshots 是独立命令，不在 score transaction 证明范围内。

### 7.4 还没有做的发布工作

- 没有 commit/stage/push。
- 没有执行 `deploy_to_live.sh`。
- 没有重启 dashboard/launchd。
- 没有对 live 运行真实 smoke/verify。
- R6 versioned release + symlink 原子切换尚未实施；计划是本版上线后稳定观察 3 个交易日再做。

---

## 8. 请 Reviewer 重点攻击的问题

1. 是否还有生产路径可在无 active lease 情况下调用真实持久化函数？
2. 是否有任何可伪造/复用失效 lease 的路径？
3. daily 已持锁再调 `_score_pipeline_locked()` 是否完全避免自死锁？
4. 部署是否真的在一次 lock acquire 内完成 backup/sync/config/smoke？
5. `require_pipeline_lock_held()` 的 inode + 新 OFD 竞争探测是否存在 macOS `flock` 语义漏洞或错误分类？
6. dashboard stop 与 lock acquire 之间若 daily 启动，是否只会导致部署等待，而不会并发切换？
7. 任一 rollback 路径是否会遗留新增文件、错 mode、新 VERSION 或污染 git index？
8. `.hermes` allowlist 是否可能包含 config/data/tests/runtime secret？
9. verify 是否仍有任何路径写 official receipt、live state、audit、SQLite、heartbeat 或 live log？
10. `BaseException` 失败路径是否会留下旧绿回执？回执写入自身失败时是否说真话？
11. Health 的 26h 回执规则是否与实际 launchd “每自然日”配置一致？
12. 8766 是否确实只绑定 loopback？若不是，当前分级 token 政策必须立即判失效。
13. 持久化比较器的归一化是否可能掩盖真实语义变化？
14. 是否有未被六个 canonical artifact 覆盖的 `score_pipeline` 写点？

---

## 9. 建议复审命令（严格串行）

### 9.1 静态检查

```bash
cd ~/Documents/github/hermes
git status --short
git diff --check
bash -n scripts/deploy_to_live.sh ops/run_daily.sh ops/verify_live.sh
/usr/bin/python3 -m compileall -q \
  src/hermes_escape_top ops/run_daily.py scripts/compare_pipeline_persistence.py
```

### 9.2 事务与锁

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_pipeline_transaction.py \
  src/hermes_escape_top/tests/test_pipeline_lock_exec.py \
  src/hermes_escape_top/tests/test_safe_io.py -q
```

### 9.3 Web/Health

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_run_receipt_writer.py \
  src/hermes_escape_top/tests/test_run_receipt_banner.py -q
```

### 9.4 Deploy/Isolation

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_deploy_to_live.py \
  src/hermes_escape_top/tests/test_ops_entrypoints.py \
  src/hermes_escape_top/tests/test_next5_runtime_isolation.py -q
```

### 9.5 全套

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

不要在复审中运行真实 `deploy_to_live.sh`，不要 chmod live，不要 commit。

---

## 10. Reviewer 回报格式

请先列 findings，按 P0/P1/P2/P3 排序，每条包含：

- 文件 + 行号
- 可触发场景
- 为什么现有测试没抓住
- 最小修复
- 应增加的失败测试

若无阻断项，请明确写：

```text
未发现 P0/P1/P2 阻断项。
已运行：<commands/results>
残余风险：<list>
结论：READY FOR COMMIT / NOT READY
```

复审通过只表示可以进入拆分 commit 与真实部署准备，不表示允许 agent 自动上线。

---

## 11. 独立复审结论与放行状态

2026-06-19 独立复审结论：

- 未发现 P0/P1/P2 阻断项。
- live CSV 权限漂移已登记，只在受控部署窗口归一化，不在 code review 中静默修 live。
- FD inode + contention probe 按 guardrail 定级，不宣称为对抗本机同用户恶意代码的安全边界。
- 四日期等价回放的 `include_ibkr=False` 范围已明确；IBKR auto-confirm 分支由独立测试覆盖。
- 工作区未混入 staged 内容、config/data 运行态、`.bak`、`.pyc` 或 `__pycache__` 文件。

放行结论：**READY FOR COMMIT**。

下一步边界：先按 runtime transaction / health+Web / deploy+isolation / tests+docs 拆分 commit，每个 commit 后运行对应 focused tests；全部 commit 完成后再跑一次全套，然后另开真实部署窗口。
