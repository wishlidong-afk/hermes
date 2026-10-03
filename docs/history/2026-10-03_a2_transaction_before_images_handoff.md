# A2 / 3C 前置：从 v2 冻结前像导出运行前状态

日期：2026-10-03。仓库 HEAD：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 1. 当前判定与范围

**完成一个显式、未接生产入口的导出原语与 24 个隔离测试。没有完成 3C 自动捕获、完整重放或 A2；不得据此部署。**

上一批 3B 和证据锚点保留补丁仍待独立外审。用户继续推进后，本轮只补它们后续需要的前像导出原语，不绕过外审去接评分入口。

本轮增量：

- `src/hermes_escape_top/core/data/run_transaction.py`：只新增 `export_score_run_before_images`，当前文件 641 行。删除这一个函数及新增的两个空行，剩余字节 SHA 等于 3B 登记的 `cbbe41f5...`。
- `src/hermes_escape_top/tests/test_transaction_before_images.py`：新文件，334 行、24 个用例。
- `building/reports/transaction_before_images/2026-10-03/equivalence.json`：本轮重新生成的四日期 strict 证据；不覆盖旧 JSON。
- 本文及两份已有交接的后续注记：只区分历史证据与当前状态。

这不是全部 `git diff HEAD` 的范围。共享工作区仍有先前 A2 切片，必须连同其交接分别核对；三份九月未跟踪计划未动。

`pipeline.py`、identity/revision、config、flag、依赖锁、比较器和部署脚本本轮零改动。没有提交、推送、部署、刷新数据、连接 IBKR 或触碰 live。

## 2. 为什么新增独立入口

3A 的 `capture_pre_run_state` 要求没有 pending transaction。直接在 v2 上下文里调用它会拒绝；删除这个守卫则可能把评分期间已经变化的状态冒充运行前状态。

v2 在进入上下文之前已完成七业务文件的前像备份，包括 SQLite backup 保存的已提交 WAL 行。因此本轮从这些冻结备份导出，**不重新读取当前业务文件**，也不调用离线捕获后再重命名其证据角色。

```python
state = export_score_run_before_images(transaction, _lease=lease)
```

`transaction` 必须对应当前持锁、PENDING 的 v2 journal，run_id 与 capture_id 均匹配。v1、已提交的事务、错根/失效/缺失 lease 均拒绝。

## 3. 路径、返回值与提交契约

调用方在进入 v2 事务前，显式登记每一个存在前像的目标：

```text
archive/decision_inputs/<capture_id>/pre_state/<business-relative-path>
例如：.../pre_state/archive/hermes_state.sqlite
```

登记在 `pre_state/` 下的文件集合必须恰好等于七业务文件中 `existed=true` 的集合；缺登记或多登记都拒绝。其它输入证据仍按 v2 原协议登记，不被算作前像。若调用方要保存返回清单，可在捕获根登记 `pre_state.json`，不能把它放进专用于前像的 `pre_state/` 文件集合。

返回值包含：

- schema：`hermes-score-before-images-v1`。
- capture_mode：`V2_PREPARED_BEFORE_IMAGES`，**不是消费输入已验证的声明**。
- binding：run_id / capture_id / as_of；没有分配 decision_id 或修改 input_hash。
- artifacts：精确七业务路径的 PRESENT/ABSENT、目标路径、SHA、snapshot_format、before_mode。

PRESENT 的 SHA 绑定冻结备份字节及导出文件；SQLite 格式为 `SQLITE_BACKUP`，不得把该 SHA 称为原 SQLite 主文件字节 SHA。其它文件为 `BYTES`，这里不新增 JSON/审计链的语义认证。

ABSENT 只有显式缺失元数据，不创建空 DB/空业务文件。**ABSENT 不证明首次安装或旧认证链有效**；required 文件和决策链完整性仍是未来真实调用方必须核验的条件。

函数先核验所有备份的格式/原权限/字节 SHA、目标登记及路径，再开始复制。复制使用排他创建，目标为 0400；复制异常清除本次新文件，允许同一事务内显式重试。已有目标不覆盖，链接/断链拒绝。没有额外重试循环或网络请求。

返回的字典不会自动落盘、不会自动绑定或提交。调用方仍须保存清单、生成最终输入清单并调用原 `bind_score_run_inputs`；最后由 v2 验证全套登记文件及摘要后 COMMITTED。目录存在、复制成功或返回清单都不能代替 COMMITTED 外部锚点。

业务失败由同一 v2 journal 恢复业务文件并删除新捕获文件。成功提交后，登记的前像属于永久证据，临时 backups 可以删除；上一批的保留补丁保护其 v2 journal。这里尚未提供此新格式的恢复/重放消费者。

## 4. 测试矩阵与实际开发记录

| 组 | 数量 | 实际验证 |
|---|---:|---|
| 写后导出 | 1 | 先改七文件，再导出；仍得到旧状态，提交后证据保留、临时备份删除 |
| 坏备份元数据 | 4 | SQLite 格式被误标、原权限缺失/负数/布尔均拒绝 |
| WAL | 1 | 真实 SQLite；旧已提交 WAL 行保存，后来删改不改变导出的旧行；源 main/WAL 字节不被导出修改 |
| ABSENT | 2 | 一个 DB 缺失及全部七文件缺失；不补造空文件 |
| 复制中断 | 1 | 第二次实际复制后注入异常；新文件全清，显式重试可提交 |
| 事务回滚 | 1 | 已导出后业务失败，JSON 字节恢复、SQLite 旧业务行恢复、新证据删除 |
| 目标清单/存在性 | 4 | 缺登记、多登记、已有目标、悬空目标链接拒绝，先前文件不被改写 |
| 最后一份坏备份 | 3 | 内容损坏、丢失、文件链接均在复制前拒绝 |
| 事务/lease | 5 | 错 run、错 capture、无 lease、错根、失效 lease |
| v1 / COMMITTED | 1 | 两种调用都拒绝，已提交证据字节不变 |
| 3A 守卫 | 1 | 真实 pending v2 内离线捕获仍拒绝，外部目标不创建 |
| 合计 | **24** | 每例显式 tmp_path；socket.connect 被禁止；无网络/IBKR/live |

两个实际红转绿阶段：第一例因 API 不存在失败；第二例因误标 backup 格式未被拒绝失败。其余用例用于验证已实现的拒绝面和既有事务回滚。开发中还纠正了两处测试错误：SQLite backup 不保证主文件原字节一致，以及 LocalStore 的导入/构造方式；没有为这两处测试错误修改生产恢复逻辑。

## 5. 验证结果与证据

| 检查 | 本轮实际结果 |
|---|---|
| 新增用例 | **24 passed，0.80s** |
| 六文件组合 | **167 passed，2.81s** |
| 全套 | **1710 passed，153.78s**（上一批 1686 + 24） |
| Governance | **8/8 OK**，ibkr_readonly=true |
| 两改动文件完整 Ruff 0.15.22 | PASS |
| 全仓 E9/F63/F7/F82 | PASS |
| run_transaction mypy 2.3.0 | PASS，1 file，无新增 ignore |
| compileall | PASS，缓存写入 tmp |
| 四日期 strict | **all_equal=true，4/4 strict_differences=[]** |

六文件组合见下节原样命令；完整类型检查未扩大到 ops 所有文件，3B 已披露的 ops 四处预存类型提示不因这一项 PASS 而被关闭。

四日期比较重新运行于同一解释器、新隔离数据根，基线为 git archive HEAD。覆盖默认 manual/v1、include_ibkr=False 的完整规范化 payload/input_hash 与七业务落盘；比较器未改、未加忽略项。**它不证明新 API 被实际评分消费，也不覆盖完整非空 Hermes 状态重放、scheduled 身份迁移或真实 IBKR 分支。** 新 API 的实际行为靠本轮专用测试证明。

| 文件 | SHA256 |
|---|---|
| 当前 run_transaction.py | `42c96e65a3f2bdcf3f6115411615aa14cb155cd26bab6249d51ddc44e161a6e8` |
| 新测试 | `39ec50fdea355327ec2548ac205141feb9d6856fef7a677253ccfab750ff0ea6` |
| 新 equivalence.json | `99f15174ca9e5ca8646f9f3aeabb3ab488c0825f0b2f61f4edec4f3c5cf142c3` |
| 未改比较器 | `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d` |

新 JSON 的候选 package 清单：353 文件，manifest SHA `be4757048bcf74e909580c2a9b8b4880a61b472da9b81a1a20ed8ef19e4f9f99`；基线 341 文件 SHA `062eea7f67cd3c0789d0482296b120ca6d045fd6286a7d38d5d7297fa35b5eb0`；seed 77 文件 SHA `c119ae18b453b0e6838629c5af5c377cd4b2aa209aba84002c92303320455c99`。package 清单不包含 ops 或本文，不冒称整个仓库证据。

四日期 input_hash 与前一批一致：

| 日期 | input_hash |
|---|---|
| 2022-01-03 | `71e82be53a877500b2ce09ac6539ff048e90d7054a16d219450810bce9c28f9b` |
| 2022-01-25 | `7468df38dae70a3c309a4b553c9123e0543714f7ad3cf587f39f48614d915545` |
| 2026-05-29 | `b9327d63229390d3545530f13c03c16972450d81bcccdab9bcb64d582d492f31` |
| 2026-06-04 | `03ea60f73228a178435cfb131942b18bcefded7409f602c0acf20961bef53930` |

评分逻辑字节指纹如实变化：HEAD `42d207d6...` → 3B `9394490d...` → 当前 `03b94995fba06e849eef7468d1ba3e9f67bd8038296dfd8cf0e47a694533ad73`。预算、映射、排除集未改。没有用 manual 四日期等价替代 A1 scheduled 发布证明。

本轮重算五份旧证据 SHA：history_versions `d3517494...`、decision_inputs `5da62a09...`、pre_run_state `230237d6...`、3B equivalence `4ed4c08c...`、legacy_writer_probe `c9714d06...`，全部保持原字节。旧候选清单仅代表各自成文时点，当前复核使用本轮新报告。

## 6. 独立复现与外审问题

不要运行 daily/morning_acceptance.py、刷新行情、连接 IBKR 或触碰 live。`PY` 指向具备项目依赖的 Python 3.11 环境；作者环境为 `/tmp/hermes-urllib3-tests-20261002/bin/python`，NumPy 2.0.2 / pandas 2.3.3 / SciPy 1.13.1。

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests/test_transaction_before_images.py \
  src/hermes_escape_top/tests/test_score_transaction_v2.py \
  src/hermes_escape_top/tests/test_pre_run_state_archive.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  src/hermes_escape_top/tests/test_evidence_anchor_retention.py \
  src/hermes_escape_top/tests/test_runtime_retention.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src "$PY" scripts/check_governance_consistency.py
"$PY" -m ruff check --no-cache src/hermes_escape_top/core/data/run_transaction.py \
  src/hermes_escape_top/tests/test_transaction_before_images.py
"$PY" -m ruff check --no-cache --select E9,F63,F7,F82 src/hermes_escape_top scripts ops
"$PY" -m mypy --cache-dir=/tmp/hermes-before-images-audit-mypy \
  --ignore-missing-imports --follow-imports=skip src/hermes_escape_top/core/data/run_transaction.py
git diff --check
```

四日期独立重做沿用 3B 交接的 git archive 基线与 comparator 命令，candidate 指向当前仓库；输出放新 tmp 文件，不覆盖作者冻结证据。审查比较器源码后再信其结论。

必答：

1. 此 API 是否只新增于原事务模块，原有 prepare/恢复/绑定/提交逻辑未被改写？是否区分本轮增量与累积 HEAD diff？
2. 导出是否使用 PENDING v2 的冻结备份而非写后业务文件；7 路径、run/capture/lease 是否精确核验？
3. 缺失、坏备份或格式误标能否被记为 PRESENT；最后一个备份损坏时有无先前半成品？
4. 登记集合、已有目标、链接/断链是否拒绝；中断是否清理新文件，事务失败是否恢复业务状态？
5. WAL 用例是否真实，且诚实区分备份 SHA、源主文件字节和逻辑行？
6. 3A pending 守卫是否仍在；ABSENT 是否未被宣称首次安装证明？
7. 返回值是否未自动认证或变成消费输入证明；测试的 IN_RUN_CAPTURE 顶层清单是否明确是隔离 fixture，不是生产评分证据？
8. 24/167/1710、治理、静态及四日期证据能否独立复现，源码/seed/比较器 SHA 是否匹配？
9. A1 指纹变化是否如实披露，预算/迁移/排除集/比较器是否未改，旧证据是否保持原字节？
10. 是否仍无生产调用方、完整恢复消费者、全路径重放或自然样本，没有关闭 A2 或宣称允许部署？

请对 **3B + 锚点保留 + 本原语**给出分别的正确性、提交/推送、部署/A2 闭合判定。作者自查与本文不构成独立外审批准。

## 7. 仍未完成

- 真实入口事务提前与消费输入冻结；历史/soft/config/市场认证材料和 Position/Execution 返回值均未自动绑定。
- 该前像格式的独立恢复消费者、完整非空 Hermes 状态重放、运行源码/依赖归档。
- 大文件峰值内存/耗时与存储容量测试；本函数摘要核验使用 read_bytes，不声称已解决大档案成本。
- 同用户恶意篡改或并发改链接不是此 API 的安全边界；真实性与串行性依赖既有 lease/journal 纪律。
- 本轮未新增 SIGKILL 或断电实验；已有 v2 crash 测试本轮组合重跑，不冒充新出口的完整断电耐久证明。
- A1 新指纹发布/迁移和旧 writer 完整版本回滚证明、受控 R6 及自然观察。

下一步先联合外审，再确定真实入口的冻结边界及显式接线开关。**不因今晨 live PASS 或此处测试全绿跳过这些门槛。A2 OPEN，Phase B 不启动。**

## 8. 收到本原语外审后的范围澄清

同日用户提供独立外审：本原语与 24 用例 PASS，提交/推送可批准其范围；部署与 A2 闭合明确 HOLD。这个结论不是 3B/锚点保留或全部累积工作区的批准。

本轮核对并登记 7 个 tracked 改动、12 个新源码/测试及 5 个证据目录，详见 [累积范围与联合外审提示](2026-10-03_a2_cumulative_scope_joint_audit_prompt.md)。未来提交说明分列各批与批准状态；3B 与锚点保留仍待独立外审。本轮没有提交或改实现/测试/冻结 JSON。

反馈中“函数内 registered/expected 检查不可达”已被现有正常上下文用例证伪：missing_registration 与 extra_registration 均直接触发 `before-image evidence registration mismatch`，没有手工改 journal。一般协议验证与前像精确集合验证不可混为一谈。增量旧 SHA 的重建仍仅表示单文件字节一致性，不伪装成已提交的 3B 历史基线。

## 9. 同日联合外审结论注记

2026-10-03 联合外审已覆盖当前累积候选，包括本原语、3B、锚点保留和依赖交互，结论 PASS；本文 §8 原“仍待独立外审”为当时时点记录，已被联合结论取代。原正文、历史 SHA 和旧测试记录不回写。来源见 [联合报告](2026-10-03_a2_joint_external_audit_report.md) 与 [澄清](2026-10-03_a2_joint_external_audit_clarification.md)。当前候选冻结，可按用户授权提交/推送；**DEPLOY HOLD，A2 OPEN，Phase B 不启动**。没有生产调用方、恢复消费者、完整重放或自然样本的限制仍成立。
