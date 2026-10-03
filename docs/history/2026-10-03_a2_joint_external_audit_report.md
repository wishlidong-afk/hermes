联合外审完成。我按提示的 10 个步骤逐条执行:清点并复算 19 项 SHA、逐行审 3B 协议与 WAL、审 SQLite 抽取与 3A 守卫、跑真实子进程 SIGKILL 用例、审锚点保留与验收读者、做独立故障/边界探针、重跑全套与四日期 strict。

联合外审结论
当前累积树正确性:通过。 我在 3B 协议、SQLite/WAL、回滚与提交边界、锚点保留、验收读者、export 交互六条线上都没有找到可利用缺陷;19 项声明 SHA 全部命中。
可 commit / push:可以,但必须按批次分列审计状态。 这不是"一个已批准特性",而是三批待批 + 一批已批的累积候选;你给的提交说明模板(第 104–117 行)方向正确,请照用。
可部署 / A2 闭合:不可以。DEPLOY HOLD、A2 OPEN、Phase B 不启动 —— 与本文第 17 行判定一致。
1. 清单与字节绑定(步骤 1)
✅ HEAD 68e6b7fb…;7 个受跟踪改动 + 12 个未跟踪源码/测试,与第 23 行完全一致;三份九月计划确实未被改动、也不在实现清单内。

✅ 19 项 SHA 逐个重算,19/19 命中(0 mismatch),含 run_transaction.py 42c96e65…、prune_runtime_artifacts.py 7d52be95…、transaction_evidence.py b6cfe162…、sqlite_snapshot.py c7457430…、test_transaction_v2.py f4751cb7… 等;6 个冻结 JSON 的 SHA 也与第 85–94 行的登记一致。

✅ 受跟踪 diff 只覆盖 7 个文件;config / flag / 评分 / 路由 / 版本预算 / 比较器 / 部署脚本 / 依赖锁 / pipeline.py / identity-revision 全部零改动(我按路径逐个 git diff 核空)。

2. 3B 协议逐行审(步骤 2)
边界	我的核对结果
v1 默认兼容	✅ 无 capture_id 走 v1:schema=hermes-score-run-transaction-v1、capture_id=None、行内无 role;pending_score_run_transaction 对 schema_version ∈ {None, v1} 仍放行
精确七业务 + evidence 登记	✅ validate_inventory 强制 business == business_paths(as_of) 七项精确、evidence 必须落在 archive/decision_inputs/<capture_id>/、至少两项且含 manifest.json;我探针删一个业务文件 → ValueError: business artifacts mismatch
v2 metadata 约束	✅ run_type != scheduled 或 shadow != False 直接拒绝(manual/shadow 两例我都实测拒绝)
lease	✅ assert_pipeline_lease 校验 capability/active/PID/线程/路径;错根、无 lease、失效 lease、错 run、错 capture 五向均拒绝(测试矩阵 + 我复核实现)
前像准备	✅ SQLite 走 copy_sqlite_snapshot(只读 URI + BEGIN + integrity + 前后逻辑摘要比对 + busy/locked 立即拒绝),非 SQLite 走 clonefile/cp -c 回退 copy2
完整 WAL	✅ 测试覆盖"WAL 中有已提交行";我另确认提交后证据留存、源 main/WAL 字节不被导出改动
绑定与提交	✅ bind_score_run_inputs 只在匹配 pending v2、未绑定、manifest 非链接时写入;退出上下文时先 validate_input_evidence 再写 COMMITTED;提交写失败时按"读回状态是否已 COMMITTED"决定是否回滚,并用 commit outcome unknown; journal retained for inspection 兜底
COMMITTED 后清理失败	✅ 有专测:失败不倒退业务与证据
恢复预核验	✅ v2 回滚前先校验全部备份的格式/权限/摘要,再动第一个文件 —— 我的探针也确认"坏后备份 → 前件不恢复"
旧 writer active 守卫	✅ active 指针写 run_id=V2_REQUIRES_UPGRADED_WRITER + v2_run_id,v1 读取路径看到不匹配的 run_id 即拒绝;我在 prune 侧也确认 v2 active 指针会阻断旧计划执行
诚实性:文档把"active 守卫"与"完整版本回滚"分开表述,实现层面也确实只是 fail-closed 守卫,没有夸大成旧 writer 能完整回滚 v2。

3. SQLite 抽取与 3A 契约(步骤 3)
✅ decision_inputs.py 现在 376 行 / 73a9d9e4…,通过 from ..data.sqlite_snapshot import copy_sqlite_snapshot as _copy_state_database, sqlite_state_hash as _sqlite_state_hash 保留原调用契约,别名与函数签名一致,异常类型与消息也保持原样。

⚠️ 诚实说明一处外审限制:旧 430 行版本从未进入 git 对象库(我试过 git cat-file 两个历史 SHA,均 Not a valid object name),所以"原样提取"我只能靠行为与调用面验证,不能做旧/新函数体的字节 diff。作者在 3A 交接回注里也承认这是提取后的当前状态,没有反过来拿旧 SHA 证明新文件 —— 处理方式正确。

✅ 3A 守卫仍在:export 与离线捕获互不干扰,pending v2 时离线捕获仍拒绝(recovery of the pending score run);required/ABSENT 语义与损坏不当缺失的行为保持。

4. 故障注入(步骤 4)
✅ 我重跑了真实子进程用例 test_sigkill_then_a_different_process_recovers_or_preserves_committed_v2 的三个阶段(during_write / after_binding / after_commit),3 passed,确实是 SIGKILL 子进程 + 新进程恢复,不是我方内存内模拟。加上"COMMITTED 后清理失败不倒退""坏备份拒绝部分恢复"两项,提示第 4 步要求的三件事都被真实覆盖。文档同时明说这不是断电实验、也不是真实 scheduled 接线 —— 一致。

5. 锚点保留(步骤 5)
我独立造了四种 journal 直接跑 build_prune_plan:

场景	结果
普通 v1 terminal(keep=0,max_bytes=1e9)	✅ 仍在 delete 列表,可清理
未知协议(schema_version=future-v9)	✅ protection_reason=unknown_transaction_protocol,受保护
legacy 记录带 capture_id 标记	✅ evidence_markers_on_legacy_record,受保护
v2 terminal(keep=0,max_bytes=0)	✅ decision_input_evidence_anchor,受保护;capacity_exceeded=True、retained_bytes 只统计已解析 terminal 清单
✅ Apply 时复查有效:我把已生成计划对应的 manifest 改成非法 JSON 后执行 → deleted_count=0,跳过原因就是 JSON 解析错误,run 目录保留;namespace/runs 被换成链接时同样拒删。链接、悬空、腐坏、非对象 manifest 都不构成删除授权。

✅ 报告口径诚实:capacity_exceeded 单独表示"受保护记录超容量",runbook 与 ops/README 都明写 APPLY 的 PASS ≠ 容量达标、暂保留不是引用式 GC —— 与提示第 5 步的要求一致。

6. 验收读者(步骤 6)
✅ _collect_transaction v1 仍要求精确七业务名;v2 额外要求:validator 文件存在于 current/hermes_escape_top/core/data/transaction_evidence.py(缺失→FAIL)、validate_inventory、binding 的 decision_id/input_hash 必须匹配 scheduled audit、validate_input_evidence 用数据根重算。

✅ 我确认了最容易出错的那条:transaction_evidence.py 只用标准库,并且真有一个用 /usr/bin/python3 -S(禁 site-packages)加载它并调用 validate_input_evidence 的子进程用例,我已单独重跑通过。这正好支撑提示第 6 步的"验证 system Python 标准库路径"。

✅ 验收侧 11 个 fail-closed 变体(未知角色、重复、错路径、未知 schema、错 decision、错 hash、缺 validator、manifest 摘要坏、文件坏、多文件…)都在。

7. export 与依赖交互(步骤 7)
✅ 复查通过:regist开集合检查在进入上下文后才可能触发(协议层先拦错角色/越界),真实 v2 事务端到端链路(export → 写 pre_state.json → bind → COMMITTED)在我自己的探针里跑通,提交后 capture root 与七份前像保留、backups/ 被删除 —— 这正是 3B 与锚点保留补丁的交互点,行为正确。

✅ 测试里的 IN_RUN_CAPTURE 顶层清单只在隔离 fixture 内使用(第 55–60 行 isolated-before-images-fixture),validate_input_evidence 会把它当协议标记而非真实性证明;文档第 155 行也明确要求外审不要把 fixture 标记当消费证明。我按此口径判定:这不是生产消费证据。

8. 早期 history/backfill 与事务边界(步骤 8)
✅ 无冲突。需要指出的唯一结构点:v2 证据路径由 checked_path(data_root, path) 约束在数据根之下,而 history 版本根在 history 根的同级;两者当前没有交集,所以互不影响。将来若要让事务登记版本根文件,必须把版本根显式纳入 checked_path 的根集合,否则会被"outside data root"拒绝 —— 这是设计边界,不是缺陷。

✅ 我独立重做了最新 comparator(/tmp/review-cs-equivalence.json):all_equal=true,4/4 strict_differences=[];候选 353 文件 manifest be475704…、基线 341/062eea7f…、seed 77/c119ae18… 与作者 JSON 逐字一致,四个 input_hash 也与第 108–115 行登记一致。没有新增忽略项,比较器 SHA 未变(19540147…)。

9. 重跑与门禁(步骤 9)
检查	我实测
全套	1710 passed,155.05s
test_score_transaction_v2 + v2_acceptance + evidence_anchor_retention	73 项收集,SIGKILL 三项子集通过
Governance	8/8 OK,ibkr_readonly=true
Ruff(14 个改动/新增 py + 全仓 E9/F63/F7/F82)	全部 PASS
mypy(三个新/改核心模块)	零 issue
compileall(src/ops/scripts)	PASS
git diff --check	无诊断
指纹	HEAD 42d207d6… → 候选 03b94995fba06e849eef7468d1ba3e9f67bd8038296dfd8cf0e47a694533ad73,与第 96 行一致
✅ 已有 ops 类型债如实列出,未被新增 ignore 掩盖:ops/morning_acceptance.py 有 4 个 mypy 错(382、1259、1261、1263),我核对了 git diff -U0 的 hunk 范围(153、420–510),这四行都不在改动内,属预存债,与 3B 交接的说法一致。

发现(均不阻塞)
F1(中,提交前用模板落实)——累积范围与审计状态必须随提交一起带上。 19 个文件横跨四个批次,其中 3B 与锚点保留至今没有独立外审结论,export 只有范围性 PASS。你第 104–117 行的模板已经处理了这点,请务必原样带入提交信息,并保留 DEPLOY HOLD; A2 OPEN; Phase B not started。这样将来任何一次审计都能从 commit message 直接看出"哪些文件属于哪一批、哪一批获批到哪一步"。

F2(低,记录)——"原样提取"无法从对象库独立还原。 旧 430 行版本从未入库(历史 SHA 都不是 git 对象),所以"SQLite 原语原样抽取"只能靠行为等价 + 3A 58 项回归 + 别名一致来支撑,做不到函数体字节 diff。文档第 13/123 行已经诚实地只声明"剩余字节 SHA 等于 3B 登记值",没有声称能恢复当日全树 —— 建议保持这个措辞,以后按 F2 的小批次落 commit 才能真正消掉这条限制。

F3(很低,口径提示)——容量指标只覆盖"已解析 terminal 清单"。 retained_bytes 不含链接/畸形 manifest 的目录,capacity_exceeded 也不阻断 APPLY。文档已明文披露(runbook 第 16 行、ops/README 新增段),我不建议改代码;只提醒后续做引用式 GC 时要重新定义这两个指标,别让运维把 capacity_exceeded=false 误读成"磁盘没超"。

三个判定(步骤 10)
正确性:通过。 协议、WAL、回滚/提交边界、守卫、保留、验收读者、export 交互均无缺陷,证据自洽且可独立复现。
commit / push:可以,前提是提交信息按批次分列审计状态(你的模板),并明确"联合外审结论为:export 范围 PASS,3B 与锚点保留待批,整树待批"。不要用一次提交暗示整体获批。
部署 / A2 闭合:不可以。 仍缺生产调用方、该格式的恢复消费者、完整非空状态重放、A1 新指纹(03b94995…)的发布/迁移证明与自然观察。1710 全绿不能替代这些门槛。
(复核产物:/tmp/review-cs-probe.py、/tmp/review-cs-prune2.py、/tmp/review-cs-wal.py、/tmp/review-cs-equivalence.json、/tmp/review-cs-baseline;未改动仓库任何文件。)
