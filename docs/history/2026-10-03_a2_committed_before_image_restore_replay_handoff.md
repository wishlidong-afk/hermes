# A2: COMMITTED Before-Image Consumer and Isolated Replay

Date: 2026-10-03. Baseline: `ca7dda934b4433b1e88f77ce979fc54f08e36c0c` (`ca7dda9`).

**外审后状态更新：** 当前新增实现外审 PASS，允许提交/推送；不具备部署或 A2 闭合条件，A2 OPEN、Phase B not started。外审原文和 F1/F2 修正见第 7 节。第 1 节的“尚未外审”为初次成文的时点记录，不表示还需要重复同一实现审查。

## 1. Disposition and Scope

本批实现了一个离线前像恢复消费者，以及从非空旧状态执行真实评分管道的隔离重放演练。初次成文时作者验证通过，**本批当时尚未独立外审、未提交、未推送、未部署**。当前外审状态以文首及第 7 节更新为准。

**DEPLOY HOLD; A2 OPEN; Phase B not started.** 前一批联合外审批准的对象是已提交的 `ca7dda9`，不自动覆盖本批新增代码。前一批不存在第四道待批审批；本批是新的实现范围，需要单独审查。

本批实现范围为以下四个新增代码文件、三个新增证据文件、本文，共八条路径。外审后另原字节归档一份外审报告，只作文档证据，不是新增实现面。没有修改任何已有受跟踪文件。

| Path | Purpose |
|---|---|
| `src/hermes_escape_top/core/reporting/transaction_restore.py` | 新增离线 COMMITTED v2 前像恢复消费者，110 行 |
| `scripts/verify_a2_isolated_replay.py` | 新增仅临时目录内的真实管道重放演练，352 行 |
| `src/hermes_escape_top/tests/test_committed_before_image_restore.py` | 新增 32 个恢复用例，303 行 |
| `src/hermes_escape_top/tests/test_a2_isolated_replay.py` | 新增 6 个演练/负向/入口边界用例，79 行 |
| `building/reports/committed_before_image_restore/2026-10-03/replay.json` | 完整测试套件中产生的正向演练原始报告 |
| `building/reports/committed_before_image_restore/2026-10-03/negative_replay.json` | 完整测试套件中产生的反向对照原始报告 |
| `building/reports/committed_before_image_restore/2026-10-03/equivalence.json` | 对 `ca7dda9` 的四日期 strict 原始结果 |
| `docs/history/2026-10-03_a2_committed_before_image_restore_replay_handoff.md` | 本批交接和外审提示 |

以下既有未跟踪文件不属于本批，不得纳入提交：

- `docs/history/2026-09-05_dated_update_schedule.md`
- `docs/history/2026-09-05_post_release_a_20_dimension_review.md`
- `docs/history/2026-09-05_stabilization_update_plan.md`

`pipeline.py`、生产入口、事务协议、输入归档、身份/修订、评分、路由、config、flag、依赖锁、部署脚本、比较器均无修改。不建立新的生产 flag，也没有生产调用方。

## 2. Offline Consumer Contract

入口：`restore_committed_before_images(store, run_id, expected_journal_sha256, decision_id, input_hash, destination)`，所有参数为关键字参数。

### 2.1 Authentication and Refusal

1. `run_id` 必须为规范的小写 32 位 UUID hex。读取的 journal 必须来自该 run 的既有 v2 目录，路径检查复用 `checked_path`。
2. **先核外部传入的 journal 字节 SHA**。调用者必须从 bundle 之外取得这个锚；自动从同一份可疑 journal 计算摘要不提供真实性。
3. journal 必须为 v2、`COMMITTED`，run_id 必须一致。v1、pending、ROLLED_BACK、错误 run 均拒绝。
4. 复用 `validate_inventory` 的精确七业务文件/证据登记规则，以及 `validate_input_evidence` 的既有摘要、路径、binding 校验；不弱化协议。
5. 请求的 `decision_id`、`input_hash` 必须与 journal 的 input binding 相同。
6. `pre_state.json` 必须已登记，顶层字段集合、schema、capture mode、run/capture/as_of binding、七文件集合均精确匹配。
7. 每一条前像必须与权威 journal 的 `existed / snapshot_format / before_mode / before_sha256` 对齐。权限值须为整数而非 bool，且为合法 permission bits。
8. PRESENT 的路径必须是该 capture 下准确的 `pre_state/archive/<business-name>`，并已登记；摘要必须与 journal 的 before SHA 一致。
9. ABSENT 必须为规范形态，不建立空文件。全部 ABSENT 只表示经绑定的前态缺失，不证明首次安装。
10. 已登记的 `pre_state/` 集合必须恰好等于 PRESENT 集合；额外、未登记、缺失、换链的文件不得被恢复。

恢复 SQLite 时检查的是**冻结 SQLite backup**，以 `mode=ro&immutable=1` 读取，复用完整 integrity/逻辑状态检查。不是拿 live main 文件忽略 WAL；不是把 backup SHA 宣称为原主文件字节 SHA。JSON/JSONL 做对象语法校验，不声称验证所有业务字段语义。

### 2.2 Output and Side Effects

所有来源核验成功后才准备目标；目标必须是新目录，不能是已有文件/目录/悬空链接，也不能位于 source data、history、legacy history 根内。

输出布局：

```text
<new-destination>/                     mode 0700
  archive/<PRESENT business files>     mode 0600
  source_transaction.json             mode 0400
  restoration.json                    mode 0400
```

`restoration.json` 明确标记 `OFFLINE_BEFORE_STATE_NOT_FULL_REPLAY`，保留原 journal SHA 和决策 binding。输出业务文件统一 0600，不声称恢复其原权限；原权限仍在证据里。

同父目录 staging 后 `os.rename` 发布，异常清理 staging。验证失败不创建目标；发布异常不会改 source。消费者不改 canonical、原业务状态、journal、active pointer，也不自动恢复 pending 事务。

限制：SHA 是外部绑定而非签名；不是同用户恶意并发的安全边界。沿用既有目标根保护，未新增全机写入禁区/全部祖先链接防御。没有父目录 fsync、SIGKILL/断电实验、超大档案内存基准。业务内容先完整读入内存；不声称已解决大文件成本。

该 API 依赖 Hermes 包及既有 reporting/SQLite helpers；不宣称 `/usr/bin/python3` 标准库环境即可独立消费。既有协议校验还要求当前 source store 的业务路径满足其检查，因此不是任意脱离原 store 的 bundle 导入器。

## 3. Real Pipeline Replay: What Was Actually Exercised

### 3.1 Sequential Isolated Workers

演练只在系统临时目录创建私有根，结束时删除。输入只读复制 history、soft_history、legacy_history，不复制真实 archive、账户或持仓。**seed 选择继承 `HERMES_DATA_DIR`；未设置时才使用当前包目录。** 如果该环境变量指向 live shared，则旧命令会只读复制 live 的上述三个数据目录；不写 live，但这不是本批外审应采用的输入。禁止网络，worker 中拦截 `socket.connect / connect_ex / create_connection`，记录尝试次数；任何尝试都使演练失败。

本次冻结正/负向报告来自完整 pytest 套件；子进程继承 `tests/conftest.py` 创建的 session 数据副本（Git-tracked package data 加 test fixtures）。独立 CLI 默认当前包数据目录，不保证与该副本同字节。报告未登记机制演练所复制 seed 的完整文件 manifest；其中 `source` 是源码指纹，`input_manifest_sha256` 是事后归档输入的摘要，均不能代替 seed 指纹。四日期 comparator 另有 77 文件 seed manifest，但不证明机制演练用了同一份 seed。

第 5.1 节独立 CLI 命令现显式固定仓库内数据根，并在运行前回显仅上述三个目录的 seed 指纹。运行后应复查该指纹未变。该说明不追补旧报告缺失的输入证据，不修改演练器，也不将某次新演练当成旧报告的同输入复现。若要统一测试/CLI 的可复现 seed，应作为后续独立实现并重新审查。

顺序运行三个独立 Python 进程：

1. `seed`：在隔离 source 执行真实 `score_pipeline`，2026-05-28，manual_rerun，关闭 IBKR 读取，建立实际非空旧状态。
2. `reference`：在 source 数据副本执行真实 scheduled `score_pipeline`，2026-05-29，用模拟 broker 只读返回值，记录实际 soft adapter 返回值。
3. `replay`：恢复 COMMITTED fixture 的七前像，恢复匹配的历史输入，再执行同日真实 scheduled `score_pipeline`，从记录的返回值供给 soft/positions/executions 三个读取端口。

`scheduled` 仅发生在隔离目录，不是 live 官方补跑。四个 SQLite 都具有实际用户表数据，audit 非空；并非从空库或仅有 schema 起跑。七个前像槽位中当日 dated soft snapshot 可以是 ABSENT，不宣称七个文件运行前都存在。

沙箱配置只为覆盖只读路径启用 `ibkr.enabled`、`ibkr.executions.enabled`；这些是临时配置文件里的 override，未改生产 config/flag，readonly=true 保留。所有账户和 execution ID 都是 `OFFLINE-SYNTHETIC` / `OFFLINE-FILL` fixture，source=tws 是用于真实分支选择的 fixture 字段，不表示连接过网关。

### 3.2 Important Boundary: The v2 Producer Is Still a Fixture

真实评分**不在本批 fixture v2 事务内执行**。source 的外层 v2 事务导出前像；reference 在另一个副本里真实评分；其七业务输出被复制回 fixture source，登记并绑定测试输入证据，再 COMMITTED。

这个 fixture 顶层清单使用协议要求的 `IN_RUN_CAPTURE` 字段，是为了验证消费者能识别协议；**不是生产 in-run consumption 证据**。演练报告明确：`production_capture=false`、`ISOLATED_MECHANISM_REHEARSAL_NOT_PRODUCTION_CAPTURE`。

历史/config/快照恢复继续用既有 `archive_decision_inputs` 和 `restore_decision_inputs`，其模式为 `RETROSPECTIVE_AS_OF_MATCH`。没有偷偷将事后归档改称原运行消费的输入。生产 pipeline 仍未接入本批 v2 producer 或消费者。

### 3.3 Compare Contract and the Red/Green Findings

评分、路由、reentry、实际持久化函数均未 mock；只 mock 外部读取端口与评分墙钟。reference/replay 的评分墙钟固定为 `2026-05-30T00:10:00+00:00`。

比较器未改，复用其 strict 规范化与七业务产物快照。对 reference/replay 统一应用预先定义的三个沙箱根归一化，处理旧状态和 taped provenance 中保留的 source/reference 路径。没有失败后回退到更宽松模式，没有新增字段忽略项。

比较全部 normalized payload、四个 SQLite 的 schema/列/行/值、两份 JSONL 的顺序/对象、当日 soft snapshot。它不是全部文件原始字节逐一相等的承诺；既有 volatile 字段和临时路径规则仍由 unchanged comparator 定义。

TDD/调查中实际捕获的问题：

- 未实现 API/脚本时，新测试先失败。
- scheduled fixture 缺少真实行情清单时，认证按设计拒绝；补入隔离输入原有 frozen manifest，不绕过认证。
- 一度只有 input_hash 相同而 strict payload 不同。原因是保存 soft 返回值时排序了字典，改变数据质量解释中的顺序选择。修复限定在 tape 序列化：保留原字典插入顺序。没有忽略相关 payload 字段或改生产计算。
- `--probe-net-liq-change` 只把记录中的模拟净值加 1000；即使行情 input_hash 仍相同，也必须 FAIL 并指出业务差异。

本次真实 execution_sync 结果为 **NO_MATCH**。原始 executions reader 返回值和实际同步代码被走到，但**没有据此声称成功自动确认分支已获本批完整重放证明**。

## 4. Verification Results

全部顺序执行，未并行。最终源码状态与下表验证状态一致；之后只添加本文和机械复制原始结果。

| Check | Actual result |
|---|---|
| 新增恢复测试 | 32 passed |
| 新增演练测试 | 6 passed，含三个 worker 模式拒收和一个预期 FAIL 对照 |
| 旧六文件 + 新两文件 focused | **205 passed, 28.57s** |
| 全套 | **1748 passed, 177.89s**，1710 + 38 |
| Governance | **8/8 OK**，ibkr_readonly=true |
| 新四文件完整 Ruff 0.15.22 | PASS |
| 全仓严重错误 E9/F63/F7/F82 | PASS |
| 新模块/脚本 + CI 四模块 mypy 2.3.0 | PASS，6 files，无新增 ignore/exclude |
| compileall src/scripts/ops | PASS，bytecode 写 tmp |
| 隔离环境依赖检查 | PASS，62 installed packages compatible；lock 仍 32 包，未改 |
| 四日期 strict 对 ca7dda9 | **all_equal=true，4/4 equal，strict_differences=[]** |

评分指纹仍为 `03b94995fba06e849eef7468d1ba3e9f67bd8038296dfd8cf0e47a694533ad73`。没有扩大已有排除集、追加 A1 migration release 豁免、扩修订预算或改比较器。reporting/scripts/tests 原本即处于现有指纹排除范围。

### 4.1 Frozen Positive and Negative Results

三个 JSON 从本轮实际 tmp 输出原字节复制，没有重排或重写。它们是生成结果，必须审源和独立重跑，不能把报告本身当独立正确性证明。

独立重跑会生成新的 run UUID、临时目录、journal 时间和 PID，因此整份报告/fixture journal SHA 不要求跨次相同。应核本次冻结报告与登记 SHA、各自源码绑定、已实际登记的 seed 绑定及真实比较结果，不把自然变化的运行标识当可复现性失败；没有 seed manifest 的旧机制报告不得被推定为同输入复现。

**外审后更正：** `normalized_reference_sha256` 和 `normalized_replay_sha256` 仅是本机、本轮快照的记录，用于核对同一次演练的两侧是否相等，**不作为跨环境重跑的固定摘要或外部真实性锚点**。外审复跑的两侧均为 `0d83736172a5fd4b4ed5987c6e5f9d2cccaa3579dc05e4024721d2a7dc06fa84`，与作者下面登记的 `c8ba2bf7...` 不同，但各轮 strict_differences 均为空。现有材料没有证明两次机制演练消费了相同的 seed，也没有定位全部跨轮差异字段；不能直接归因于某个环境变量或某台机器。不得为追求跨轮摘要一致而追加比较器忽略项。

第 4.2 节的文件 SHA 仍用于核对冻结文件是否被改动；四日期 comparator 的 seed manifest 仍绑定该次四日期输入。它们与机制演练的本轮快照摘要不是同一类证据。

正向报告：

- status=PASS；artifacts_compared=7；strict_differences=[]。
- nonempty_pre_state=true，source_unchanged=true，replay_transaction_status=COMMITTED。
- reader_calls：soft_data=1 / positions=1 / executions=1；network_attempts=0。
- 三个 worker PID 各异：10408 / 10412 / 10422。
- normalized reference/replay SHA 本轮都为 `c8ba2bf7715ba212c5b306777fa4b2393cbffba0dacbf3418e12223bef11165d`；仅记录这一轮，不要求外审重跑得到同一个值。
- source fingerprint 登记 358 个文件；含本脚本和 requirements.lock。不是 runtime 全档案。

反向报告：

- status=FAIL，**这是负向对照成功的预期结果**。
- input_hash_equal=true；strict_differences=`payload / artifact:audit_log.jsonl / artifact:hermes_state.sqlite`。
- 具体差异路径包括 target_notional / target_shares / portfolio_value；没有只比较 input_hash 就判通过。
- source_unchanged=true，network_attempts=0，reader 三端口各调用一次。

四日期严格对比：

| as_of | Baseline and candidate input_hash |
|---|---|
| 2022-01-03 | `71e82be53a877500b2ce09ac6539ff048e90d7054a16d219450810bce9c28f9b` |
| 2022-01-25 | `7468df38dae70a3c309a4b553c9123e0543714f7ad3cf587f39f48614d915545` |
| 2026-05-29 | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` |
| 2026-06-04 | `03ea60f73228a178435cfb131942b18bcefded7409f602c0acf20961bef53930` |

四日期报告的基线源码 353 文件、候选 356 文件；此比较器的 fingerprint 清单不包含新增演练脚本，与演练报告显式登记脚本/lock 的 358 文件口径不同。两份清单各自可复算，不混称数量。

seed 77 文件，manifest SHA `c119ae18b453b0e6838629c5af5c377cd4b2aa209aba84002c92303320455c99`；基线 manifest `be4757048bcf74e909580c2a9b8b4880a61b472da9b81a1a20ed8ef19e4f9f99`；候选 manifest `d913719352e01dd2634be3c89c1cf3b2fb6d8071b71c9011dccfe710ddf840ac`。

### 4.2 SHA-256 Inventory

```text
a8f466ee535ec1ae658dced2fe7e74defd16e05788c0c6ea7870df7a036ea601  src/hermes_escape_top/core/reporting/transaction_restore.py
2fe12046c43a37c838c952f97178bbf418847d7194ae97ede05273b9464b5071  scripts/verify_a2_isolated_replay.py
354e346f1c6406a4afc872b8c374cc963fc9b0b09e932105d667041894f44051  src/hermes_escape_top/tests/test_committed_before_image_restore.py
dbcf2d89df6e8032f5fd48ed9007bec5eee377f285c7c89e27920061b7dee9ef  src/hermes_escape_top/tests/test_a2_isolated_replay.py
fbe47776f4a1fb22dfa8a31f2b2f8bb3fb3d60bb9f58693f5e70d039b097970b  building/reports/committed_before_image_restore/2026-10-03/replay.json
9a8c059f5e0b064867be74fbfb80daca74ae4fd1a668c4c999bc4bfa35dfeac2  building/reports/committed_before_image_restore/2026-10-03/negative_replay.json
57a4d8b4bb951ccd9b32c6d9c84e33da4fe6f0c69c552927e698eeb05c87b372  building/reports/committed_before_image_restore/2026-10-03/equivalence.json
19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d  scripts/compare_pipeline_persistence.py (unchanged)
```

旧六份冻结 JSON 不变：history_versions、decision_inputs、pre_run_state、score_transaction_v2 的 equivalence、legacy_writer_probe、transaction_before_images 的 equivalence。旧正文和历史判定不覆盖改写。

## 5. Independent Audit Prompt

请在 `/Users/liweishi/Documents/github/hermes` 对 **ca7dda9 -> 当前工作区**做只读独立外审，包含未跟踪文件。先确认第 1 节八条范围及第 4.2 节 SHA，再逐行审消费者、演练器和测试。不能仅以本文或三个生成 JSON 判定通过。

安全纪律：不 commit/push/deploy；不运行 daily、晨验或真实刷新；不连接 IBKR；不改 live/shared、canonical、config、flag、身份迁移映射或比较器。所有演练只用新临时目录，按顺序运行。不要把三份九月文档纳入范围。

必须分别回答：

1. 外部 journal SHA、COMMITTED/v2/run/decision/input binding 是否在输出创建前全部强制？来自 bundle 自算摘要是否被诚实定义为不提供外部真实性？
2. 元数据重新锚定后，错格式、错权限、ABSENT/PRESENT 不一致、缺/额外条目、路径穿越、digest mismatch 是否仍拒绝？
3. 原文件/整个 evidence bundle/journal 换链、未登记文件、坏 SQLite 是否拒绝，不留目标或 staging？
4. 真 WAL 已提交行是否出现在恢复 backup 中；是否避免把 live main 当 immutable 来漏读 WAL？
5. 恢复是否只写新目标，保护原数据根/已有目标/悬空链接，发布异常是否无 source 改动？权限是否如声明而非假装还原原权限？
6. 三个 scoring worker 是否独立进程且真实非空前态？是否只有读取端口/墙钟被 mock，而非评分/状态写入？
7. 字典顺序是否保留；三个根归一化是否固定且两边一致；比较器和字段忽略集合是否确实未改？
8. 只改变 broker 净值是否令全 payload/相关业务产物失败，即使行情 input_hash 仍相同？
9. v2 producer 是否明确为 fixture，历史输入是否仍 retrospective，NO_MATCH 是否没有冒充 successful auto-confirm 分支覆盖？
10. worker 和 CLI 目标是否拒绝非演练根/非新临时输出，网络尝试是否 fail-loud？有没有生产调用方或 live 写入？
11. 205/1748、治理、静态、四日期和源码/seed/comparator hashes 能否独立复算？旧六份证据是否未变？
12. 是否仍区分离线消费者、机制重放、生产输入绑定、源码/runtime 归档、发布迁移与自然观察，保留 DEPLOY HOLD / A2 OPEN / Phase B not started？

### 5.1 Suggested Commands

使用 Python 3.11 和匹配锁文件的隔离环境；作者解释器路径只是本机当前存在的验证环境，不是跨机器安装保证。

```sh
cd /Users/liweishi/Documents/github/hermes
PY=/tmp/hermes-urllib3-tests-20261002/bin/python
git status --short --branch
git diff HEAD --stat
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests/test_transaction_before_images.py \
  src/hermes_escape_top/tests/test_score_transaction_v2.py \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  src/hermes_escape_top/tests/test_evidence_anchor_retention.py \
  src/hermes_escape_top/tests/test_runtime_retention.py \
  src/hermes_escape_top/tests/test_committed_before_image_restore.py \
  src/hermes_escape_top/tests/test_a2_isolated_replay.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" scripts/check_governance_consistency.py
"$PY" -m ruff check --no-cache \
  src/hermes_escape_top/core/reporting/transaction_restore.py scripts/verify_a2_isolated_replay.py \
  src/hermes_escape_top/tests/test_committed_before_image_restore.py src/hermes_escape_top/tests/test_a2_isolated_replay.py
"$PY" -m ruff check --no-cache --select E9,F63,F7,F82 src/hermes_escape_top scripts ops
env PYTHONPATH=src "$PY" -m mypy --cache-dir=/tmp/hermes-a2-consumer-external-mypy \
  --ignore-missing-imports --follow-imports=skip \
  src/hermes_escape_top/core/reporting/transaction_restore.py scripts/verify_a2_isolated_replay.py \
  src/hermes_escape_top/core/data/market_witness.py src/hermes_escape_top/core/data/market_admission.py \
  src/hermes_escape_top/core/backtest/formal_gate.py src/hermes_escape_top/web/health.py
env PYTHONPYCACHEPREFIX=/tmp/hermes-a2-consumer-external-bytecode "$PY" -m compileall -q src scripts ops
git diff --check
```

直接机制/负向重做可以省略 `--output`，避免覆盖既有证据。**必须显式固定 `HERMES_DATA_DIR`，不得继承可能指向 live 的 shell 值。** 先回显 seed 指纹并保留在自己的取证记录里；两次运行后再运行同一指纹命令确认输入未变。此处使用当前仓库 seed，不承诺它等于已冻结的 pytest 运行输入。负向命令退出码 1 是预期，须审具体差异，而非泛化为执行失败：

```sh
SEED_ROOT=/Users/liweishi/Documents/github/hermes/src/hermes_escape_top
env PYTHONDONTWRITEBYTECODE=1 HERMES_DATA_DIR="$SEED_ROOT" "$PY" - <<'PY'
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("existing_comparator", "scripts/compare_pipeline_persistence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
seed = (Path(os.environ["HERMES_DATA_DIR"]) / "data").resolve()
fingerprint = module._tree_fingerprint(seed, relative_roots=("history", "soft_history", "legacy_history"))
print(json.dumps({"seed_root": str(seed), "scope": fingerprint["relative_roots"],
                  "file_count": fingerprint["file_count"],
                  "manifest_sha256": fingerprint["manifest_sha256"]}, indent=2))
PY
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HERMES_DATA_DIR="$SEED_ROOT" \
  FRED_API_KEY=hermes-review-synthetic-key \
  "$PY" scripts/verify_a2_isolated_replay.py
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src HERMES_DATA_DIR="$SEED_ROOT" \
  FRED_API_KEY=hermes-review-synthetic-key \
  "$PY" scripts/verify_a2_isolated_replay.py --probe-net-liq-change
```

四日期重做使用新目录，不使用候选作为基线，也不覆盖冻结 JSON：

```sh
BASE=$(mktemp -d /tmp/hermes-a2-consumer-external-baseline.XXXXXX)
git archive ca7dda9 | tar -x -C "$BASE"
env PYTHONDONTWRITEBYTECODE=1 FRED_API_KEY=hermes-review-synthetic-key \
  "$PY" scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASE" --candidate-source /Users/liweishi/Documents/github/hermes \
  --seed-data /Users/liweishi/Documents/github/hermes/src/hermes_escape_top/data \
  --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 \
  --python "$PY" --contract strict --baseline-label ca7dda9 \
  --candidate-label external-a2-consumer-replay --output /tmp/hermes-a2-consumer-external-equivalence.json
```

请给出三个独立判定：代码正确性、允许提交/推送、是否具备部署/A2 闭合条件。**不可把第一项 PASS 自动转成部署授权。**

## 6. Remaining Work Before A2 Can Close

- 真实生产入口提前声明/准备 v2 事务，并在各读取端口消费时绑定历史、soft、config、认证材料、broker 返回值；需要新的设计/迁移及故障注入审查，不能简单塞入本演练 fixture。
- 真实 source/runtime/依赖归档；本批只有 source hashes，不是可独立恢复的代码或解释器档案。
- 将真实 COMMITTED 外部锚与 run/decision/input bundle 纳入实际运行和 retention 链，并审恢复旧 writer/缺证据/中断边界。
- 多状态、多日期、successful auto-confirm 等完整分支重放；当前真实评分样本只覆盖一个日期和 NO_MATCH 同步结果。
- A1 新指纹发布/迁移证明、单次 R6 发布授权和自然运行观察。这里没有读取或更改 live，也没有自然线上样本。

下一步先外审本切片。通过后再单独设计生产接线和归档，不把沙箱结果当完整 A2 或 Phase B 放行。

## 7. External Audit Disposition and Follow-Up

2026-10-03 独立外审已覆盖本批实现和第 5 节十二问，判定：**正确性 PASS；允许提交/推送；DEPLOY HOLD；A2 OPEN；Phase B not started。** 第 6 节最后一句保留初次成文时的下一步记录；同一实现外审已经完成，后续新增生产接线仍需另行审查。

外审原文：`docs/history/2026-10-03_a2_committed_before_image_restore_replay_external_audit_report.md`。从用户提供附件原字节复制，未改正文、未补标题或换行。SHA-256：`6ec2aac6c341ef58b9493a5f8d95194c2149cd5db706f82ee9b9837462240cbb`。

外审报告的 205 focused / 1748 full / 8/8 governance / 四日期 strict 结果为外审员独立取证。本次处理反馈没有冒称重新执行该全量组合；八项原声明 SHA 再核均与第 4.2 节一致，代码和冻结 JSON 没有改动，因此先前与外审的对应验证仍适用。

逐项处理：

| Finding | Disposition | Verification |
|---|---|---|
| F1：两侧 normalized SHA 不可作为跨轮固定锚 | 文档已修正，限定本机/本轮；不改代码/归一化/忽略项，不声称已定位所有跨轮差异成因 | 直接读取作者/外审报告，各轮两侧相等、strict_differences=[]，跨轮值不同 |
| F2：机制演练继承可变 HERMES_DATA_DIR，未记录 seed manifest | 文档已明确实际选择规则和缺失证据；独立 CLI 固定非 live 根，回显并复查 seed 指纹 | 顺序执行当前仓库 seed 的正/负向演练；不追补旧报告的 seed，不声称同输入历史复现 |
| F3：不可达畸形路径可能抛 KeyError | 接受的错误类型观察，不改代码 | 既有协议在正常流程提前强制精确集合；KeyError 仍 fail-closed，外审未发现可绕过路径 |

本次显式 seed 为仓库包内 `data`，scope=history/soft_history/legacy_history，77 files，manifest SHA `c119ae18b453b0e6838629c5af5c377cd4b2aa209aba84002c92303320455c99`。正向 PASS；reference/replay 两侧 SHA 均为外审登记的 `0d83736172a5fd4b4ed5987c6e5f9d2cccaa3579dc05e4024721d2a7dc06fa84`；网络尝试 0，七产物比较无差异，source 未变。负向按预期 FAIL，实际检出 payload/audit/state 差异、input_hash_equal=true；网络尝试 0，source 未变。前后 seed 指纹复查一致。

本次临时取证报告为 `/tmp/hermes-a2-reviewed-seed-positive-20261003.json` 和 `/tmp/hermes-a2-reviewed-seed-negative-20261003.json`；它们不是不可变归档，也不替换第 4.2 节已冻结报告。

这两次新增取证只写新临时目录及 `/tmp` 报告，未替换前三份冻结 JSON。未运行 official daily、真实刷新、晨验或连接 IBKR；未修改 live，未执行 Git add/commit/push/deploy。下一步可以按精确清单提交本批及文档状态更新；这是代码冻结，不是部署或 A2 结案。
