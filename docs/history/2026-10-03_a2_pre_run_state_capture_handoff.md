# A2 第三切片 3A：离线运行前状态捕获与恢复 / 外审交接
_a2_pre_run_state_capture_handoff.md

日期：2026-10-03（实现及部分验证开始于 10-02，最终验证与交接于 10-03）。

仓库：`/Users/liweishi/Documents/github/hermes`，`hermes-docs`。
HEAD：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 1. 判定与范围

**3A 的显式离线捕获/恢复原语已实现并验证，等待独立外审。没有生产自动接线，没有提交、推送或部署；A2 保持 OPEN，Phase B 不启动。**

本批没有读取或修改 live，没有运行官方 daily、行情/外部源刷新、IBKR 连接或订单操作。四日期比较器是在临时隔离数据根内的有限评分回放，不是全窗口回测或 gate。

本批范围：

| 文件 | 本批变化 |
|---|---|
| `src/hermes_escape_top/core/reporting/decision_inputs.py` | 扩展第二切片的离线模块，加入两个 pre-state API 及其辅助函数；当前完整文件 430 行 |
| `src/hermes_escape_top/tests/test_pre_run_state_archive.py` | 新增 549 行，58 个收集用例 |
| `building/reports/pre_run_state/2026-10-03/equivalence.json` | 新生成的 strict 四日期对比证据 |
| 本文 | 实现契约、验证结果、限制及独立外审提示 |

工作区此前已经包含未提交的第一/第二切片和 3A 设计预检。`git diff HEAD` 不是本批的单独 diff：`decision_inputs.py` 本身仍是 untracked，外审必须读完整新文件，不能只看 tracked diff。

第一切片的 `history_versions.py`、backfill 接线、版本测试，第二切片的旧测试，以及两份 10-02 等价性 JSON 本批均保持原字节。**本批确实扩展了 `decision_inputs.py`，不能沿用第二切片旧模块 SHA 证明当前模块。** 原两个离线输入 API 仍在，旧 29 项测试已纳入本批验证。

三份无关九月计划文档保持原样，不属于本批：

- `docs/history/2026-09-05_dated_update_schedule.md`
- `docs/history/2026-09-05_post_release_a_20_dimension_review.md`
- `docs/history/2026-09-05_stabilization_update_plan.md`

`test_a2_capture_boundaries.py` 属于 10-02 的设计预检，不是 3A 新增测试；它计入 130 项组合只是验证复用，其 SHA 仍为 `e150741fb9969c276df1e4d46b2c4bcb75b3a149a2f08dfbb95c3cff143f1202`。外审收尾另对前两份交接补充时点回注；这两份文档回注属于收尾范围，不改前两切片实现、测试或证据字节。

pipeline、identity/revision、事务核心、config/flag、评分/路由、比较器、部署脚本、依赖锁均无本批变更。没有扩大指纹排除集、修订预算或迁移豁免。

## 2. 两个显式接口

```python
capture_pre_run_state(
    as_of, *, store, destination, _lease, required_artifacts=(),
) -> {"manifest_path": str, "manifest_sha256": str, "capture_id": str}

restore_pre_run_state(
    manifest_path, *, expected_manifest_sha256, capture_id,
    as_of, store, destination,
) -> Path
```

定义位置分别为 `decision_inputs.py:304` / `:367`。行号只是定位辅助，复核请同时按函数名。

调用方仍仅存在于新测试。没有 begin/finalize 生产 hook，没有把档案引用写入 score/audit/receipt/journal，没有把 capture_id 加进 decision identity。

### 2.1 捕获契约

1. 必须持有当前 `archive/.pipeline.lock` 的有效 lease，沿用既有 PID/线程/路径/活动状态校验。没有 `lock_held=True` 旁路。
2. 如存在未完成 score transaction，拒绝捕获。函数不会自行恢复或修复；调用方应在正确流程先完成恢复。
3. `as_of` 必须是精确 ISO 日期。清单固定为下面七文件，不扫描任意 runtime 目录。
4. `required_artifacts` 只允许该七文件的子集。预期应该存在的旧状态必须由调用方声明；缺失 required 文件拒绝。
5. 未声明 required 的缺失文件记 `ABSENT`，不创建空 DB/日志。**ABSENT 只是该路径当时不存在，不能证明首次安装、没有历史状态或认证链有效。**
6. 存在但损坏、不可读、目录冒充、文件级 symlink 或 SQLite 孤立 sidecar 不得变成 ABSENT。
7. 输出必须是新的离线目录，不得已存在、为悬空链接，或位于 data/archive/history/legacy 源根内。stage 根 0700；归档文件 0400。
8. 清单写完后 rename 发布；普通异常清理私有 stage，不产生可用的半成品输出。该实现不是新的生产持久化事务。

| 文件 | 归档方式 / 角色 |
|---|---|
| `hermes_state.sqlite` | `SQLITE_BACKUP` |
| `reentry_state.sqlite` | `SQLITE_BACKUP` |
| `mirror_reference.sqlite` | `SQLITE_BACKUP` |
| `flow_reference.sqlite` | `SQLITE_BACKUP` |
| `audit_log.jsonl` | `JSONL_BYTES` |
| `signal_journal.jsonl` | `JSONL_BYTES` |
| `soft_adapter_snapshot_<as_of>.json` | `JSON_BYTES` |

清单 schema 为 `hermes-pre-run-state-archive-v1`，证据角色明确为 `OFFLINE_PRE_STATE_NOT_DECISION_BOUND`。包含独立 UUID hex capture_id、as_of、捕获时间、四个解析后的源根、required 集合、七文件存在性/格式/摘要。

**没有 decision_id、input_hash、run_id 或 semantic_identity。** 调用接口的时间不能自行证明“这是某次真实 scheduled 评分读取前的状态”。这个证明要留给 3B/3C。

### 2.2 SQLite：保存已提交 WAL，不冒充主文件字节复制

源连接使用只读 URI、timeout=0，启动读事务，再核验 integrity、schema/列/行/元数据；使用 `Connection.backup()` 写隔离备份，并对备份复算同一逻辑摘要。连接通过 `closing()` 真正关闭。

- 捕获包含真实 WAL 中已提交的记录；不设置源 journal_mode、不 checkpoint、不删除源 WAL。
- backup busy/locked callback 直接拒绝，不无限重试。排他锁用例验证了立即失败与 stage 清理。
- 保存文件 SHA 绑定备份输出；`logical_sha256` 绑定其 schema、类型化行值、可访问 rowid 及 user_version/application_id/encoding。
- 文本保留嵌入 NUL，BLOB 用 hex、浮点用 float.hex，行摘要排序但保留重复次数；支持测试中的 WITHOUT ROWID 和含引号的标识符。
- 所有三个隐式 rowid 名称都被用户列遮蔽时明确拒绝，不做不完整逻辑哈希。依赖当前受测 SQLite 的 table_list/table_xinfo 能力；不宣称任意 SQLite 扩展/虚表兼容。
- 不用 SQL iterdump 作为逻辑摘要：开发中的实测发现它会把嵌入 NUL 的文本截断，回归用例先失败，再由类型化投影修复。

**备份 SHA 不等于源主文件 SHA。** WAL 用例检查源 main/WAL 字节未变，但 SQLite 只读连接可能更新 SHM 的读者账目；没有“全部 sidecars 零副作用”的承诺。多 DB 的一致性依赖同一 lease 下所有合法 writer 串行，backup 本身不是跨 DB 原子事务。

### 2.3 JSON/JSONL 边界

保存原字节。每个非空 JSONL 行及 JSON 文件必须能解析为 object；空/空白 JSONL 允许。这里只核验语法和顶层类型，**没有验证 audit 认证链、业务字段或 journal 语义**，不能把一个任意合法 JSON object 宣称为有效官方审计记录。

### 2.4 恢复契约

恢复要求外部提供 manifest SHA、capture_id 和 as_of，而不是取 bundle 自己声称的摘要作为可信锚点。

- 拒绝 manifest 自身及直接 bundle 根 symlink，包含全七项 ABSENT 的情况。
- 核对 schema、证据角色、有效的 32 位 UUID hex、日期、七文件精确集合、required 集合、四个绝对源根。
- PRESENT 文件必须命中预期白名单相对路径、格式、存在性与文件 SHA；SQLite 再核对逻辑 SHA。文件/直接 archive 子目录 symlink 也拒绝。
- `immutable=1` 只用于已经冻结的 SQLite 备份，绝不用于 live/source DB。
- EXACT ABSENT 不写空文件；required ABSENT 拒绝。
- 同时保护当前源根和捕获时源根；切换 LocalStore 后，也不能恢复进旧 data/archive/history/legacy。
- 恢复只写新的离线根 `archive/<文件名>`，输出业务文件 0600，根 0700；`original_manifest.json` 保留原证据字节、0400。
- 不借当前文件补缺，不连接网络/IBKR、不评分、不认证、不写官方 audit/state。restore 无需 pipeline lease，因为它不写源根。
- 摘要/绑定/路径验证或 rename 发布失败，删除 stage，不留最终输出。

## 3. 测试及实际红转绿

新文件收集 **58 项**。计数按参数化后的实际执行项，不按函数数。

| 用例组 | 数量 |
|---|---:|
| 七文件捕获、只用档案恢复、显式缺失、required 缺失 | 4 |
| 真实 WAL 与类型值/元数据 | 1 |
| 四类腐坏状态 | 4 |
| SQLite 排他锁 | 1 |
| 全 ABSENT 时的根 symlink | 1 |
| 缺失/错误根/失效 lease | 3 |
| 未完成事务拒绝且不自动恢复 | 1 |
| 空 capture_id 拒绝 | 1 |
| 来源 symlink/目录/sidecar/orphan | 5 |
| 不可读不能变 ABSENT | 1 |
| 错摘要/错 ID/错日期/缺档案/坏字节 | 5 |
| NUL 文本摘要不截断 | 1 |
| 捕获输出边界 | 6 |
| 源根切换后的原根/当前根保护 | 6 |
| 重锚摘要后仍须满足内部契约 | 7 |
| capture/restore 发布失败 | 2 |
| 匹配字节的 symlink 证据拒绝 | 3 |
| 真实 execution confirmation + sell cooldown 消费者重放 | 1 |
| restore 已有/悬空目标拒绝 | 2 |
| WITHOUT ROWID/引号标识符、隐式 rowid 变化、rowid 不可检查 | 3 |
| 合计 | 58 |

实际观察到的红转绿包括：capture/restore 接口尚不存在、未支持 required_artifacts、合法 ABSENT 处理缺口、全 ABSENT 根链接漏检、空 capture_id 漏检，以及 NUL 文本碰撞。其余用例是已实现拒收面的验证，不把所有 58 项都宣称为各自先红后绿。

真实消费者用例归档 T1 确认/旧卖出冷却，然后修改当前源为 T2/新冷却，恢复后用实际 readers 读到旧确认/冷却，当前源仍保持新状态。这是两个消费者的有限重放，**不是含 IBKR、sizing、routing、全部旧状态的完整 pipeline 重放。**

新测试全部使用 tmp_path 独立 LocalStore，socket.connect 被禁止。不可读场景用明确的 PermissionError 注入；不依赖当前进程身份是否能绕过 chmod。pending transaction 用例调用真实事务，在捕获拒绝断言后，仅为清理临时测试根显式调用恢复器。

## 4. 验证结果

| 检查 | 当前结果 |
|---|---|
| 新测试收集 | 58 项 |
| 3A + 输入29 + 版本24 + 边界14 + score transaction5 | **130 passed，4.89s** |
| 全套 | **1606 passed，156.23s**（1548 + 58） |
| Governance | **8/8 OK**，ibkr_readonly=true |
| 完整 Ruff：当前 decision_inputs + 新测试 | PASS |
| 全仓 src/scripts/ops Ruff E9/F63/F7/F82 | PASS |
| mypy：当前 decision_inputs + 新测试 | 2 files，零 issue，未加 ignore/exclude |
| 两文件 compileall | PASS |
| tracked diff --check + 两个 untracked 源/测试空白检查 | 无诊断；no-index 的退出 1 是存在差异，不是空白错误 |
| strict 四日期比较 | **all_equal=true，4/4 equal，strict_differences=[]**，每日期七业务产物 |
| 评分指纹 | 与 HEAD 基线相同，见第 5 节 |

四日期证据的范围：完整规范化 payload 与七业务产物。比较器原有规则会规范化时间戳、临时根前缀、audit 时间戳派生 payload_hash；操作性的随机事务 envelope 不参与业务比较。**本批没有修改比较器或新增忽略字段。** include_ibkr=False，不证明 IBKR 分支或新增档案本身通过生产评分链路；新档案由专属 58 项验证。

本批未重新运行 external failure drill：外部 adapter/runner 未变，此检查不支持新 pre-state 契约，不能拿旧 13/13 冒充本轮新执行。没有 kill-9、自然 scheduled run 或线上观察结果。

## 5. 不可变证据与旧报告关系

新报告：`building/reports/pre_run_state/2026-10-03/equivalence.json`。

| 证据 | SHA256 |
|---|---|
| 当前 decision_inputs.py | `f98010bbd68e2f53f184ecd933cc7aa6f0895fdbfdab5b4883b0734fcbbd0bb5` |
| 新 test_pre_run_state_archive.py | `0ad72d39123f6c78e9f1a74ec5fbe7bdea7956062bb297fb1282ecc66d8aa64a` |
| 新 equivalence.json | `230237d633aafae088e8a7a708799d561a375feea7e35853a60061057574af50` |
| 未改比较器 | `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d` |

评分指纹：`42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`。

新证据绑定：

- 基线 source：341 文件，manifest SHA `062eea7f67cd3c0789d0482296b120ca6d045fd6286a7d38d5d7297fa35b5eb0`。
- 当前候选 source：347 文件，manifest SHA `939e933ab37cd34adf7eab19193517d11a83706f773ecee5b9a7ef8ac3c2ebd2`。这是累积工作区源码快照，含先前切片/边界测试，不是只含两文件的干净 HEAD。
- seed：77 文件，manifest SHA `c119ae18b453b0e6838629c5af5c377cd4b2aa209aba84002c92303320455c99`。
- 解释器：Python 3.11.15，numpy 2.0.2，pandas 2.3.3，scipy 1.13.1。解释器二进制 SHA `4c78423e7d5986362ac04df40edb18cdd1174f9818d653402e3abbd2a5bbf793`。

| as_of | 两侧相等的 input_hash |
|---|---|
| 2022-01-03 | `71e82be53a877500b2ce09ac6539ff048e90d7054a16d219450810bce9c28f9b` |
| 2022-01-25 | `7468df38dae70a3c309a4b553c9123e0543714f7ad3cf587f39f48614d915545` |
| 2026-05-29 | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` |
| 2026-06-04 | `03ea60f73228a178435cfb131942b18bcefded7409f602c0acf20961bef53930` |

旧报告保持冻结，不覆盖历史事实：

- history_versions/10-02 JSON SHA `d3517494fe573565043ebaf652fdbbb7e985fbdaa8533755192196a4a4f9b9d1`。
- decision_inputs/10-02 JSON SHA `5da62a094665d31741729ed1de11932ac59332d1d89e96117a5c0ccf1f9e571e`。
- 第二切片曾验证的 213 行模块 SHA `e73a3f9a5f772bf50a4af235ac243161f51a9a659adb3ec1bf4b80415829cd05` **不是当前 SHA**。当前扩展后的等价性应查 10-03 新报告。

本文不是自己的独立证明；请重算源文件/报告 SHA，审比较器，再独立跑验证。没有把账户/持仓/原始 SQLite/完整状态 bundle 写进仓库证据目录。

## 6. 复现命令

从仓库执行。`PY` 使用本次既有兼容环境，或外审按 lock 安装的独立 Python 3.11 环境；临时路径不是长期可用保证。工具本次为 Ruff 0.15.22 / mypy 2.3.0。

```sh
PY=/tmp/hermes-urllib3-tests-20261002/bin/python

env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py \
  src/hermes_escape_top/tests/test_decision_input_archive.py \
  src/hermes_escape_top/tests/test_history_versions.py \
  src/hermes_escape_top/tests/test_a2_capture_boundaries.py \
  src/hermes_escape_top/tests/test_score_run_transaction.py -q -p no:cacheprovider

env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider

env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" scripts/check_governance_consistency.py

env RUFF_CACHE_DIR=/tmp/hermes-a2-3a-ruff "$PY" -m ruff check \
  src/hermes_escape_top/core/reporting/decision_inputs.py \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py
env RUFF_CACHE_DIR=/tmp/hermes-a2-3a-ruff "$PY" -m ruff check --select E9,F63,F7,F82 src scripts ops
env MYPY_CACHE_DIR=/tmp/hermes-a2-3a-mypy "$PY" -m mypy \
  --ignore-missing-imports --follow-imports=skip \
  src/hermes_escape_top/core/reporting/decision_inputs.py \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py

BASELINE=$(mktemp -d /tmp/hermes-a2-3a-baseline.XXXXXX)
git archive 68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e | tar -x -C "$BASELINE"
env PYTHONDONTWRITEBYTECODE=1 FRED_API_KEY=hermes-review-synthetic-key "$PY" \
  scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASELINE" --candidate-source "$PWD" \
  --seed-data "$PWD/src/hermes_escape_top/data" \
  --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 \
  --python "$PY" --contract strict \
  --baseline-label 68e6b7f --candidate-label a2-pre-run-state-external-audit \
  --output /tmp/hermes-a2-3a-external-equivalence.json
```

独立比较结果应查 all_equal、每日期 strict_differences、source/seed/python/comparator 绑定，不要求重新运行生成的 JSON 与原报告逐字节相同；临时路径及捕获元数据本来不同。不得覆盖原冻结证据。

## 7. 外审提示与必答问题

你是独立审计员。仅在 repo 和自己的临时隔离数据根取证，禁止访问/修改 live runtime、运行 daily/refresh/morning_acceptance、连接 IBKR、改 config/flag 或部署。先核范围与源码，再运行验证，不采信本文自身作为证明。

请分别判定：离线实现正确性、是否可提交/推送、是否具备完整 A2/部署条件。后两者不能因全套通过而合并；本批没有生产接线，作者建议**不部署、不关闭 A2**。

1. 本批是否确实只有扩展 reporting 模块、新测试和证据/文档？是否误把已有 backfill diff、三份九月计划混进本批？
2. capture 是否要求有效的当前根 lease，并拒绝 pending transaction 而非自行修复？无 lease/失效/错根是否拒绝？
3. 七文件集合与 required/ABSENT 是否精确？损坏、不可读、孤立 WAL、文件链接会否变成正常缺失？是否诚实声明 ABSENT 不能证明首次安装？
4. SQLite 是否真正包含已提交 WAL？源 main/WAL 是否未改？是否误用 immutable=1 读取源或把 backup SHA 说成源文件字节 SHA？
5. 逻辑摘要是否区分 NUL 后文本、BLOB、浮点、重复行和隐式 rowid？WITHOUT ROWID/引用标识符是否可恢复？不可检查的 rowid 是否拒绝？
6. 锁冲突/发布失败/损坏文件是否 fail-loud 且无半成品？普通异常清理是否被误称为 kill-9/断电恢复？
7. 外部 manifest SHA、capture_id、as_of 与每文件摘要是否都要匹配？重新锚定 manifest 后，越界路径、错 inventory/format/logical SHA/required 仍会被拒吗？
8. 恢复是否同时保护当前及原根，并只写新的离线目录？manifest/root/file symlink 在全 ABSENT/有文件时是否都拒绝？
9. 是否承认 JSON 仅语法校验、读者可能改变 SHM、路径祖先 symlink/同用户并发换路径不属独立安全边界，未夸大来源/审计真实性？
10. 是否保留旧两个接口契约和旧 29 项测试？新报告是否绑定当前 430 行源码，而非错误引用第二切片旧 SHA？
11. 是否独立复现 130 focused、1606 full、8/8 governance、静态检查、四日期 strict 与评分指纹；没有新 comparator 忽略项、config/flag/路由/预算变更？
12. 是否明确没有实际 run/decision 绑定、COMMITTED 锚点、生产 WAL 回滚修复、完整重放、自然运行样本，因此 A2 和发布依然未闭合？

可增加探针：修改档案并重锚 manifest 后测试内部拒收面；真实 WAL/排他锁；NUL 文本；恢复到旧根/悬空目标；全 ABSENT 根 symlink；异常注入后逐文件比对源字节。探针仅使用 tmp 数据，不从 live 复制账户数据。

## 8. 残余边界与下一步

1. **尚无事务绑定。** 清单摘要由显式调用方保存，没有持久化到 COMMITTED journal/audit 的外部锚点；bundle 存在不等于某次评分成功，capture_id 不等于 run_id。
2. **尚无生产自动化。** 没在 schema-changing readers 前自动冻结状态；旧 raw SQLite 主文件 rollback 未被修复。不得把新增 SQLite backup 能力宣称为现有 rollback 已支持 WAL。
3. **尚无全状态重放。** 只有确认和冷却两个真实消费者验证；原始执行输入、代码内容、外层 daily state/receipt/SIP 未归档，没有完整 pipeline 隔离重放。
4. **有限文件验证。** JSON 合法不等于链条自洽；required 集合目前由离线调用方承担，不从生产审计状态自动推导。
5. **非崩溃耐久协议。** JSON 写有文件 fsync，但没有整 bundle/父目录耐久提交保证，没有 kill-9 恢复器；断电或强杀可能留下 stage，不能拿 finally 当持久化恢复。
6. **非安全沙箱。** SHA 是绑定不是签名；0400/0700 是访问限制不是 WORM。合法 writer 必须遵守共同锁；不防同用户恶意改源、换父链接或发布前竞态。直接 bundle-root symlink 拒绝不等于整条祖先路径无 symlink。
7. **规模边界。** 完整 schema/行排序和 JSONL 读取有内存/时间成本，尚无大规模 benchmark/保留策略；本批按现有七文件范围，不泛化成任意数据库备份框架。

下一步按 10-02 设计执行 **3B：显式事务/验收协议升级**：完整登记每个业务与证据文件、保留七业务 exact-set、解决 WAL 前像恢复、把最终 manifest SHA 绑定到 COMMITTED、独立子进程 kill-9 与下一进程恢复、提交后的清理失败不得反向回滚。

3B 通过后再做 3C 真实入口自动绑定与完整隔离重放；pipeline/事务变更引起的 A1 指纹差异必须另证，不扩大排除集或预算。独立外审、人工发布批准和自然观察完成以前，不将上述计划作为已实施项，不部署，也不启动 Phase B。

## 9. 2026-10-03 独立外审收尾

用户提供的外审判定为：离线实现 PASS、允许提交/推送；不得部署、不得关闭 A2。外审报告声称独立复现 58/130/1606、四日期 strict、源码/seed/解释器绑定及 21 个对抗性变体。此处记录审计方结论，不将它们冒称为作者本轮新执行的测试。

收尾核验与处理：

- F1：重新计算第一切片 JSON/测试 SHA，并读取第一份交接，当前已是 `d3517494…`、24 项、`10e98bf5…`。外审反馈中的旧登记值在现文件未复现，因此不“修复”已经正确的表格、不再次生成 JSON；只明确各时点及最新证据去向。
- F2：补注 14 项设计边界测试的既有归属，避免把验证组合误认为本批新增范围。
- F3：第二切片的 213 行模块 SHA 是历史登记，不是当前 430 行 SHA；在旧交接紧邻哈希表回注当前值与 3A 交接路径。第一切片已有初版 23→24 的时间线，本次不改历史数值。
- 本轮收尾只改三份交接文档；模块、测试、三个归档 JSON 均未改。沿用对未变化实现有效的 1606/strict/静态证据，不为文字回注重跑完整测试。

3A 离线契约外审通过不等于 3B/3C 完成。仍未 commit/push/deploy；下一批先实施并验证 3B 事务升级，保持 A2 OPEN。

## 10. 后续时间注：3B 共享 SQLite 原语提取

2026-10-03 后续 3B 将本模块两个 SQLite 私有函数原样提取到 `core/data/sqlite_snapshot.py`，通过导入别名保留 3A 调用契约；当前 `decision_inputs.py` 为 376 行，SHA `73a9d9e4c6125196694d69a7ab864e55c7783ac5ddb0ea0242c8d1a4d9f5f3cc`。

本文原 430 行/f98010bb… 和 `pre_run_state/2026-10-03/equivalence.json` 是 3A 时点证据，未被覆盖，不再作为当前工作区源码绑定。新的验证、指纹差异、事务 scope 与发布限制见 `docs/history/2026-10-03_a2_transaction_v2_handoff.md`；3A 的 58 用例再次通过。3B 尚无生产接线，不表示完整 A2 已完成。
