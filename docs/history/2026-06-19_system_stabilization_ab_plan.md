# Hermes 系统稳固计划与双 Agent A/B 轨分工

> 日期：2026-06-19
> 依据：`docs/history/2026-06-18_review_remediation.md` 外部审计补充、当前代码与 `context.md`
> 当前 repo：`hermes-docs@3f48dd3`；当前 live：`2beea7d`
> 目标：先关闭一致性、健康、部署三类高风险缺口，再恢复策略和 WebUI 功能开发。
> 修订：v1.2 补入落盘等价证明、active lease 运行时守卫、部署单次持锁，并按本机 loopback 威胁模型定稿 token 政策。

## 0. 先说结论

接下来不应继续加因子、数据源或首屏模块。最优顺序是：

1. **统一所有生产写入入口**，让定时任务、Web、CLI、IBKR 检查不能绕过同一把锁。
2. **让 health 和运行回执反映当前事实**，不能继续展示过期 IBKR 或遗留绿色回执。
3. **让部署与运行互斥并可精确回滚**，失败时 live 必须逐字节回到部署前状态。
4. **收紧写端点鉴权与运行数据边界**，避免 token 政策分裂和 `.hermes` 混入敏感运行态。
5. 完成前三项并稳定运行 3 个交易日后，再恢复普通优化。

双 Agent 可以并行，但必须按**文件所有权**拆分，而不是两边同时改同一条调用链：

- **Agent A：运行时一致性 / 健康真相轨**
- **Agent B：部署原子性 / 仓库隔离轨**

两轨只有一个技术汇合点：A 先交付可供部署脚本调用的 pipeline lock 接口，B 再把它接入部署流程。

---

## 1. 已确认事实与计划假设

### 1.1 已确认事实

以下问题已经复核，不再把时间花在争论是否存在：

| 编号 | 问题 | 风险 |
|---|---|---|
| S1 | `score_pipeline()` 可从 Web、CLI、IBKR 路径无锁写 5 个 SQLite、audit 和 journal | P1 |
| S2 | 部署只做一次性 `pgrep`，之后可与 daily/refresh 交叠 | P1 |
| S3 | health 信任冻结的 `snapshot_stale`，不按 `sync_time` 现算 IBKR 年龄 | P1 |
| S4 | rollback 只覆盖解包，不删除失败部署新增文件 | P1 |
| S5 | `.hermes` commit 失败仍可输出 `deploy OK` | P1 |
| S6 | 只有 state commit 失败会写红回执，较早异常会遗留旧绿回执 | P2 |
| S7 | busy 返回 HTTP 200；写端点 token 政策与 `context.md` 不一致 | P2 |
| S8 | `.hermes` 整树提交包含 SQLite、持仓、预览、日志与备份 | P2 |
| S9 | NEXT5 从 live 回写 repo | P3 |
| S10 | `mkstemp + os.replace` 将原 0644 CSV 变为 0600 | P3 |

### 1.2 本计划采用的明确决策

1. **SIP 是辅助数据。** SIP 更新失败不把核心评分判为失败，但 health 必须降为 `DEGRADED`，页面明确展示数据日期与失败原因。
2. **busy 使用 HTTP 409。** 响应体继续提供 `busy=true`、锁持有阶段和建议重试时间。
3. **repo 是代码与非敏感配置的 SSOT。** live 只保存机器环境、密钥和运行数据，不允许反向写 repo。
4. **不做隐式“可重入 flock”。** 使用清楚的事务边界、运行时 lease 守卫和私有 locked helper，避免第二个文件描述符造成自锁或错误放行。
5. **部署分两步完成。** 先把当前 in-place 部署修到可互斥、可精确回滚，再升级到 versioned release + symlink 原子切换。

### 1.3 已定稿的安全政策

8766 当前只绑定 loopback，不经反向代理或对外暴露。所有写端点都校验本机 Host/Origin；会改变生产行为或决策状态的 `m4_golive`、`confirm_execution` 额外要求 `HERMES_CONFIRM_TOKEN`；数据刷新、重算和只读检查仅限 loopback，不要求 token。

这是当前运行边界的刻意取舍，不是可复用的对外服务鉴权方案。如 8766 改为非 loopback 绑定、经反向代理或可被其他主机访问，在暴露前必须将全部 mutating POST 升级为 token 鉴权并重新审核 CSRF/代理信任边界。

### 1.4 不在本批范围

- 不改策略阈值、评分权重、路由规则和 flag 部署态。
- 不新增因子、外部数据源或 WebUI 面板。
- 不自动下单，不修改 IBKR `readonly=true`。
- 不重跑 alpha gate 或全窗口策略回测；只做行为一致性回放。
- 不借机重构无关模块。

---

## 2. 完成定义

本计划只有同时满足以下条件才算完成：

### 2.1 写入一致性

- 所有生产写入路径只能从一个 transaction boundary 进入。
- daily、Web refresh、IBKR live/demo、CLI score 同时触发时，最多一个 writer。
- Web 冲突返回 `409 BUSY`，CLI/daily 可在有上限的 timeout 内等待。
- dashboard 作为 reader 只能看到旧文件或新文件，不能看到半写文件。
- 原 0644 的 CSV 原子替换后仍为 0644。

### 2.2 健康与回执

- IBKR 陈旧状态由当前时间与 `sync_time` 动态计算，不信任旧布尔值。
- 当天 scheduled run 不存在、失败或仍在运行时，health 能准确显示。
- 核心运行任一步骤异常都会留下 `FAILED` 回执，不能保留上一次绿色头条。
- SIP 过期或刷新失败显示 `DEGRADED`，但不伪装成核心评分失败。
- 业务 `/api/health_status` 必须先说真话；`/livez`、`/readyz` 是可选的后续拆分，不作为 R2 阻塞条件。

### 2.3 部署

- 部署切换代码时不能有 daily/refresh writer 在运行，也不能有新 writer 进入。
- stop/backup/swap/smoke 必须由**一次 lock acquire** 连续罩住，禁止每个步骤各自加锁后在步骤间释放。
- 部署失败后，live 文件集合、内容、VERSION 与部署前完全一致。
- `.hermes` commit 失败时部署整体失败，不得输出 `deploy OK`。
- `.hermes` 只跟踪代码、入口脚本和 VERSION，不跟踪运行数据或备份。
- 部署验证仍是 `manual_rerun`，不得写官方 state/receipt。

### 2.4 行为证明

- 全套 pytest 通过，起点为 517 passed。
- 4 个历史日期的策略 payload、status 与 `input_hash` 在重构前后相同。
- 同一输入在重构前后的**持久化语义等价**：state DB、audit、journal、5 个 SQLite/snapshot 均无缺写、增写、字段漂移或顺序语义变化。
- 持久化比较使用隔离的双份 `HERMES_DATA_DIR`；只允许按显式 allowlist 归一化 `run_ts`、自增 rowid 等非确定字段，其余 schema、行和 JSON 内容严格比较。
- 并发故障注入、回执异常注入、rollback 文件集合比较全部通过。
- live deploy 仍保留人工确认，不在本计划中自动执行。

---

## 3. 目标架构

### 3.1 写事务边界

推荐把当前混合“计算 + 持久化”的调用链逐步收口为三层：

```text
Web / daily / CLI / IBKR
          |
          v
run_score_transaction(...)
  1. acquire pipeline lock
  2. refresh/validate inputs when requested
  3. compute score
  4. persist all state/audit/journal atomically
  5. release lock
          |
          +--> pure/offline compute path: no production writes
```

实现时先审计 `score_pipeline()` 的副作用。如果一次拆成纯计算和持久化会造成过大 diff，则采用最小过渡结构：

```python
def score_pipeline(...):
    """Public blocking transaction entry."""
    with pipeline_lock(...):
        return _score_pipeline_locked(...)

def _score_pipeline_locked(..., lease):
    """Private; requires an active lease minted by the transaction entry."""
    _assert_active_pipeline_lease(lease)
```

daily 与 Web 需要把 refresh 和 score 放进同一个事务时，可以显式持锁后调用 `_score_pipeline_locked()`。事务 context manager 必须 mint 一个模块私有的 active lease；helper 在运行时验证 lease 的私有 capability、active 状态、PID 和 thread owner。退出 context 后 lease 立即失效。Python 的私有对象不是安全沙箱，但它能阻止意外绕锁，并让错误调用在运行时当场失败。

静态或 AST 测试可作为第二层约束，限制私有 helper 只能被批准的事务入口调用，但不能代替运行时 lease。禁止增加一个随手可传的 `lock_held=True`，因为布尔值可由任何调用方伪造，会重新制造绕锁入口。

最终形态再把 `_score_pipeline_locked()` 内部拆成：

- `compute_score_payload()`：纯计算，不写生产状态。
- `persist_score_run()`：只在持锁事务内调用。
- `run_score_transaction()`：唯一公开生产写入口。

### 3.2 健康模型

健康状态按严重度合并：

| 状态 | 含义 | 例子 |
|---|---|---|
| `OK` | 核心运行、持仓快照、数据 SLO 均正常 | 今日 scheduled OK，IBKR 未超龄 |
| `DEGRADED` | 核心评分可用，但辅助能力或次要数据异常 | SIP 过期、IBKR 临界、辅助源失败 |
| `CRITICAL` | 不应依此输出执行决策 | 今日 scheduled FAILED、核心 history 漂移、IBKR 严重陈旧且页面仍需对账 |
| `BUSY` | 系统正在写入或部署 | Web 返回 409，不生成第二个 writer |

R2 首先修正现有业务 endpoint：

- `/api/health_status`：返回完整业务健康 JSON，可为 OK/DEGRADED/CRITICAL。

若完成上述核心修复后仍保持小 diff，再补充：

- `/livez`：HTTP 进程存活即可 200，不读取业务数据。
- `/readyz`：代码、数据目录、manifest、锁状态满足服务条件才 200。

### 3.3 回执状态机

scheduled run 开始时先原子写 `RUNNING`，结束时覆盖为 `OK` 或 `FAILED`：

```json
{
  "run_id": "...",
  "run_type": "scheduled",
  "status": "FAILED",
  "started_at": "...",
  "finished_at": "...",
  "failed_step": "artifact_write",
  "error_type": "OSError",
  "message": "...",
  "code_version": "...",
  "payload_hash": null,
  "state_hash": null
}
```

核心规则：

- `RUNNING` 超过预设时限也要被 health 视为异常。
- 捕获顶层 `Exception`，先写 `FAILED` 再重新抛出，保持非零退出码。
- `KeyboardInterrupt`/进程被 kill 无法保证 finally 时，由 health 将超时 `RUNNING` 判为失败态。
- SIP 结果单独记录为 auxiliary source status，由 health 合并，不把核心回执的 `OK` 改写成假失败。

### 3.4 部署互斥与回滚

第一阶段保留当前目录结构，但修正流程：

```text
precheck
  -> stop dashboard
  -> acquire .pipeline.lock ONCE
       -> exact backup to isolated temp dir
       -> rsync --delete repo code to live
       -> smoke
     release .pipeline.lock ONCE
  -> restart dashboard
  -> verify_live (it reacquires pipeline lock normally)
  -> selective .hermes commit
  -> deploy OK
```

若任一步失败：

```text
stop dashboard
  -> acquire .pipeline.lock
  -> rsync --delete backup/ live/
  -> restore VERSION and entry scripts
  -> release lock
  -> restart dashboard
  -> curl dashboard root and /api/health_status
  -> exit non-zero, never print deploy OK
```

不要在 macOS shell 中假设存在 Linux `flock` 命令。A 轨应提供基于 Python `fcntl.flock` 的可执行 lock helper，B 轨只消费它。

`pipeline_lock_exec -- <command>` 的 `<command>` 必须是一个覆盖 backup/swap/smoke 的完整内部阶段，例如 `deploy_to_live.sh --locked-swap`。禁止把 backup、rsync、smoke 分别调用三次 helper，否则步骤间释放锁会重新打开 TOCTOU 窗口。部署期间 8766 会短暂下线，这是有意的安全取舍，必须写入 runbook。

第二阶段升级为：

```text
releases/<hash>/        # 完整 staging
current -> releases/<hash>
previous -> releases/<old_hash>
```

staging 内先 smoke，通过后用原子 symlink rename 切换 `current`。失败时把 `current` 原子切回 `previous`。该阶段在第一阶段稳定后单独实施，不能与第一阶段混成一个巨大 diff。

---

## 4. 单 Agent 顺序执行方案

如果只用一个 agent，按以下顺序做，每项完成后独立 review：

### R1. 单一写事务 + 409 + 文件权限

**实施**

1. 枚举全部 `score_pipeline` 与生产 store 写调用方。
2. 在改代码前冻结 13 个 persistence write-point 的基准快照。
3. 建立唯一事务入口，用 active lease 封闭私有 locked helper。
4. daily 阻塞等待锁；Web 非阻塞冲突返回 409；CLI 有界等待。
5. Web 的 demo_snapshot/live_check 同样非阻塞，冲突返回 409，不得绕锁。
6. 原子写继承目标文件 mode；新文件默认 0644。

**验证**

- focused lock tests。
- 两个 subprocess 同时评分，证明一个等待或返回 BUSY。
- 注入 CSV 写失败，旧文件内容和 mode 不变。
- 4 日期 byte-identical。
- 双隔离数据目录的持久化 canonical snapshot 等价。
- 全套测试。

### R2. 动态 health + 完整回执

**实施**

1. IBKR 每次 GET 按当前时间重算年龄。
2. scheduled receipt 改为 RUNNING/OK/FAILED。
3. 包住完整核心运行，而不只包 state commit。
4. health 合并今日 scheduled、manifest、soft SLO、IBKR、SIP。
5. 先修正 `/api/health_status`；`/livez` 与 `/readyz` 仅在不扩大 diff 时补充。

**验证**

- time-travel fixture：旧 `sync_time` 必须非 OK。
- scoring/artifact/diff/state 任一点抛错都留下 FAILED。
- 旧绿色回执不能盖住当日失败。
- SIP 失败为 DEGRADED，核心输出不被误判失败。
- 全套测试。

### R3. 部署互斥 + 精确 rollback

**实施**

1. stop/backup/swap/smoke 由一次 pipeline lock acquire 连续罩住。
2. rollback 用 `rsync --delete` 从完整备份恢复。
3. `.hermes` commit 失败成为 fatal。
4. selective add，仅代码、ops 入口和 VERSION。
5. 备份移到 git 外并只保留最近 5 份。

**验证**

- 在临时 live fixture 做失败注入，不碰真实 live。
- 部署前后对文件路径、SHA256、mode 做集合比较。
- 构造新增文件后失败，rollback 后新增文件必须消失。
- 构造 git commit 失败，脚本必须非零且没有 OK 文案。

### R4. 写端点分级鉴权

**实施**

1. 所有 mutating POST 要求 Host/Origin loopback。
2. `m4_golive` 和 `confirm_execution` 额外要求 `HERMES_CONFIRM_TOKEN`。
3. 其余数据刷新、重算和只读检查端点仅限 loopback，不要求 token。
4. busy 统一返回 409，不调用第二个 writer。

**验证**

- 危险 endpoint：无 token 403、错 token 403、正确 token 正常。
- 低风险 refresh：loopback 无 token 正常，非本机 Host/Origin 拒绝。
- busy 情形在鉴权后返回 409。
- GET 与静态页面不要求 token。

### R5. repo/live 边界清理

**实施**

1. NEXT5 只写 live runtime path。
2. 删除 live 到 repo `building/logs` 的写回。
3. `.hermes` ignore runtime DB、CSV、audit、order preview、reports、backup。
4. config 明确分层：repo 非敏感默认 + env/本机 secret overlay。

**验证**

- live 运行后 repo `git status` 不变。
- `.hermes` 部署 commit 的文件清单只有 allowlist。
- secret scanner 与运行数据路径测试通过。

### R6. versioned release 原子切换

状态：2026-07-01 已进入实施。设计为稳定 live 容器 + `releases/<hash>_<stamp>/` 版本目录 + `current`/`previous` symlink 原子切换；package `data/config` 与根 `data/reports/orders` 保持共享运行态，不随 release 回滚。入口脚本通过 `HERMES_RUNTIME_ROOT` 固定运行态根目录，避免代码物理位置进入 `releases/` 后把 state/report 写进版本目录。

---

## 5. 双 Agent A/B 轨并行方案

### 5.1 分轨原则

两个 agent 不共享工作区，使用两个 git worktree：

```bash
git -C ~/Documents/github/hermes worktree add \
  ~/Documents/github/hermes-agent-a -b codex/stability-a-runtime hermes-docs

git -C ~/Documents/github/hermes worktree add \
  ~/Documents/github/hermes-agent-b -b codex/stability-b-deploy hermes-docs
```

开始前两边都记录：

```bash
git status --short --branch
git rev-parse HEAD
```

两轨共同纪律：

1. 不改策略、flag 值和生产 config。
2. 不 deploy，不写真实 live，不启动全窗口回测。
3. focused tests 可各自运行；全套测试在同步点串行跑。
4. 不 `git add -A`，只 stage 自己的明确文件。
5. 一项一 commit，commit message 带任务号。
6. 发现对方所有权文件需要修改时，只写接口需求，不跨轨代改。

### 5.2 Agent A：运行时一致性 / 健康真相轨

### 文件所有权

- `src/hermes_escape_top/pipeline.py`
- `src/hermes_escape_top/cli.py`
- `src/hermes_escape_top/core/safe_io.py`
- `src/hermes_escape_top/ibkr/live_check.py`
- `src/hermes_escape_top/web/server.py`
- `src/hermes_escape_top/web/health.py`
- `src/hermes_escape_top/scripts/run_daily_package.py`
- `ops/run_daily.py`
- 与上述模块直接对应的测试文件
- 新增的 Python pipeline-lock exec helper

### A-1：写入图与失败测试

先只读审计并形成表：入口、是否写入、当前锁、预期行为。至少覆盖：

- daily scheduled/manual_rerun/deploy_verify
- Web 四类 refresh
- IBKR demo/live check
- CLI score/ibkr-live/dashboard/mirror-dashboard
- state DB、5 个 SQLite、audit、journal、manifest、receipt

先写能复现两个无锁 writer 的测试，确认修复前失败。随后在隔离 `HERMES_DATA_DIR` 冻结 13 个 persistence write-point 的 canonical baseline；这一步必须在事务重构前完成。

### A-2：唯一写事务

- 建立事务入口并用运行时 active lease 封闭 `_score_pipeline_locked`；helper 验证 capability、active、PID 和 thread owner。
- Web 使用 non-blocking acquire，冲突返回 409。
- daily/CLI 使用 bounded blocking acquire。
- 所有 IBKR 触发评分的路径改走事务入口；Web demo_snapshot/live_check 同样 non-blocking，冲突返回 409。
- 为 B 提供稳定的命令行 lock helper，接口示例：

```bash
python -m hermes_escape_top.scripts.pipeline_lock_exec \
  --archive-dir <archive> --timeout 600 -- <command...>
```

helper 成功时返回被包命令退出码；timeout 使用单独非零码；始终由 kernel 释放锁。

### A-3：原子写 mode

- 替换已有文件时继承其 `stat.S_IMODE`。
- 新 CSV 默认 0644，敏感文件按原约定保留 0600。
- 本批用“关闭 temp file 后 `os.replace`”解决撕裂读，并保留 mode；不要把 `fsync` 当成原子可见性的必要条件。
- 文件与父目录 `fsync` 属于断电耐久性策略，先做基准和风险评估，另开任务决定，不在本批静默增加每次写延迟。
- 修复 live 权限的命令只写进交付说明，未经人工确认不直接改 live。

### A-4：health 与回执

- scheduled receipt 状态机。
- 顶层异常覆盖 score、artifact、diff、state commit。
- IBKR 动态 age、scheduled receipt、SIP as_of 合并。
- 优先把 `/api/health_status` 做真；`/livez`、`/readyz` 不作为本节点完成条件。
- 明确 SIP auxiliary degradation。

### A-5：分级鉴权与 Web 状态码

- busy 统一为 409。
- 所有 mutating POST 校验 loopback Host/Origin。
- `m4_golive` 和 `confirm_execution` 无 token/错 token 返回 403；低风险 refresh 在 loopback 下不要求 token。

### A 轨交付证据

- 写入调用图。
- focused tests 命令和结果。
- 4 日期 byte-identical JSON。
- state/audit/journal/5 个 SQLite/snapshot 的 canonical persistence diff，含允许归一化字段清单。
- 全套测试结果。
- 给 B 的 lock helper 使用说明和退出码表。
- 未修改策略 payload 语义的 diff 说明。

### 5.3 Agent B：部署原子性 / 仓库隔离轨

### 文件所有权

- `scripts/deploy_to_live.sh`
- `ops/verify_live.sh`
- `src/hermes_escape_top/scripts/check_next5_unlock.py`
- deployment/ops 对应测试
- `.gitignore` 与部署 allowlist 文件
- `docs/PRODUCTION_RUNBOOK.md`
- 本计划后续状态更新

**禁止修改 A 轨文件。** 在 A-2 lock helper 合并前，B 只实现不依赖 helper 的部分，并把 lock 调用留在一个清楚的函数/步骤中。

### B-1：部署脚本测试化

把 live、repo、backup、`.hermes` 目录参数化，使部署流程可针对临时 fixture 测试。默认值仍指向现有路径，不能改变真实命令的用户体验。

需要的失败注入点：

- rsync 后失败
- smoke 失败
- dashboard restart 失败
- verify_live 失败
- `.hermes` commit 失败

测试不得碰真实 `~/.hermes`、launchd 或 8766。

### B-2：精确 rollback

- 备份必须保存完整代码树、VERSION 与 ops entry scripts。
- 恢复使用 `rsync --delete`，确保失败部署新增文件被删除。
- 恢复后比较路径集合与 SHA256 manifest。
- rollback 本身失败时输出双重故障，保留 backup 路径并非零退出。
- 脚本只允许一个成功出口打印 `deploy OK`。

### B-3：`.hermes` allowlist

禁止 `git add skills/investment/escape-top` 整树。改为明确 allowlist，例如：

- package Python 代码
- `ops/run_daily.sh`、`ops/run_daily.py`、`ops/serve_dashboard.sh`
- `VERSION`

明确排除：

- `data/`
- SQLite、audit、journal、position/order preview
- logs、reports、backup tar
- token/key/config secret overlay

`.hermes` commit 失败必须触发 rollback，并使部署返回非零。

### B-4：repo/live 隔离

- NEXT5 只写 live 路径。
- live 运行不得写 repo `building/logs`。
- 部署产生的软数据反同步不再进入 repo 工作树；需要研究快照时使用显式导出命令和独立目录。
- 更新 runbook，删除“live 是软数据 SSOT 并回写 repo”的旧描述。

### B-5：接入 A 的 lock helper

收到 A-2 后 rebase。部署脚本必须把以下步骤组织成一个内部 `locked-swap` 子命令，再用 helper **单次 acquire** 包住整个子命令：

- dashboard stop
- backup
- rsync/switch
- smoke

禁止对四个步骤分别调用四次 helper。步骤之间不得释放/重取锁。

在启动 dashboard 和执行 `verify_live` 前释放部署阶段持有的 lock。`verify_live` 自己通过正常 daily transaction 重新获取同一把锁。这样不会自死锁，同时任何 writer 只能在完整旧代码或完整新代码上运行。8766 在 stop 到 restart 之间短暂不可用是预期行为，必须写入 runbook。

rollback 也必须先 stop dashboard，再通过 helper 持锁执行精确恢复。

### B-6：versioned release 设计稿

本批只提交设计与迁移步骤，不与 B-1 至 B-5 一起上线。第一阶段稳定 3 个交易日后另开任务实现。

### B 轨交付证据

- 临时 fixture 的五类失败注入结果。
- 部署前后路径/SHA256/mode 对比。
- `.hermes` stage 文件 allowlist 输出。
- NEXT5 运行后 repo clean 证明。
- runbook 更新。
- 未触碰真实 live 的声明。

---

## 6. A/B 同步点与合并顺序

### S0：开工冻结

- 两个 worktree 基于同一 commit。
- 记录测试基线 517 passed。
- 暂停其他 agent 修改两轨所有权文件。

### S1：A 发布 lock contract

A 完成 A-1/A-2/A-3 后：

1. A focused tests 绿。
2. A 4 日期 byte-identical 通过。
3. A 提交 lock helper 使用说明。
4. B rebase A 分支或将 A 分支先合入 integration branch。

B 在 S1 前不得自行实现第二套锁。

### S2：并行成果汇合

建议合并顺序：

1. 合入 A 的唯一写事务与 safe I/O。
2. B rebase，接入 lock helper。
3. 合入 B 的 deploy/rollback/hygiene。
4. 合入 A 的 health/receipt/token。
5. 解决文档与测试计数漂移。

如果 A 的 server 测试和 B 的 verify 测试存在语义冲突，以以下规则裁决：

- official scheduled 记录只能由真实 scheduled run 写。
- deploy verify 必须 manual_rerun。
- Web busy 必须 409。
- mutating POST 按第 1.3 节的分级鉴权政策执行。
- SIP failure 只能降级，不得伪造核心失败或核心成功。

### S3：集成验收

按顺序执行，不并行：

1. focused runtime tests。
2. focused deploy fixture tests。
3. 全套 pytest。
4. compileall。
5. 4 日期 byte-identical。
6. 13 个 persistence write-point canonical diff。
7. 临时目录并发压力测试。
8. 临时目录 deploy + rollback 故障注入。
9. 人工 review diff。

S3 通过后才准备真实 live deploy，真实 deploy 仍由人类确认。

### S4：上线后观察

连续 3 个交易日检查：

- 每天仅一条 scheduled official run。
- receipt、state、audit 的 run_id 一致。
- IBKR/SIP 年龄随时间动态变化。
- 没有 200 BUSY。
- repo 和 `.hermes` 工作树无运行数据脏文件。
- daily 与 Web refresh 没有锁 timeout。

观察期内发现异常，只回滚本批，不继续 versioned release。

---

## 7. 验收测试矩阵

| 场景 | 预期 |
|---|---|
| 两个 Web refresh 同时提交 | 一个正常，一个 409 BUSY |
| demo_snapshot/live_check 遇到锁 | 409 BUSY，不进入评分写路径 |
| daily 已持锁，CLI score 启动 | CLI 等待或 timeout，不并发写 |
| deploy 切换中 daily 启动 | daily 等待；不接触半同步代码 |
| deploy backup/swap/smoke 之间 | 同一次 lock acquire，writer 无缝隙可进入 |
| 评分中进程 crash | kernel 释放锁，旧原子文件仍完整 |
| 原子 CSV 写失败 | 旧内容、mode 不变，无残留 temp |
| 重构前后同一输入 | 13 个 persistence write-point canonical snapshot 等价 |
| IBKR `sync_time=2026-01-01` | health 非 OK |
| 今日 scheduled scoring 抛错 | receipt=FAILED，退出码非零 |
| 昨日绿、今日失败 | 页面显示今日失败，不显示旧绿头条 |
| SIP 更新失败 | 核心 receipt 可 OK，health=DEGRADED |
| loopback 无 token 调低风险 refresh | 正常执行；非本机 Host/Origin 拒绝 |
| 无 token 调 `m4_golive` / `confirm_execution` | 403，handler 不执行 |
| 鉴权通过但锁被占 | 409，不执行第二个 writer |
| deploy 新增文件后 smoke 失败 | rollback 后新增文件消失 |
| `.hermes` commit 失败 | rollback，非零，无 deploy OK |
| verify_live | manual_rerun，不改 official state/receipt |
| NEXT5 live 运行 | repo `git status` 不变 |

---

## 8. 风险与回滚边界

### 8.1 最大风险

最大风险不是代码量，而是把锁放错层后产生两种假安全：

1. 新入口再次绕锁。
2. 外层已持锁，内层重新 open 同一 lock file 导致自死锁。

因此 A 必须用调用图和并发测试证明，而不是只搜索“有几处 `pipeline_lock`”。

### 8.2 每个节点的回滚

| 节点 | 回滚方式 |
|---|---|
| 写事务 | revert 单独 commit；恢复旧入口，不动策略配置 |
| safe I/O mode | revert mode-preserve commit；不改 CSV 内容 |
| health/receipt | revert UI/receipt commit；保留旧数据格式兼容读取 |
| token | revert auth commit；Host/Origin 仍保留 |
| deploy phase 1 | 使用部署前完整 backup `rsync --delete` 恢复 |
| `.hermes` allowlist | revert stage 规则，不删除历史 git 数据 |
| versioned release | symlink 切回 previous |

所有数据格式变更必须向后兼容至少一个 live 版本，避免代码回滚后读不了新 receipt。

---

## 9. 建议任务工期

以下是工程时间，不含等待人工 review 和 live 观察期：

| 轨道 | 任务 | 估时 |
|---|---|---:|
| A | 写入图 + 失败测试 | 0.5 天 |
| A | 唯一写事务 + persistence 等价 + 409 + safe I/O mode | 2-3 天 |
| A | health + receipt | 1 天 |
| A | token 政策落地 | 0.5 天 |
| B | deploy fixture + 精确 rollback | 1 天 |
| B | `.hermes` allowlist + NEXT5 隔离 | 0.5 天 |
| B | 接 lock helper + runbook | 0.5 天 |
| 集成 | S3 验收 | 0.5-1 天 |

两轨并行时，预计 **4-5 个工程日完成代码与集成验收**，随后观察 3 个交易日。A-2 是安全关键路径，不按原 1-1.5 天硬压。不要为了压缩半天而把 R1-R3 合成一个不可 review 的大提交。

---

## 10. 可直接交给两个 Agent 的 prompt

### Agent A prompt

```text
你是 Hermes Agent A，负责“运行时一致性 / 健康真相轨”。
仓库 worktree：~/Documents/github/hermes-agent-a，分支 codex/stability-a-runtime。

先完整阅读：
1. context.md
2. docs/history/2026-06-18_review_remediation.md 的 §2A
3. docs/history/2026-06-19_system_stabilization_ab_plan.md

你的文件所有权：pipeline.py、cli.py、core/safe_io.py、ibkr/live_check.py、
web/server.py、web/health.py、scripts/run_daily_package.py、ops/run_daily.py 及直接测试。
不得修改 deploy_to_live.sh、verify_live.sh、check_next5_unlock.py 和 B 轨文档。

按 A-1 到 A-5 顺序执行。先写调用图、13 个 persistence write-point 基准和失败测试，再修代码。
目标是 active lease 保护的唯一生产写事务、Web/IBKR busy=409、原子写保留 mode、动态 health、
完整 scheduled receipt。鉴权按第 1.3 节已定稿的 loopback 威胁模型实施。
不要改策略、flag 值或 config。不要 deploy，不碰真实 live。

A-2 完成后先交付 pipeline lock exec helper 的命令、退出码和 focused tests，作为 S1。
全部完成后提供：改动清单、4 日期 byte-identical、13 个落盘产物 canonical diff、
focused/full tests、残余风险。
每项一 commit，不 git add -A。
```

### Agent B prompt

```text
你是 Hermes Agent B，负责“部署原子性 / 仓库隔离轨”。
仓库 worktree：~/Documents/github/hermes-agent-b，分支 codex/stability-b-deploy。

先完整阅读：
1. context.md
2. docs/history/2026-06-18_review_remediation.md 的 §2A
3. docs/history/2026-06-19_system_stabilization_ab_plan.md

你的文件所有权：scripts/deploy_to_live.sh、ops/verify_live.sh、
scripts/check_next5_unlock.py、部署/ops 测试、.gitignore/allowlist、
docs/PRODUCTION_RUNBOOK.md。不得修改 Agent A 所有权文件。

按 B-1 到 B-6 执行。先把部署路径参数化，在临时 fixture 做失败注入；修精确 rollback、
.hermes selective commit、commit failure fatal、NEXT5 不回写 repo。不要碰真实 live、launchd、8766。

A 的 lock helper 未到位前不要自创第二套锁；只把接入点留清楚。收到 S1 后 rebase，
把 backup/switch/smoke 做成一个 locked-swap 子命令，用 A 的 helper 单次 acquire 包住整个子命令；
禁止每步分别 acquire。verify_live 在释放部署锁后按正常事务重新取锁。
每项一 commit，不 git add -A。

完成后提供：五类失败注入结果、文件集合/SHA256 rollback 证明、.hermes allowlist、
repo clean 证明、focused/full tests 和残余风险。
```

---

## 11. 最终优先级

必须先做：

1. R1 单一写事务。
2. R2 动态 health 与完整回执。
3. R3 部署互斥与精确 rollback。

随后做：

4. R4 分级鉴权政策落地。
5. R5 repo/live 边界清理。

最后做：

6. R6 versioned release 原子切换。

在 R1-R3 完成前继续扩展策略或 UI，会让系统“看起来更丰富”，但不会让输出更可信。当前最值得买回来的不是新功能，而是三个确定性：**同一时刻只有一个 writer、页面展示的是当前事实、失败部署真的能回到原点。**

---

## 12. 执行状态（2026-06-19）

已完成但尚未 deploy/commit：

- **R1 / A-1 至 A-3**：active lease 单一评分事务、daily/Web/IBKR/CLI/M4/8765 锁接线、Web busy=409、CSV 原子替换保留 mode、部署 lock exec helper。
- **R2 / A-4**：scheduled `RUNNING -> OK/FAILED` 回执、顶层失败红回执、旧绿回执失效、IBKR 动态 age、SIP auxiliary health、26 小时次日运行宽限。
- **R3 / B-1 至 B-5**：fixture 化部署、单次 fcntl lease、精确 rollback、`.hermes` allowlist、repo/live 数据隔离、NEXT5 仅写运行数据根、隔离数据上的真实入口 verify、runbook 更新。
- **R4 / A-5**：鉴权政策已按当前威胁模型定稿并同步到代码、测试、`context.md` 和 runbook。全部写端点限 loopback；`m4_golive` 与 `confirm_execution` 额外要求 token；其余低风险 refresh 不要求 token；对外暴露前必须全面升级鉴权。
- **行为证明**：4 个历史日期 payload/status/input_hash 与 6 个 canonical persistence artifacts 等价，报告为 `building/reports/pipeline_persistence_equivalence_2026_06_19.json`，`all_equal=true`。
- **验证**：pytest `562 passed, 1 warning`；隔离数据根的 `scripts/system_validation.py` 为 `28/28 pass`；4 日期持久化等价证明收紧 `payload_hash` 归一化后仍为 `all_equal=true`；shell syntax、Python compileall、`git diff --check` 通过。

交付边界：

- R1-R5 的代码、测试、行为证明和运维文档已闭环。R6 在 2026-07-01 的后续批次实施，真实部署验收以 `deploy_to_live.sh` 输出、`current` symlink、8766 版本和 `verify_live PASS` 为准。
- 本批未触碰 live、launchd、8766，也未执行真实部署或 git commit；需人工 review 后另开部署窗口。
