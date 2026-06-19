# Hermes 稳固版本发布前 Review 方法

> 日期：2026-06-19
> 适用范围：`2026-06-19_system_stabilization_ab_plan.md` 的 R1-R5 变更
> 目标：证明本批变更可以进入人工部署窗口，而不是仅确认“代码看起来合理”
> 执行纪律：**严格串行；一次只审一个风险点，修一个问题后立即重审并运行对应测试；禁止并行 review、并行测试和并行回测。**

---

## 1. Review 的最终问题

本次 review 必须用证据回答六个问题：

1. 任意时刻是否确实只有一个生产 writer？
2. 评分重构前后，payload 与全部关键落盘产物是否等价？
3. daily 失败、进程中断或辅助数据失败时，页面是否展示当前事实？
4. 部署是否从代码切换开始到 smoke 结束始终持有同一把锁？
5. 任一步失败后，live 文件集合、内容、权限和 git index 是否精确恢复？
6. repo、live、临时验证目录和 `.hermes` git 是否保持清晰的数据边界？

任何问题没有直接证据，都不能标记为通过。

---

## 2. 安全边界

Review 期间遵守以下硬约束：

- 不运行真实部署，不改 live，不操作 launchd。
- 不提交 git，不执行 `git add -A`。
- 不修改生产 config、策略阈值、flag、路由或 IBKR readonly 设置。
- 所有评分回放使用独立 `HERMES_DATA_DIR`。
- 部署测试只使用临时 fixture，禁止把测试路径指向 `~/.hermes`。
- 不在北京 07:00-07:20 运行任何可能与 daily 争锁的验证。
- 发现问题后立即停止当前节点；只修该问题，重跑该节点，再继续下一节点。

---

## 3. Review 输入与基线

开始前记录以下事实到 review 报告：

```bash
cd ~/Documents/github/hermes
git status --short
git rev-parse --short HEAD
git diff --stat
git diff --check
head -n 1 ~/.hermes/skills/investment/escape-top/hermes_escape_top/VERSION
```

当前预期边界：

- repo 基线 HEAD：`3f48dd3`
- live VERSION：`2beea7d 20260618_205923`
- 工作区允许存在本批 R1-R5 未提交修改。
- review 前后 live VERSION 必须不变。

先读取：

1. `context.md`
2. `docs/history/2026-06-18_review_remediation.md`
3. `docs/history/2026-06-19_system_stabilization_ab_plan.md`
4. `building/reports/runtime_write_path_audit_2026_06_19.md`
5. `building/reports/pipeline_persistence_equivalence_2026_06_19.json`

---

## 4. 串行 Review 循环

每个风险点都执行同一个循环：

1. **声明假设**：写清该节点依赖什么，以及什么结果算失败。
2. **追踪入口**：从公开入口追到真实持久化点，不只检查按钮或包装函数。
3. **检查 diff**：每一行必须能对应本节点目标；不顺手重构邻近代码。
4. **构造反例**：优先检查锁冲突、异常、kill、文件残留和陈旧状态。
5. **运行 focused test**：只运行当前节点测试并阅读断言，不只看退出码。
6. **修复或通过**：有问题则只修一个问题，回到第 2 步重新 review。
7. **记录证据**：文件、行、命令、结果、残余风险。
8. **进入下一节点**：当前节点没有结论前禁止开始下一节点。

禁止把多个问题攒到最后一起修改，因为这样无法确认是哪项修改改变了行为。

---

## 5. Review 顺序

### 5.1 节点一：单一生产写事务

重点文件：

- `src/hermes_escape_top/core/safe_io.py`
- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/scripts/run_daily_package.py`
- `src/hermes_escape_top/web/refresh.py`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/mirror_server.py`
- `src/hermes_escape_top/ibkr/live_check.py`
- `src/hermes_escape_top/cli.py`

检查方法：

1. 搜索 `score_pipeline`、`_score_pipeline_locked` 和所有 archive/SQLite/audit/journal 写入。
2. 从 daily、8766、8765 兼容入口、CLI、IBKR demo/live、M4 shadow/backfill/golive 分别追踪。
3. 确认公开 `score_pipeline()` 自己获取锁，而不是依赖调用方自觉加锁。
4. 确认私有 locked helper 需要 active lease，外部无法伪造或复用失效 lease。
5. 确认 lease 校验 PID、thread、lock path 和 active 状态。
6. 确认不存在 `lock_held=True`、可选 bypass 或隐式重入。
7. 确认锁竞争与真实 I/O 错误分开处理；非竞争类 `OSError` 不得伪装成 BUSY。

必须注入的故障：

| 场景 | 预期 |
|---|---|
| 两个 Web refresh 同时进入 | 一个执行，一个 HTTP 409 |
| daily 持锁时 CLI score 启动 | 等待或超时，不并发写 |
| 无 lease 调 private helper | 立即失败，零落盘 |
| lease 离开 context 后复用 | 立即失败 |
| 其他线程/进程复用 lease | 立即失败 |
| 锁文件权限或 I/O 错误 | 原错误上抛，不返回 BUSY |

Focused tests：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_pipeline_transaction.py \
  src/hermes_escape_top/tests/test_pipeline_lock_exec.py \
  src/hermes_escape_top/tests/test_safe_io.py -q
```

通过标准：所有生产写入口都进入同一事务边界，且运行时守卫能拒绝旁路。

### 5.2 节点二：持久化行为等价

只比较 payload 不够。本节点必须同时比较：

- payload、status、`input_hash`
- state DB canonical row
- audit canonical record
- journal canonical entry
- mirror/reentry/flow 等 canonical snapshot
- 其他报告中列明的关键持久化产物

执行：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python \
  scripts/compare_pipeline_persistence.py
```

检查报告：

`building/reports/pipeline_persistence_equivalence_2026_06_19.json`

Review 要点：

1. 四个日期覆盖早期、压力期、近期和当前基线。
2. 归一化字段只能包含 timestamp、临时路径、自动递增 ID 等非语义字段。
3. 不允许把 score、状态、仓位、原因、hash 或数据日期加入忽略列表。
4. 每个 canonical artifact 必须明确存在；“文件缺失但两边都缺失”不能自动算通过。
5. 报告必须 `all_equal=true`。

### 5.3 节点三：原子文件写入

重点文件：`src/hermes_escape_top/core/safe_io.py` 及 CSV 写调用方。

检查：

- 同目录临时文件写完后使用 `os.replace()`。
- 已存在文件保留原 mode；新文件使用项目约定 mode。
- 写失败时旧文件内容和 mode 不变。
- 临时文件被清理。
- 不把 `fsync` 与“避免半文件读取”混为一谈；`os.replace()` 负责原子可见性，`fsync` 只处理断电耐久性。

Focused test：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_safe_io.py -q
```

### 5.4 节点四：scheduled 回执和 Health 真相

重点文件：

- `src/hermes_escape_top/scripts/run_daily_package.py`
- `src/hermes_escape_top/web/health.py`
- `src/hermes_escape_top/web/render.py`
- `ops/run_daily.py`

检查状态机：

```text
scheduled start -> RUNNING
all required steps succeed -> OK
any BaseException -> FAILED
stuck RUNNING beyond threshold -> health failure
```

Review 要点：

1. `OK` 只能在评分、产物、diff、state commit 等必需步骤全部成功后写入。
2. 任意早期异常都覆盖旧绿回执；若替换 FAILED 回执也失败，旧绿证明必须失效。
3. deploy verify 只能写 `manual_rerun`，不得生成 scheduled 官方记录。
4. Health 每次请求根据 `sync_time` 计算 IBKR 年龄，不信任冻结的 `snapshot_stale`。
5. 当日失败优先于昨日成功；26 小时宽限不能掩盖当天明确失败。
6. Alpaca SIP 属辅助数据：失败使 health `DEGRADED`，但不能伪造核心 run FAILED。
7. 页面文案与结构化状态一致，不能出现旧绿头条。

Focused tests：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_run_receipt_writer.py \
  src/hermes_escape_top/tests/test_run_receipt_banner.py \
  src/hermes_escape_top/tests/test_health_truth.py \
  src/hermes_escape_top/tests/test_ibkr_live_check.py -q
```

### 5.5 节点五：Web 写端点与状态码

当前唯一政策：

- 所有 mutating POST 都要求 loopback Host/Origin。
- `/api/m4_golive`、`/api/confirm_execution` 额外要求 `HERMES_CONFIRM_TOKEN`。
- 数据刷新、重算和只读检查端点在 loopback 下不要求 token。
- 锁冲突返回 409，不调用第二个 writer。

逐端点检查：认证必须在业务 handler 前完成；BUSY 必须在实际写入前返回。

Focused tests：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_phase15_integration.py \
  src/hermes_escape_top/tests/test_mirror_web.py -q
```

停止条件：发现 8766 绑定非 loopback、存在反向代理或可被其他主机访问。此时当前鉴权模型立即失效，部署前必须把所有 mutating POST 升级为 token 鉴权并重新做 CSRF review。

### 5.6 节点六：部署互斥与精确回滚

重点文件：

- `scripts/deploy_to_live.sh`
- `src/hermes_escape_top/scripts/pipeline_lock_exec.py`
- `ops/verify_live.sh`
- `ops/run_daily.sh`
- `src/hermes_escape_top/tests/test_deploy_to_live.py`

检查顺序：

1. production 路径不能被普通环境变量偷偷替换；fixture override 只在显式 test mode 生效。
2. dashboard 在代码切换前停止，避免同步期间惰性 import 半套代码。
3. backup、sync、config decision、smoke 必须被**一次 acquire** 连续包住，不能每步分别获取锁。
4. internal locked mode 必须验证继承 FD 与目标 lock 是同一 inode，且新 OFD 非阻塞抢锁必须返回 `EWOULDBLOCK`；单纯检查 FD 已打开不构成持锁证明。
5. 回滚使用完整备份和 `rsync --delete`，同时恢复文件集合、内容、mode、VERSION、入口脚本和原 git index。
6. rollback 自身失败必须输出 `DOUBLE FAILURE`、保留 backup、非零退出，不得重试或打印 OK。
7. `.hermes` commit 失败属于部署失败，必须回滚。
8. `deploy OK` 只能出现在 dashboard、verify 和 commit 全部成功之后。

部署 fixture 至少覆盖：

| 注入点 | 必须证明 |
|---|---|
| backup 后失败 | live 精确恢复 |
| rsync 产生新增文件后失败 | 新文件消失 |
| smoke 失败 | mode、内容、集合恢复 |
| dashboard 重启失败 | 回滚并再次恢复 dashboard |
| verify 失败 | 不提交、不输出 OK |
| `.hermes` commit 失败 | 回滚、非零、无 OK |
| rollback 再失败 | DOUBLE FAILURE，保留备份 |
| 部署前已有 staged allowlist 文件 | 在停 dashboard 前拒绝部署 |

Focused tests：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_deploy_to_live.py \
  src/hermes_escape_top/tests/test_pipeline_lock_exec.py \
  src/hermes_escape_top/tests/test_ops_entrypoints.py -q
```

静态检查：

```bash
bash -n scripts/deploy_to_live.sh ops/run_daily.sh ops/verify_live.sh
```

### 5.7 节点七：repo/live/verify 数据边界

检查：

- deploy 不再把 live `soft_history` 反向同步到 repo。
- NEXT5 只写 `HERMES_DATA_DIR` 或 live runtime archive。
- verify 使用 APFS 临时隔离副本，不写 live audit、SQLite、receipt、state、heartbeat 或日志。
- verify 产生 `manual_rerun`，不是 scheduled。
- `.hermes` git 只 stage 明确 allowlist。
- SQLite、audit、journal、持仓、order preview、logs、reports、backup、token、key 和 config 不进入 commit。
- 部署备份位于 `.hermes` git 目录之外。

Focused tests：

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests/test_next5_runtime_isolation.py \
  src/hermes_escape_top/tests/test_ops_entrypoints.py \
  src/hermes_escape_top/tests/test_deploy_to_live.py -q
```

---

## 6. 全局回归

所有节点逐项通过后，才运行全局验证。

### 6.1 全套测试

```bash
PYTHONPATH=src:src/hermes_escape_top/tests \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest \
  src/hermes_escape_top/tests -q
```

当前期望：`562 passed`。新增测试可使数量增加，但不得减少或出现 skip/xfailed 漂移而不解释。

### 6.2 系统验证

使用独立数据副本设置 `HERMES_DATA_DIR`，然后运行：

```bash
HERMES_DATA_DIR=<isolated-data-root> \
PYTHONPATH=src \
/Users/liweishi/.hermes-v3/.venv/bin/python scripts/system_validation.py
```

期望：`28/28 pass`。

### 6.3 静态检查

```bash
git diff --check
bash -n scripts/deploy_to_live.sh ops/run_daily.sh ops/verify_live.sh
/usr/bin/python3 -m compileall -q \
  src/hermes_escape_top ops/run_daily.py scripts/compare_pipeline_persistence.py
```

---

## 7. Review 发现的严重度

| 等级 | 定义 | 处理 |
|---|---|---|
| P0 | 可能下单、修改 readonly、损坏真实持仓/密钥 | 立即停止全部工作，禁止部署 |
| P1 | 并发写、旧绿回执、回滚不精确、部署成功误报 | 当前节点必须修复并重跑全部相关证据 |
| P2 | health/鉴权/数据边界不真实，可能误导操作 | 部署前必须修复 |
| P3 | 文档漂移、诊断性或维护性问题 | 本批修正或明确登记，不得悄悄忽略 |

Review 报告必须先列 findings，按 P0-P3 排序；没有 finding 时明确写“未发现阻断项”，并列出剩余风险。

---

## 8. 单项 Review 记录模板

```markdown
### [节点编号] 标题

- 假设：
- 审查范围：
- 入口到持久化路径：
- 故障注入：
- Finding：P0/P1/P2/P3 或无
- 修改：无 / 文件与原因
- Focused test：命令 + 结果
- 行为证据：报告路径或关键断言
- 残余风险：
- 结论：PASS / BLOCKED
```

一次只填写一个节点。若发生修改，该节点新增一段“修复后复审”，不能直接覆盖原 finding。

---

## 9. Release-ready 判定

同时满足以下条件才可以进入 commit 和真实部署准备：

- 七个 review 节点全部 PASS。
- 没有未关闭的 P0/P1/P2。
- 4 日期 payload 与 canonical persistence `all_equal=true`。
- 全套 pytest 全绿，系统验证 28/28。
- deploy fixture 的失败注入全部精确回滚。
- `git diff --check`、shell syntax、compileall 通过。
- repo HEAD 与 live VERSION 被记录，review 期间 live VERSION 未改变。
- review 报告列出所有改动文件、测试、允许的残余风险和明确的“不自动下单”确认。

Release-ready 不等于自动部署。真实部署仍需单独窗口、独立前置检查和人工确认。

---

## 10. Commit 与部署后的下一步

Review 通过后建议按以下边界拆 commit：

1. runtime transaction + safe I/O
2. receipt + health + Web status/auth
3. deploy rollback + verify isolation + repo/live hygiene
4. tests + reports + documentation

提交后重新运行全套测试，再进入真实部署。上线后观察三个交易日：

- 每日只有一份 scheduled 官方 run。
- 无异常 BUSY、重复 writer 或陈旧绿回执。
- IBKR 与 SIP health 日期正确。
- repo 不出现 live 反向写入。
- `.hermes` commit 不含运行态或敏感文件。
- rollback fixture 持续通过。

三个交易日稳定后，才开始 R6 versioned release + symlink 原子切换。
