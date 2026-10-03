# A2 第三切片 3B：事务 v2 / 证据锚点 / WAL 恢复 / 只读验收

日期：2026-10-03。基线：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`，分支 `hermes-docs`。本文记录 **3B 收尾时点的累积工作区**，不是已提交的新版本。后续保留保护补丁及其证据见第 9 节，不把历史源码 SHA 当成最新源码。

## 1. 结论与边界

**3B 协议原语及隔离验证完成，待独立外审；没有生产 v2 接线，没有提交、推送或部署。A2 OPEN，Phase B 不启动。**

本批实现：显式选择 v2 的评分事务、七业务文件与证据文件分角色登记、最终输入清单的外部摘要锚点、SQLite/WAL 前像恢复、真实 SIGKILL 后下一进程恢复、COMMITTED 后清理失败不回滚、晨验的 v2 只读核验。

没有实现：真正读取点的自动输入捕获、提前生产事务边界、实际 IBKR 返回值冻结、完整源码归档、非空旧状态下的完整 pipeline 重放、A1 新指纹发布证明、自然线上样本。测试中的 `IN_RUN_CAPTURE` 是调用方提供的协议标记，**不是已证明生产消费了所存输入**。

默认调用仍用 v1；`pipeline.py` 未改、未向它传入 v2 参数。现有生产 v1 的主文件复制/WAL 边界未因此解决。不能把“新增 v2 支持 WAL”写成“所有生产 writer 已支持 WAL”。

## 2. 本批范围

下面路径相对仓库 `/Users/liweishi/Documents/github/hermes`。

| 文件 | 本批修改 |
|---|---|
| `src/hermes_escape_top/core/data/run_transaction.py` | 扩展既有事务，v1 默认保留；v2 选择、绑定、恢复、提交边界 |
| `src/hermes_escape_top/core/data/transaction_evidence.py` | 新增 124 行、仅标准库的角色/集合/路径/摘要校验 |
| `src/hermes_escape_top/core/data/sqlite_snapshot.py` | 新增 65 行共享 SQLite 逻辑备份原语，来自此前 3A 实现 |
| `src/hermes_escape_top/core/reporting/decision_inputs.py` | 3A 的两个 SQLite 私有函数提取到上述共享模块，通过别名保留调用契约；现为 376 行 |
| `ops/morning_acceptance.py` | 只读支持 v2，按当前 release 的标准库校验模块检查，不改变 v1 七文件规则 |
| `ops/prune_runtime_artifacts.py` | v2 active 指针读真实 v2_run_id，保护未清理的 COMMITTED；非法 guard/ID、journal namespace 链接拒绝；删除前复查 |
| `src/hermes_escape_top/tests/test_score_transaction_v2.py` | 新增 33 个用例 |
| `src/hermes_escape_top/tests/test_transaction_v2_acceptance.py` | 新增 19 个用例 |
| `src/hermes_escape_top/tests/test_runtime_retention.py` | 新增 7 个用例，旧 5 项保留 |
| `building/reports/score_transaction_v2/2026-10-03/` | 新增 `equivalence.json`、`legacy_writer_probe.json`；无实际状态 bundle |
| 本文、3A 交接的后续时间注 | 范围、证据、限制与外审指引 |

已有且不算本批新增：backfill/history_versions 接线、离线输入归档、3A 前态归档、14 项设计边界测试及其证据/交接。工作区没有被清理或伪装成干净 HEAD。

零 diff：`pipeline.py`、`decision_identity.py`、`decision_revision.py`、config/flag、评分/路由、依赖、比较器、部署脚本。三份 `2026-09-05_*` 未跟踪计划文档未改，也不得混入本批提交。

## 3. 协议契约

### 3.1 显式 opt-in 与精确清单

`score_run_transaction(..., evidence_artifacts=..., capture_id=...)` 两项必须一起提供；缺省两项即 v1。v2 只接收 `run_type=scheduled`、`shadow=False` 与精确 ISO 日期。

业务文件必须恰好是：

```text
archive/hermes_state.sqlite
archive/reentry_state.sqlite
archive/mirror_reference.sqlite
archive/flow_reference.sqlite
archive/audit_log.jsonl
archive/signal_journal.jsonl
archive/soft_adapter_snapshot_<as_of>.json
```

业务行角色为 `BUSINESS`。证据行角色为 `DECISION_INPUT_EVIDENCE`，必须是新的 `archive/decision_inputs/<capture_id>/` 内逐文件登记，含 `manifest.json` 及至少一个内容文件。capture_id 为标准 32 位 UUID hex；既存 capture 目录（即使为空）、既存证据文件、重复、未知角色、越界、符号链接均拒绝。允许 R6 数据根本身通过链接指向物理 shared 根，但不允许其内部文件/目录链接冒充。

登记在业务写入前完成。v2 journal 私有目录 0700；前像文件 0400。进入上下文后建立属于本次的全新 capture 目录。

事务 namespace 的 `.score_run_transactions`、`runs`、run 目录及 manifest/active 路径不接受内部符号链接；悬空 active 链接不是“无事务”。路径校验也供 v1 journal 的读写使用，因此默认协议仍 v1，但不能声称对所有畸形路径的旧行为完全不变。物理数据根内部 `loop → data` 的自指别名会拒绝；真实 R6 根 alias 的正向用例保留。

### 3.2 最终清单与外部锚点

调用方写好所有业务/证据文件后，调用 `bind_score_run_inputs`：必须持有当前根有效 lease，且 transaction/capture_id 对应仍 PENDING 的 v2 journal，不能重复绑定。

输入清单 schema 为 `hermes-in-run-input-binding-v1`；`capture_mode=IN_RUN_CAPTURE`；`binding` 精确包含本次 `run_id/capture_id/as_of/decision_id/input_hash`。`files` 逐个列出登记的内容文件及 SHA256，不包含 manifest 自己的摘要，避免循环。

外部摘要保存在 journal 的 `input_binding.manifest_sha256`；每证据行记录 `after_sha256`。绑定与退出前均重新检查：manifest 字节 SHA、身份、内容 SHA、精确文件集合、业务文件存在性和普通文件属性。少文件、额外文件、变更或链接拒绝。只有成功写入 COMMITTED 后，journal 才是本次成功证据锚点；PENDING 内的绑定、目录完整或 manifest 存在均不代表成功。

**这层只验证协议和字节绑定，不证明捕获时点或业务内容语义。** 业务 SQLite 的 schema/记录、JSONL 链条及实际消费输入由未来生产者/既有业务验证负责。成功 fixture 使用部分合成业务字节，不伪装成一次真实 scheduled pipeline。SHA 不是签名，权限不是 WORM。

### 3.3 WAL、回滚与提交边界

v2 对既存 SQLite 使用只读连接与 `Connection.backup()`，核对 integrity、schema/列、类型化记录（含重复行、隐式 rowid、NUL/BLOB/浮点）、数据库属性，保存已提交 WAL 中的数据。不使用 `immutable=1` 读取源，不静默 checkpoint 或改变源 journal_mode；可能产生/更新 SHM 等 SQLite bookkeeping。

`decision_inputs.py` 与事务共用此原语，避免 data 反向依赖 reporting。恢复前预检**所有**目标路径、前像 SHA、权限及与文件后缀对应的备份格式；任何前像坏/路径不可信先拒绝，不能恢复一半后才发现第二文件坏。备份格式误标为 BYTES 的 SQLite 也拒绝。

未提交时：普通异常恢复旧业务状态，移除新证据文件及本次新 capture 目录；SIGKILL 遗留 PENDING 后由下一持锁进程恢复。SQLite 恢复的是逻辑前像，可能不与旧主文件物理布局相同；移除 sidecars、原子替换备份、保留原文件权限。合法 writer 必须服从共同 lease，不承诺外部仍打开旧 DB 连接时替换安全。

坏前像/路径篡改等无法安全恢复时保留 PENDING 并报 `PersistenceRecoveryError`，等待取证，不猜测或伪造成功。恢复过程再次中断可用保留的前像重试。

**COMMITTED 是不可反向跨越的边界。** 提交发布异常会重读 journal：仍未提交则回滚；已 COMMITTED 不回滚；无法判定则保留 journal、失败上报。COMMITTED 后清 active/删临时备份失败，下一进程只清理，不倒退业务和证据。

文件有 fsync、原子替换和目录同步尝试。v2 在发布 COMMITTED 前还对实际存在的 SQLite `-wal` / `-journal` 同步，并校验 sidecar 路径，不能仅同步主文件就忽略仍在 WAL 内的已提交行。目录同步沿用既有尽力策略；本批证明的是进程崩溃恢复，**不承诺断电/文件系统故障下的完整耐久事务**。

### 3.4 旧 writer 的未完成事务守卫

v2 active pointer 存储实际 `v2_run_id`，并把旧 writer 读取的 `run_id` 设为保留的 `V2_REQUIRES_UPGRADED_WRITER`。新 reader 识别 schema、严格验证守卫并读取实际 manifest；旧基线代码会在不存在的守卫 manifest 处失败，而不是按 v1 对 v2 WAL 前像做错误恢复。

用真实 `git archive` 的 HEAD 代码在另一进程独立取证：旧代码 `FAIL_CLOSED`，档案 SHA 集合不变；新代码随后 `RECOVERED_ROLLBACK`，旧 journal 还原、active 清除。探针只是临时 fixture，不访问 live、不联网。

**此守卫仅覆盖 active 未完成/待清理事务。** active 已清除后旧 writer 仍可能启动 v1；本批不据此宣称生产旧版本回滚已全面安全，完整 A1/3C 迁移与发布证明另做。

直接读取 active.json 的保留任务也同步识别 v2。计划生成和删除前重新校验均使用实际 v2_run_id，不能保护占位名称却删除真实 COMMITTED journal。七项红转绿覆盖：计划保护、旧计划在删除前发现新 active、错误 guard、越界 ID、两类 namespace 链接、计划后 namespace 被换成链接；另在真实 v2 提交后清理失败用例中验证保留计划不删 journal。此修改是新指针格式必要的消费者兼容，不是无关运维重构。

**尚未实现证据锚点感知的长期保留规则。** inactive terminal v2 journal 仍可能按既有年龄政策进入删除计划；本批只保证 active/待清理事务不被误删，不承诺完整证据永久可验。3C 生产接线前必须明确 journal 锚点、输入 bundle 与历史版本的引用/保留政策，不能先启用 v2 再补此规则。

### 3.5 晨验

v1 仍按原集合核验（旧非 policy-bound release 的六文件兼容规则未扩大）。v2 必须恰好七业务文件，另行验证证据，不接受“至少七个”。

沿 audit 的 persistence.run_id 找 COMMITTED journal；核对 scheduled/non-shadow/as_of、无 active、协议/schema、decision_id/input_hash 与 audit 一致、精确角色与目录、最终清单 SHA 和每文件 SHA。未知角色、重复、少/多文件、错绑定、残留 active 均 FAIL。

晨验也拒绝 journal root/runs/run/manifest 的链接路径；悬空 active 链接仍视为残留 active，不降格为 absent。对应三类晨验链接拒收及两类事务 active 读者回归已实跑。

入口把当前 release 的 `transaction_evidence.py` 路径传入，动态读取可信已发布代码的纯标准库校验器；缺校验器则 FAIL。fixture 直接验证函数；另有 `/usr/bin/python3 -S` 用例验证不依赖运行时 site-packages。未对真实 live 执行晨验脚本。

## 4. TDD 与实际验证

| 检查 | 实跑结果与范围 |
|---|---|
| 新事务测试 | 33 项：登记/绑定/终检/权限、WAL 备份及提交前同步、前像预检、提交发布/清理、R6 alias、自指链接、journal namespace、悬空 active、旧 writer 守卫、三类真实 SIGKILL |
| 新晨验测试 | 19 项：成功只读、17 类拒收、system Python 标准库独立运行 |
| 保留任务测试 | 12 项：旧 5 + 新 7；实际 v2 事务的保护另在 33 项中覆盖 |
| 定点组合 | **181 passed，2.57s**：33 + 19 + 5 旧 score transaction + 14 设计边界 + 58 3A + 40 旧 morning acceptance + 12 retention |
| 全套 | **1665 passed，151.36s**；1606 + 33 + 19 + 7，无跳过本批失败测试 |
| Governance | **8/8 OK，ibkr_readonly=true** |
| 全仓 Ruff E9/F63/F7/F82 | PASS |
| 本批八个源/测试完整 Ruff | PASS（0.15.22，含 prune/retention test）；不宣称 ops/morning_acceptance 全文件完整 Ruff 通过 |
| 精确 CI mypy 四模块 | PASS |
| 四个本批核心模块 + prune mypy | PASS（2.3.0，5 files） |
| 扩展 ops mypy | **4 个预存提示，非 PASS**；基线相同四类问题见下文 |
| 编译 / tracked diff 空白检查 | PASS；缓存转存 /tmp |
| 依赖兼容 | `uv pip check`：**62 installed packages compatible**；含 dev 工具，不冒称 lock 仅有 62 包 |
| 四日期 strict 比较 | **all_equal=true；4/4 strict_differences=[]**，评分 payload/input_hash/七业务工件相等 |
| 真实旧 writer 探针 | PASS：旧拒绝且目录字节不变，新恢复；无网络/live |

关键红转绿包括：缺最终绑定原先被提交、raw 主文件回滚漏 WAL、额外证据文件残留、私有目录权限、active 路径穿越、旧 writer 不识别 v2、提交发布前失败未即时回滚、备份格式误标未拒绝、保留任务误读 v2 占位 ID、WAL 提交前未同步、自指 data alias 绕过内部链接检查、journal namespace 链接、悬空 active 被误判 absent。每项先用用例复现再修复。R6 根 alias 是既有实现的正向补覆盖，不冒称是新修缺陷。

三种强杀检查为真实子进程 SIGKILL：写业务中、绑定后未提交、COMMITTED 后清 active 前。用确定性管道握手，不靠 sleep；下一独立 PID 运行实际恢复函数。前两种恢复含两条已提交前态记录（主文件 + WAL），第三种保留已提交新值/证据。网络连接在子进程中拒绝。**不是生产完整 pipeline、自然运行或断电演练**。

扩展 ops mypy 的四类问题为：可空 datetime 的 isoformat、两处可空 mapping 的 get、dict(None) 类型。独立对 HEAD archive 复现（基线 381/1227/1229/1231 行），候选也保留这些问题；后续插入路径守卫会移动候选行号，不把旧行号当最新取证。未用 ignore/exclude 隐藏，也未顺手改无关逻辑。作为既有技术债另排修复。

### 4.1 本轮内部只读复审

同一只读代理提出三个 P2：发布 COMMITTED 前未同步未 checkpoint 的 WAL、内部自指 data alias 绕过链接检查、journal namespace 链接可导致根外写入/保留任务误删。作者独立用失败用例复现，逐项修复；并补保留任务与晨验读者回归，最终结果见上表。

代理随后仅复跑原来三个 `/tmp` 探针并静态检查修复：三项通过，原始条件下根外目录未写入，未发现修复范围内新的 P0/P1/P2。代理没有复跑最终 181/1665 套件、没有编辑仓库或访问 live；最终全套由作者实跑。此内部复审不是另一次完整外审，也不证明断电耐久或实际输入捕获。

## 5. 等价证据与 A1 发布限制

报告：`building/reports/score_transaction_v2/2026-10-03/equivalence.json`。基线 341 文件 manifest `062eea7f67cd3c0789d0482296b120ca6d045fd6286a7d38d5d7297fa35b5eb0`；候选 351 文件 manifest `f1724742185c4a5ced03241f8571469b018d07f16f3f5cbe6ab68107d70ddb5b`；seed 77 文件 `c119ae18b453b0e6838629c5af5c377cd4b2aa209aba84002c92303320455c99`。比较器的 source manifest 仅覆盖 package；两份 ops 脚本另列源码 SHA 并由 fixture 测试核验，不冒称由四日期评分比较器覆盖。

| as_of | 双端相同 input_hash |
|---|---|
| 2022-01-03 | `71e82be53a877500b2ce09ac6539ff048e90d7054a16d219450810bce9c28f9b` |
| 2022-01-25 | `7468df38dae70a3c309a4b553c9123e0543714f7ad3cf587f39f48614d915545` |
| 2026-05-29 | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` |
| 2026-06-04 | `03ea60f73228a178435cfb131942b18bcefded7409f602c0acf20961bef53930` |

**证明范围：既有比较器以 manual_rerun、include_ibkr=False 跑默认 v1 pipeline。** 使用原有严格归一化（时间/temp 路径、既有 operational envelope 等），未新增忽略项。它验证默认路径的业务输出，不证明 v2 新证据字节与 v1 相同，也不证明 scheduled 认证迁移相同或 full-state replay。新 v2 契约由专属事务/故障/晨验用例验证。

保守评分指纹实际变化，未修改排除集或迁移映射：

```text
baseline  42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a
candidate 9394490dd2db713f558080fc0239258f240ef82873c8731752f7095c8457ea66
```

新增 core/data 模块和事务字节参与指纹。默认 v1 不代表 scheduled 身份不变；四日期 manual strict 不能代替 A1 发布/旧同日 r2 迁移证明。预算仍为 2，没有 UUID 固定、认证绕过、扩豁免或 audit/state 清空。

三份旧证据保持原字节：history_versions `d3517494…`、decision_inputs `5da62a09…`、pre_run_state `230237d6…`。它们证明各自时点，不证明当前 351 文件树。3A 的 430 行/f98010bb… 现已被共享函数提取后的 376 行/73a9d9e4… 取代；不得重新拿旧 SHA 证明当前源码。

### 5.1 3B 收尾时点 SHA256

| 文件 | SHA256 |
|---|---|
| run_transaction.py | `cbbe41f5b97413e8bc3e9486aff3cfebfc317dc1655d8a42f12e52d02005a855` |
| transaction_evidence.py | `b6cfe16221170f3bbae1ee10ac14a4d7059e5222a32ef8df6130376b418176be` |
| sqlite_snapshot.py | `c74574309686f8dc8753e7120a2cdabeb2cb437f0e5a47da230783133fbdfd74` |
| decision_inputs.py | `73a9d9e4c6125196694d69a7ab864e55c7783ac5ddb0ea0242c8d1a4d9f5f3cc` |
| ops/morning_acceptance.py | `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d` |
| ops/prune_runtime_artifacts.py | `8e6945706ceb3592f39b63127aa1c90173e97577d5b8b064b6790e1aee08b7cd` |
| test_score_transaction_v2.py | `f4751cb7b4d6b972a075a01f266d5eec08ce20e775b437d5aa426d51ae554ab0` |
| test_transaction_v2_acceptance.py | `be7f6e21db654d06e9fd3e45c34e1527c6aff2f654134afec5bc7374b25b4d3f` |
| test_runtime_retention.py | `4216add92ce9be0bcb3ccae2af3c5b2512ce12a334372819956b35142a4b7384` |
| 新 equivalence.json | `4ed4c08caed7fd357d5cfc24aaa9dc4a87769d9fe33ece3522da6e0dcce71b45` |
| legacy_writer_probe.json | `c9714d069bcfb05ce14d059b86ab00a323f02d5c30d2d31d44bf32d98855fa19` |
| 未改比较器 | `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d` |

本文和生成 JSON 不是独立证明。请审源码、重算 SHA、独立跑测试/比较器；不要求重新生成报告与原 JSON 的运行时间/临时路径逐字相同。

## 6. 独立复现

在 repo 或完整候选副本操作；只用测试隔离根和 repo 的非 live seed。不得对真实 live 执行 morning_acceptance/daily/refresh 或连接 IBKR。

解释器本次为 Python 3.11.15、numpy 2.0.2、pandas 2.3.3、scipy 1.13.1；二进制 SHA `4c78423e7d5986362ac04df40edb18cdd1174f9818d653402e3abbd2a5bbf793`。临时路径不是长期保证；外审可按当前 lock/dev 安装自己的兼容环境。

```sh
PY=/tmp/hermes-urllib3-tests-20261002/bin/python
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests/test_score_transaction_v2.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  src/hermes_escape_top/tests/test_score_run_transaction.py \
  src/hermes_escape_top/tests/test_a2_capture_boundaries.py \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_runtime_retention.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" scripts/check_governance_consistency.py

env RUFF_CACHE_DIR=/tmp/hermes-a2-3b-audit-ruff "$PY" -m ruff check \
  src/hermes_escape_top scripts ops --select E9,F63,F7,F82
env RUFF_CACHE_DIR=/tmp/hermes-a2-3b-audit-ruff "$PY" -m ruff check \
  src/hermes_escape_top/core/data/run_transaction.py \
  src/hermes_escape_top/core/data/transaction_evidence.py \
  src/hermes_escape_top/core/data/sqlite_snapshot.py \
  src/hermes_escape_top/core/reporting/decision_inputs.py \
  src/hermes_escape_top/tests/test_score_transaction_v2.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  ops/prune_runtime_artifacts.py \
  src/hermes_escape_top/tests/test_runtime_retention.py
env MYPY_CACHE_DIR=/tmp/hermes-a2-3b-audit-mypy "$PY" -m mypy \
  --ignore-missing-imports --follow-imports=skip \
  src/hermes_escape_top/core/data/market_witness.py \
  src/hermes_escape_top/core/data/market_admission.py \
  src/hermes_escape_top/core/backtest/formal_gate.py \
  src/hermes_escape_top/web/health.py
env MYPY_CACHE_DIR=/tmp/hermes-a2-3b-audit-mypy "$PY" -m mypy \
  --ignore-missing-imports --follow-imports=skip \
  src/hermes_escape_top/core/data/run_transaction.py \
  src/hermes_escape_top/core/data/transaction_evidence.py \
  src/hermes_escape_top/core/data/sqlite_snapshot.py \
  src/hermes_escape_top/core/reporting/decision_inputs.py \
  ops/prune_runtime_artifacts.py
env PYTHONPYCACHEPREFIX=/tmp/hermes-a2-3b-audit-bytecode "$PY" -m compileall -q src scripts ops
git diff --check

BASELINE=$(mktemp -d /tmp/hermes-a2-3b-baseline.XXXXXX)
git archive 68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e | tar -x -C "$BASELINE"
env PYTHONDONTWRITEBYTECODE=1 FRED_API_KEY=hermes-review-synthetic-key "$PY" \
  scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASELINE" --candidate-source "$PWD" \
  --seed-data "$PWD/src/hermes_escape_top/data" \
  --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 \
  --python "$PY" --contract strict \
  --baseline-label 68e6b7f --candidate-label a2-v2-external-audit \
  --output /tmp/hermes-a2-3b-external-equivalence.json
```

旧 writer 独立探针的复现方法：在 tmp 建上述精确七文件/两证据清单；候选持 lease 调用 v2 `__enter__` 并写部分 journal，释放 lease但不执行退出；对所有 archive 文件取 SHA。另起 `PYTHONPATH="$BASELINE/src"` 进程，断言 `run_transaction.__file__` 来自基线，持同根 lease 调实际 `recover_incomplete_score_run`，必须报 `PersistenceRecoveryError`。比较 SHA 不变，再用候选持 lease 恢复，断言 `RECOVERED_ROLLBACK`、旧字节恢复、active 无。不得借该探针接触 live；保留的 JSON 有原始旧 writer 错误和双方源码 SHA，但须自行重做，不能仅采信 JSON。

## 7. 外审必答

请独立分别判定：3B 正确性、可提交/推送、完整 A2/部署条件。作者建议**3B 可审，不部署，不关闭 A2**。未获新授权前不自行 commit/push。

1. 默认 pipeline 是否仍 v1，无生产 v2 调用方/config/flag；是否把已有切片误列为本批？
2. 七业务文件是否 exact-set；角色/UUID/日期/重复/链接/既存目录/未知 schema 是否严格拒绝？
3. 输入绑定是否需有效 lease + 匹配 PENDING transaction，外部 manifest SHA 与内部文件 SHA 双层验证，COMMITTED 前不算成功？
4. 真正旧源码会否误按 v1 恢复 v2？是否独立运行旧代码且复核目录内容不变；保留任务是否保护真实 v2_run_id 并在删除前复查；事务/晨验/保留读者是否拒绝链接 namespace；是否诚实限定 active 守卫而未夸大版本回滚安全？
5. 真 WAL 已提交行是否保留，COMMITTED 发布前是否同步未 checkpoint 的 WAL？是否未 checkpoint/immutable 读源；备份 SHA 是否被误称为旧主文件字节 SHA？
6. 所有前像是否在第一文件恢复前完成核验，格式误标/坏第二备份是否 fail-closed、不半恢复？
7. 三类 SIGKILL 是否真实 OS 信号、独立 writer/recovery PID、确定性握手；是否不伪装成自然 run/断电/完整 pipeline？
8. COMMITTED 前发布失败与 COMMITTED 后清理失败是否正确分开；不可判定提交状态会否猜测性回滚？
9. 晨验是否沿 audit.run_id/decision_id/input_hash 绑定，精确七业务+逐证据核验，system Python 无 site-packages 可运行且不写入？
10. 3A SQLite 提取是否保留旧契约/58 测试；旧证据未覆盖，历史 SHA 和当前 SHA 是否准确区分？
11. 181/1665/8治理、Ruff、CI/core/prune mypy、严格四日期是否可重做；ops 四个预存类型提示是否如实登记而非宣称全绿？
12. 实际指纹变化是否明示，预算/迁移/比较器忽略项零改；是否承认实际输入生产者、证据锚点保留规则、完整重放、A1 发布证明和自然观察尚缺？

## 8. 剩余工作与下一步

- **3C 输入生产者与事务提前接线**：先定实际冻结/读取边界，再实现。3A `capture_pre_run_state` 当前拒绝 pending transaction，不能直接在 v2 上下文内调用或删守卫硬接；需有独立设计和真实接线测试。
- **完整隔离重放**：真实非空前态、历史/soft/config/认证材料、实际 Position/Execution 返回值、源码/依赖绑定；禁止重放联网或 IBKR，逐字段对照业务输出和落盘。
- **A1 / 发布**：新代码指纹已变，需新证明；旧 r2 不因安装自动解阻，不扩大预算或清链。人工批准/单次 R6/自然新决策日过渡与观察另做。
- **运维边界**：未实现新 evidence 自动保留/清理、大体量 benchmark、断电完整耐久；inactive terminal journal 可能被既有保留政策删除，3C 接线前须建立锚点/输入 bundle/版本引用的协调保留规则。0700/0400 不防同用户恶意代码，路径真实性依赖串行纪律。
- **既有技术债**：ops 四处类型收窄另批修复；本批不顺手改它们掩盖范围。

本批自查未见新的阻断缺陷，最终判定交独立外审。当前只是可供审计的工作区，没有上线效果承诺。

## 9. 同日后续：锚点保留前置补丁

本节是时点回注，不改写上述 3B 测试结果或外审判定。后续补丁只修改 `ops/prune_runtime_artifacts.py` 并新增 `test_evidence_anchor_retention.py`：全部 v2 terminal journal 暂不进入自动删除计划，执行旧计划时也复查；未知协议和带证据字段的 legacy 记录保留；链接或畸形 manifest 不授权删除。保护导致超过数量/容量限制时明确报告，不实现自动 evidence GC。

3B 表内 prune SHA `8e694570…` 是旧冻结值；后续 446 行源码 SHA 为 `7d52be95fe428a621c84f9ef8f2eec795ac7a8d5b49d5dbea82bb2d0764d6888`。新测试 21 项，最新全套 1686 passed。3B 的其他源码、两个归档 JSON 保持原字节；旧 351 文件比较器清单不代表新增测试后的完整树。生产 package 的 197 个非测试文件逐个核对未变，评分指纹仍 `9394490d…`，未重新跑四日期比较冒充新树绑定。

详情与复现命令：`docs/history/2026-10-03_a2_evidence_anchor_retention_handoff.md`。本补丁只消除既有保留任务误删锚点的前置风险，不完成引用式保留、真实输入捕获、完整重放或 A1 发布证明；3B 仍待外审，A2 OPEN，未提交/推送/部署。

## 10. 后续原语注记：前像导出

2026-10-03 后续批次新增显式 `export_score_run_before_images`，仅复用当前 PENDING v2 的冻结前像，不删 3A 守卫，不接 pipeline。当前 run_transaction 为 641 行、SHA `42c96e65...`；本文原 578 行 / `cbbe41f5...` 与 351 文件清单仍是 3B 历史时点，旧 JSON 原字节保留，不把旧清单称为最新源码。

当前工作区的新验证为 24 个专用用例、167 组合、1710 全套、8/8 治理和重新生成的四日期 strict。完整范围、当前哈希、A1 指纹变化及未完成项见 [前像导出交接](2026-10-03_a2_transaction_before_images_handoff.md)。本文 §9 锚点保留注记仍有效；3B、保留补丁和新增原语仍待联合外审，不授权生产接线或部署。

## 11. 同日联合外审结论注记

2026-10-03 联合外审已覆盖本片、共用 SQLite 原语、锚点保留与 export 交互，结论 PASS；本文原“待独立外审/待联合外审”为当时时点记录，已被联合结论取代。原正文、历史 SHA 和旧测试记录不回写。来源见 [联合报告](2026-10-03_a2_joint_external_audit_report.md) 与 [澄清](2026-10-03_a2_joint_external_audit_clarification.md)。当前候选冻结，可按用户授权提交/推送；**DEPLOY HOLD，A2 OPEN，Phase B 不启动**，未授权生产接线。
