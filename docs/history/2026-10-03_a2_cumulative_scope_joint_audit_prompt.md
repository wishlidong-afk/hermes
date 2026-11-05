# A2 累积范围冻结与联合外审提示

日期：2026-10-03。基线 HEAD：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 1. 为什么需要这一轮联合外审

本提示成文时，前像导出分片外审只通过 **export 原语及其 24 个用例**，当时 3B 与锚点保留尚未得到独立外审结论。同日后续联合外审已覆盖当前累积候选及其交互；外审者进一步确认，分片的待审标签已被该联合结论取代，不存在第四道未完成审批。

以下为澄清后的当前状态，批准仅绑定 §3 的冻结候选，不扩大为无条件发布授权：

| 批次 | 审计状态 | 当前仍需核验的边界 |
|---|---|---|
| 历史版本 / 离线输入 / 3A / 设计边界 | **当前累积候选联合外审 PASS** | 旧报告仍是时点记录；当前抽取与累积交互由联合外审覆盖 |
| 3B v2 事务及验收 | **联合外审 PASS** | 协议、WAL、回滚、旧 writer、验收及共用 SQLite 原语均已独立审查 |
| 锚点保留补丁 | **联合外审 PASS** | v2 锚点保护、执行复查及容量范围已审，不等于完整引用式 GC |
| 前像导出原语 | **分片及联合外审 PASS** | 包含与上述依赖的当前交互，不授权生产接线 |
| 整个候选 / 生产发布 / A2 | **联合外审 PASS（候选冻结）/ DEPLOY HOLD / A2 OPEN** | 没有生产接线、完整重放、A1 新指纹发布证明或自然样本；Phase B 不启动 |

本文件是范围清单和提交模板，不是独立外审原文。当前判定来源为 [原报告](2026-10-03_a2_joint_external_audit_report.md) 与 [外审澄清](2026-10-03_a2_joint_external_audit_clarification.md)。本次状态更新不改实现、测试或冻结 JSON；用户已确认提交/推送授权，未授权部署。下文历史时点记录保留。

## 2. 当前文件清单

请审 **当前工作树** 的 `git diff HEAD` 加下列未跟踪实现，不能只读最近一份增量交接。清单生成时为 **7 个已跟踪改动 + 12 个未跟踪源码/测试文件**；本文件及交接文档另列，不混入实现计数。

下表路径相对仓库；它们是允许的累积实现/运维说明范围，而非 19 个文件都属于最新 export 批次。

| 路径 | 状态 | 归属 / 需说明的累积关系 |
|---|---|---|
| `docs/PRODUCTION_RUNBOOK.md` | M | 3B 及锚点保留说明 |
| `ops/README.md` | M | 3B 及锚点保留说明 |
| `ops/morning_acceptance.py` | M | 3B v2 只读验收 |
| `ops/prune_runtime_artifacts.py` | M | 3B active 守卫 + 后续锚点保留 |
| `src/hermes_escape_top/core/data/run_transaction.py` | M | 3B 协议升级 + 已审 export 单函数增量 |
| `src/hermes_escape_top/scripts/backfill_history.py` | M | 先前历史版本存储接线，不是 export 新改动 |
| `src/hermes_escape_top/tests/test_runtime_retention.py` | M | 3B 保留兼容测试 |
| `src/hermes_escape_top/core/data/sqlite_snapshot.py` | ?? | 3B 提取的共用 SQLite backup/逻辑摘要 |
| `src/hermes_escape_top/core/data/transaction_evidence.py` | ?? | 3B 标准库协议校验 |
| `src/hermes_escape_top/core/reporting/decision_inputs.py` | ?? | 先前离线/3A 契约 + 3B 抽取后的别名导入 |
| `src/hermes_escape_top/core/reporting/history_versions.py` | ?? | 先前历史版本原语 |
| `src/hermes_escape_top/tests/test_a2_capture_boundaries.py` | ?? | 设计阶段边界验证，不是生产接线 |
| `src/hermes_escape_top/tests/test_decision_input_archive.py` | ?? | 先前离线输入归档用例 |
| `src/hermes_escape_top/tests/test_evidence_anchor_retention.py` | ?? | 锚点保留补丁 21 用例 |
| `src/hermes_escape_top/tests/test_history_versions.py` | ?? | 先前版本存储测试，含后来追加的 seal 用例 |
| `src/hermes_escape_top/tests/test_pre_run_state_archive.py` | ?? | 3A 用例 |
| `src/hermes_escape_top/tests/test_score_transaction_v2.py` | ?? | 3B v2 / 故障 / SIGKILL 用例 |
| `src/hermes_escape_top/tests/test_transaction_before_images.py` | ?? | 已审 export 24 用例 |
| `src/hermes_escape_top/tests/test_transaction_v2_acceptance.py` | ?? | 3B 验收消费者用例 |

明确排除这三份无关未跟踪计划，今后提交也不得夹带：

- `docs/history/2026-09-05_dated_update_schedule.md`
- `docs/history/2026-09-05_post_release_a_20_dimension_review.md`
- `docs/history/2026-09-05_stabilization_update_plan.md`

本轮前新增的交接文档共有七份：历史版本、离线输入、runtime capture design、3A pre-state、3B transaction v2、锚点保留、transaction before-images；本文件另算。后续回注区分历史与当前状态，不把它们当独立批准。

## 3. 当前字节绑定

以下是本轮直接重算的 SHA256，不引用旧文档的陈旧模块 SHA 来证明当前源码。根目录为 `/Users/liweishi/Documents/github/hermes`。

| 文件 | SHA256 |
|---|---|
| `docs/PRODUCTION_RUNBOOK.md` | `b8d195bba4fb68edb1f063f72bc68375d98f9368f3cfd4353b75db3fecd6c441` |
| `ops/README.md` | `9314b684779880810447aa5923e811cefcea59bc753aa883f0f591c97ff5cfea` |
| `ops/morning_acceptance.py` | `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d` |
| `ops/prune_runtime_artifacts.py` | `7d52be95fe428a621c84f9ef8f2eec795ac7a8d5b49d5dbea82bb2d0764d6888` |
| `core/data/run_transaction.py` | `42c96e65a3f2bdcf3f6115411615aa14cb155cd26bab6249d51ddc44e161a6e8` |
| `scripts/backfill_history.py` | `d07f3b05fc0754e52589b0f046949ad7a769a64b0cb3355a9301246c552f07d3` |
| `tests/test_runtime_retention.py` | `4216add92ce9be0bcb3ccae2af3c5b2512ce12a334372819956b35142a4b7384` |
| `core/data/sqlite_snapshot.py` | `c74574309686f8dc8753e7120a2cdabeb2cb437f0e5a47da230783133fbdfd74` |
| `core/data/transaction_evidence.py` | `b6cfe16221170f3bbae1ee10ac14a4d7059e5222a32ef8df6130376b418176be` |
| `core/reporting/decision_inputs.py` | `73a9d9e4c6125196694d69a7ab864e55c7783ac5ddb0ea0242c8d1a4d9f5f3cc` |
| `core/reporting/history_versions.py` | `360e9647b18ffab64173e5c395e2d3b8470b8a681c40a8c383f4a381aa57ae78` |
| `tests/test_a2_capture_boundaries.py` | `e150741fb9969c276df1e4d46b2c4bcb75b3a149a2f08dfbb95c3cff143f1202` |
| `tests/test_decision_input_archive.py` | `baad0738126b6df1b526f7c993bd26bbf0c4b17a807d63c9d56a49b7eda6ed96` |
| `tests/test_evidence_anchor_retention.py` | `170392908b7fffb16c4431ea97595f3e826873de7ba4dfcc37214541342808b8` |
| `tests/test_history_versions.py` | `10e98bf5d51978b584fc465fea92bcdd2c01892d031a3d7ff1b98f68e7a26aff` |
| `tests/test_pre_run_state_archive.py` | `0ad72d39123f6c78e9f1a74ec5fbe7bdea7956062bb297fb1282ecc66d8aa64a` |
| `tests/test_score_transaction_v2.py` | `f4751cb7b4d6b972a075a01f266d5eec08ce20e775b437d5aa426d51ae554ab0` |
| `tests/test_transaction_before_images.py` | `39ec50fdea355327ec2548ac205141feb9d6856fef7a677253ccfab750ff0ea6` |
| `tests/test_transaction_v2_acceptance.py` | `be7f6e21db654d06e9fd3e45c34e1527c6aff2f654134afec5bc7374b25b4d3f` |

短路径 `core/`、`scripts/backfill_history.py`、`tests/` 在本表均以 `src/hermes_escape_top/` 为前缀；不能把它们误定位到仓库根 scripts。

冻结证据为 **5 个目录 / 6 个 JSON**，全部在 `building/reports/`：

| 路径 | 作用 / 使用限制 |
|---|---|
| `history_versions/2026-10-02/equivalence.json` | 第一切片时点，后续再生及历史登记差异已回注 |
| `decision_inputs/2026-10-02/equivalence.json` | 第二切片时点，非当前 376 行模块证明 |
| `pre_run_state/2026-10-03/equivalence.json` | 3A 时点，非后续 SQLite 抽取批准 |
| `score_transaction_v2/2026-10-03/equivalence.json` | 3B 时点，不是当前全树快照 |
| `score_transaction_v2/2026-10-03/legacy_writer_probe.json` | 旧 writer 独立进程探针，须审源并自行重做 |
| `transaction_before_images/2026-10-03/equivalence.json` | 当前 353 文件 package 清单，manifest `be475704...`，四日期 strict 全相等 |

最新 scoring_logic_hash 为 `03b94995fba06e849eef7468d1ba3e9f67bd8038296dfd8cf0e47a694533ad73`。它确实不同于 HEAD 与 3B；本轮不加豁免、迁移映射或预算例外。

## 4. 本轮反馈处理与证据口径

### F1：接受并落实范围说明

提交说明应分列批次及审计状态，不能用“新增一个已批准函数”概括整棵树。当前没有执行提交，以下只是将来获授权时的说明模板：

```text
A2 cumulative candidate snapshot (not production release)

- Prior slices: history versions, offline decision inputs and pre-state capture.
- 3B: v2 transaction/WAL recovery, shared SQLite helpers, evidence validation
  and acceptance reader. Joint external audit PASS for the frozen candidate.
- Anchor retention: v2/unknown-protocol protection and saved-plan rechecks.
  Joint external audit PASS for the frozen candidate.
- Before-image export: scoped and joint external audit PASS, including its
  interactions with the current dependencies.
- Aggregate joint external audit PASS; DEPLOY HOLD; A2 OPEN; Phase B not started.
- No production pipeline wiring, config/flag flip or live-data changes.
- Exclude the three unrelated September plan documents.
```

这个模板不能替代明确的用户提交/推送授权。同日联合外审及澄清已通过，模板据此更新；用户执行授权另记在澄清记录，不把提交批准扩大为部署批准。

### F2：接受限制，不补造历史基线

未提交的 3B 没有一个可检出的 Git commit；删除 export 函数重得旧 SHA 只是字节一致性证明，不声称能恢复当时全部文件与执行序列。现有独立复核应针对 **当前累积树**，而非把重建单文件当成真实历史 checkout。

以后在独立外审和用户授权后按小批次落 commit，保存实际来源。当前不回填或伪造“当日已经提交”的历史，也不只为修证据口径擅自提交未经整体审阅的依赖。

### F3：“函数级登记检查不可达”不成立

一般协议 `validate_inventory` 验证精确七 BUSINESS、合法 evidence 前缀、manifest 及至少两项 evidence；它不检查 `pre_state/` 与所有 `existed=true` 业务文件的一一对应。`validate_input_evidence` 则在后续绑定/提交时调用，不是在 export 前完成这项前像检查。

本轮直接复用原测试的 missing_registration / extra_registration 两个方向，只包裹 export 收集错误；没有改 journal 或绕过上下文。两例均进入 export 并返回：

```text
before-image evidence registration mismatch
```

因此“错角色/越界可被协议先拒绝”成立，但“少/多前像登记必然在协议层先拒绝，函数级检查够不到”不成立。实现和交接无需为这条反馈改代码。

本轮重新跑专测：**24 passed，1.79s**，上述两例的函数级错误另行确证。没有改代码或环境，所以沿用适用的此前 **167 focused / 1710 full / 8治理 / strict 4日期**及用户外审独立复现证据，不再次跑全套来制造重复证据。它们仍不证明整个候选的逐行独立外审完成。

## 5. 联合外审任务

你是独立审计者。只审上述当前累积候选，不改仓库，不运行 daily/morning_acceptance.py，不刷新源，不连接 IBKR，不改 live。不要只读作者文档后给 PASS。

按以下顺序执行，每组的结论应有实际路径/函数与拒收证据：

1. 核对 HEAD、全部 modified/untracked 清单、当前 19 项 SHA；排除无关九月计划。既有模块 SHA 改变必须按当前源码重新审，而非自动沿用旧外审。
2. 逐行审 3B：v1 默认兼容、精确七业务/新 evidence 登记、lease、前像准备、完整 WAL、绑定、COMMITTED 前后异常区别、恢复预核验及旧 writer active 守卫。诚实区分 active 守卫与完整版本回滚。
3. 审 `sqlite_snapshot.py` 抽取和 `decision_inputs.py` 的旧别名/3A 契约：实际 WAL、只读源、逻辑摘要、pending 拒绝与 required/ABSENT，确认不把源文件损坏当正常缺失。
4. 独立运行故障注入：真实子进程 SIGKILL 与新进程恢复，坏后备份拒绝部分恢复，COMMITTED 后清理失败不倒退；明确不是断电实验或实际 scheduled pipeline 接线。
5. 逐行审锚点保留：v2 terminal 数量/容量全保护，未知协议和 legacy 证据标记 fail closed，旧计划执行前复查，链接/畸形 manifest 不能授权删除，普通 v1 仍可清理。容量摘要与 APPLY PASS 不得冒称硬容量合规。
6. 审验收读者：v1 精确七路径仍有效，v2 沿 audit.run_id/decision_id/input_hash 和外部 manifest SHA 验证，拒绝未知角色/缺失/多余/链接/摘要坏；验证 system Python 标准库路径。
7. 对已审 export 复查与依赖的交互，尤其注册集合检查的真实调用顺序、备份来源、异常清理、提交后锚点保留；不能把测试 fixture 的 IN_RUN_CAPTURE 标记当成真实输入消费证明。
8. 检查早期 history/backfill 改动与后来事务/源目录边界无冲突；保留旧历史报告，独立重做最新 comparator。四日期 strict 只说明 manual/v1、include_ibkr=False 的输出与七产物，不证明完整重放。
9. 重跑全部测试、治理、Ruff severe、声明范围的完整 Ruff/mypy/compile；逐项核对新指纹、零 config/flag/预算/比较器/部署脚本改动。已有 ops 类型债如实列出，不增加 ignore 掩盖。
10. 最终分别判定：当前累积树正确性、可否 commit/push、可否部署/A2 闭合。生产调用方、该新格式恢复消费者、全状态重放和 A1 发布证明尚缺，不能因 1710 全绿宣布 A2 完成。

具体运行命令见 3B、锚点保留与前像交接，使用当前源码与隔离数据根。四日期重跑输出写新的 tmp 文件，不覆盖作者冻结 JSON。明确报告没有覆盖的面，而不是用全部测试通过代替逐行协议审计。

## 6. 下一步

当前累积树联合外审及审批措辞澄清已完成。按用户授权和显式白名单提交/推送冻结候选，排除三份九月计划；不得把后续改动混入本次 PASS。真实评分入口接线、完整隔离恢复/重放、A1 发布证明和自然观察仍是后续任务。当前不部署、不重跑官方日任务消红、不关闭 A2、不启动 Phase B。

## 7. 收到联合外审后的时点记录

用户随后提供了 [联合外审原文](2026-10-03_a2_joint_external_audit_report.md)：已独立审当前累积树，正确性 PASS。但报告同时要求在提交消息保留“3B / 锚点保留 / 整树待批”，与其联合审通过的措辞存在冲突，不能由作者私自改成全批正式批准。

本轮重新核对 19 项文件及六份冻结证据均未变化；只归档原文和写 [接收记录](2026-10-03_a2_joint_external_audit_intake.md)，未改实现、未提交/推送/部署。本文 §1 / §4 是编写提示时的审计状态和模板，不代表收到报告后的完整当前状态；当前正确性 PASS、审批标签待澄清、部署 HOLD / A2 OPEN。请依接收记录作一次措辞确认，不需要重做全套外审。

## 8. 同日澄清取代旧待审标签

§7 保留第一次接收时的待澄清状态。外审者随后确认：联合外审就是对 3B、锚点保留及累积交互的独立审查，分片中的 pending 是被取代后未同步的旧模板，不是额外审批步骤。§1 / §4 已按 [澄清记录](2026-10-03_a2_joint_external_audit_clarification.md) 更新。

当前统一标签为：**当前候选联合外审 PASS（候选冻结），未获部署授权；DEPLOY HOLD，A2 OPEN，Phase B 不启动。** 原报告字节与六份冻结 JSON 保留；三份分片交接只追加时点注记。Git 操作只使用显式路径，不用 `git add -A` 或 `git add .`。
