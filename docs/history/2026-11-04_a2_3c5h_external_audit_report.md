A2 3C-5h-A 外审报告:提交观测到正式回执
结论:正确性 PASS;允许按精确范围提交/推送;部署与 A2 闭合不具备。未发现 P0/P1;P2/P3 为已披露的 A1、信任边界与静态债。

仓库:/Users/liweishi/Documents/github/hermes,HEAD 8d16ad8ba639341a38ca5c29e278d12b81bb8efe,未提交。
增量:3 个生产文件 + 2 个新测试文件;基线为证据目录三份 before 与 slice.patch,不是整棵 git diff HEAD。
我未修改仓库/live/证据;未 stage/commit/push;未运行 official daily、morning_acceptance、行情刷新或 IBKR;所有测试在 /tmp/hermes-a2-5h-audit/ 独立 venv 执行。
一、绑定核验(独立复算)
文件	SHA	行数
run_transaction.py	72805884…	663
pipeline.py	ff57e12a…	1529
run_daily_package.py	d5c23a4f…	1904
test_commit_observation.py	e5e0df9a…	235
test_commit_observation_receipt.py	0618c36a…	242
SHA256SUMS.json 22 项逐项匹配,清单自身 SHA 984f8b24…;source-binding.json 5 个实现/测试 + 8 个依赖全部匹配;三份 before SHA 42c96e65…/8780e5ef…/15cb03bc… 匹配。
slice.patch SHA c3c46049… 可干净应用到 before 三文件;diff 为 run_transaction +31/−9、pipeline +7/−1、run_daily_package +80/−4。
5g 旧包 60 项绑定:57 项不变,3 项是本片生产源;5g 13 件、契约 5 件、三份九月计划均未变。
起始 210 个 dirty/untracked 文件中 207 个不变;仅已 dirty 的 pipeline + 两份 append-only 文档变化;journal writer 与 daily wrapper 是先前干净、本片新改的生产文件;总计划 42264 字节前缀、契约 14069 字节前缀均匹配。
未执行 Git 写操作,未触 live。
二、实现审阅(三处生产修改)
A. run_transaction.py — 精确字节摘要与 observer
_atomic_write_json 改为先 json.dumps(..., ensure_ascii=False, sort_keys=True, default=str) + "\n" 编码为 UTF-8 字节,写二进制、flush、fsync、os.replace、目录 fsync,返回写入字节的 SHA256(第 579–600 行)。
_write_manifest 返回该摘要;COMMITTED 写入的返回值保存为 commit_sha256(第 301–325 行)。
observer 在成功 COMMITTED 写入之后、仍持 lease、_clear_active/_remove_backups 之前调用;观测含 9 个字段,不含任何评分 payload/七业务/输入 manifest。写入异常或结果未知时直接 raise,不调用 observer。
构造器(第 249–258 行)在任何 journal 写入前拒绝:非 callable、无 capture_id、非 scheduled、shadow 非 False。
observer 失败发生在 __exit__ 的正常退出路径,不会再次进入 _rollback;测试确认业务/证据保留、journal 仍 COMMITTED。_clear_active 失败同样不倒滚,active 由后续持锁恢复清除。
判断:契约第 2.1–2.3/3 条满足。
B. pipeline.py — 仅显式 capture 转发
公开 score_pipeline 与 _score_pipeline_locked 增加可选 commit_observer;后者在 commit_observer is not None and not capture_inputs 时拒绝(第 199–203 行)。
既有 capture_inputs and (run_type != scheduled or shadow) 拒绝保留;observer 仅透传给 score_run_transaction。
不向 payload/audit/七业务/输入 manifest 添加字段;无全局“最近观测”状态。
判断:契约第 2.4/3.1 条满足。
C. run_daily_package.py — 调用内闭环与正式 receipt
run_score_pipeline 增加默认 false 的 capture_inputs 与可选 observer;observer 无 capture 时拒绝。
_validated_commit_observation(第 1359–1380 行)要求:精确 9 字段;schema/protocol 固定;as_of/decision_id 非空;run_id/capture_id 32 位小写 hex;input_hash/journal_sha256 64 位小写 hex;committed_at 与 started_at 均带时区,且 started <= committed <= now。
_write_run_receipt 仅在 finished scheduled receipt 上携带观测;RUNNING/非 scheduled 直接拒绝;主状态计算不变,观测不能把 FAILED 变 OK。
_run_daily_with_receipt(..., capture_inputs=False):
非 scheduled + capture 立即拒绝;
observe 闭包只保存本次调用观测,重复观测拒绝;
_execute_daily 返回后,逐项匹配 as_of/run_id/capture_id/decision_id/input_hash/protocol,任一不符则清空观测并抛错;
成功 OK 与失败 FAILED receipt 都只携带当前观测;上一调用的观测不重用。
_execute_daily 把 capture_inputs/observer 传入评分;默认路径不改变。
生产 main 仍调用 _run_daily_with_receipt(args, _lease=lease)(capture 默认 false);无 CLI/config/flag 启用、无 scheduler 调用方。
判断:契约第 2.5–2.6/3 条满足。
D. 两个新测试
test_commit_observation.py(235 行):真实 journal 字节摘要/lease/COMMITTED;body/validation/before_publish/after_publish/unknown 五类失败均不签发;observer/cleanup 失败不倒滚;pipeline 不把观测放进 payload/audit;v1/shadow/manual 在 journal 写入前拒绝;两例真实 SIGKILL(before/after observation)由独立进程恢复并断言 journal 字节不变、无 active、RUNNING receipt 未被伪造为 finished。
test_commit_observation_receipt.py(242 行):真实 scorer/transaction 到正式 receipt;同 as_of 两次运行 run/capture 不同、decision 相同;cleanup/broker/receipt/health 四类提交后失败均 FAILED + 有效观测 + 七业务保留;失败的下一次调用不复用旧观测;6 个绑定字段错误均清空观测;8 类无效/陈旧观测不能替换 receipt;默认 OFF 无观测/decision_inputs/broker_cache_publications;两次 receipt 写失败不留旧 OK;shadow/manual 不暴露 capture;RUNNING 不能带观测。
三、独立执行结果
检查	我的结果	作者记录
40 新测试	40 passed / 94.85s	40 / 55.61s
234 八文件关联	234 passed / 90.97s	234 / 83.89s
全套	2056 passed / 1525.18s	2056 / 1358.40s
Governance	8/8 OK,ibkr_readonly=true	8/8
新文件 + run_transaction Ruff	PASS	PASS
全仓 severe E9/F63/F7/F82	PASS	PASS
14 模块 mypy	Success: no issues found in 14 source files	PASS
扩大三生产模块 mypy	15 errors(before 16;无新增归一化消息)	16→15
三生产文件 Ruff	19 = 19 逐条相同	19/19
compile / git diff --check	PASS	PASS
四日期 OFF strict	375 / 06fcbc10…,all_equal,4/4 空差异	同
基线 / 种子	356 / d9137193…;57 / 8557342f…	同
评分指纹	ac025f0f…(before ab97d532…,HEAD 03b94995…)	同
外部故障演练	13/13 PASS,network 0,live 未触	同
扩大 mypy 的 15 条均在 pipeline.py/run_daily_package.py(run_transaction 0),与 before 16 条相比删除了 Need type annotation for "receipt";唯一“位置变化”是 Name "result" already defined on line 982→988,按交接声明只归一化行号,不新增消息。19 条 Ruff 为 pipeline 2 + daily wrapper 17,前后一致,无 ignore/exclude 变更。

四、逐项回答必审十问
摘要是否绑定真正写出的 COMMITTED 字节(含编码/LF)? ✅ json.dumps + "\n" → UTF-8 → 写二进制 → fsync/replace/dir fsync → SHA;测试逐字节重算;body/validation/before_publish/after_publish/unknown 均不签发。
observer 是否在 lease 内、成功提交后、回滚区外? ✅ 在 COMMITTED 写入成功后、_clear_active/_remove_backups 前;observer/cleanup/broker/receipt 失败均保留业务/证据,失败仍如实传播;测试覆盖。
是否只允许显式非 shadow scheduled v2 capture? ✅ 构造器、pipeline、daily 三层校验;默认 OFF 无观测/payload 字段/目录;生产 main 不传 capture_inputs=True;无 CLI/config/flag/scheduler。
身份/日期/协议/时间/receipt 形态是否严格? ✅ 9 字段精确、32/64 小写 hex、schema/protocol/as_of、时区与 started <= committed <= now;同 as_of 两 run 的 run/capture 不同、decision 相同;旧观测不复用。
RUNNING/非正式/旧/未来/naive/错 schema/错身份/两次 receipt 失败? ✅ 8 类无效观测不能替换 receipt;RUNNING 不能带观测;shadow/manual 拒绝;两次最终写失败不留旧 OK;FAILED 保持 FAILED。
两个 SIGKILL 是否真实信号与独立持锁恢复? ✅ -SIGKILL,独立进程持锁 recover_incomplete_score_run,journal 字节不变、无 active、RUNNING receipt 未变成 finished;仅最小事务边界,不是完整 daily/broker/断电证明。
是否没有离线 ops 适配/WebUI/晨验/自算摘要/缓存补发/真实 capture 调度? ✅ 未新增;生产入口仍 OFF;无 journal 自算摘要兜底;5g reader 只在测试中消费 producer 摘要。
静态债是否按声明区分? ✅ 14 模块 mypy PASS;扩大 3 生产模块 15 条(before 16,无新增);Ruff 19/19;full_production_ruff_clean/global_mypy_clean 均为 false 并如实记录;未改忽略集。
四日期 OFF strict/指纹/比较器是否可复现? ✅ 375/06fcbc10…、356/d9137193…、57,4/4 空差异;比较器 19540147… 未改;指纹 ac025f0f…;候选指纹不能借 live 42d207d6… 的 11-04 自然样本通过 A1。
是否分别判定并列未证明事项? ✅ 见第六节。
五、P0 → P3 Findings
P0:无。P1:无。

P2-1(A1 门槛,非本片代码缺陷)候选指纹变更仍需发布/迁移/旧 writer 回滚证明
位置:scoring-fingerprint.json;decision_identity.py 未改(0765fe3c…),排除集未改。
触发:把本片 2056/四日期 OFF strict 当作 A1 发布等价证明。
影响:候选指纹从 ab97d532… 变为 ac025f0f…;当前 live 是 c1f4b8f/42d207d6…,11-04 自然样本属于 live,不属于候选;不能替代 scheduled certification 字节、迁移或旧 writer 回滚证明。
证据:OBSERVATION.md 明确“live 的 v1/42d207d6 不是 A2 v2/ac025f0f 的自然样本”;scoring-fingerprint.json 三 scopes 分列。
处置:A1 发布/迁移/回滚门槛保留,另做证明;不得加等价豁免。
P2-2(信任边界,已披露)receipt 观测是本机生产者声明,不是签名
位置:run_daily_package.py:1359–1380/_write_run_receipt;契约第 3 节。
触发:同用户同时篡改 journal 与正式 receipt,或敌对进程/OS。
影响:5h-A 交付的是 LOCAL_PRODUCER_RECEIPT,不提供独立密码学证明;未来 ops 适配器仍须选唯一正式 run/audit 并匹配身份,5g 读取器本身不认证摘要来源。
证据:交接第 3 节、契约第 3 节;测试只证明 producer→receipt 字节通路。
处置:接线时明确标注来源;不把 receipt 当签名;未来适配器单独外审。
P2-3(静态债,已声明)扩大 mypy 15 条 / Ruff 19 条
位置:pipeline.py、run_daily_package.py(15 条 mypy);pipeline 2 + wrapper 17(Ruff)。
触发:把“14 模块 PASS”读成所有修改文件全净。
影响:两生产文件仍有既有类型/风格债;本片未新增归一化消息,且删除 1 条 annotation 消息;未改 ignore。
证据:mypy-baseline-comparison.json(16→15,new=[]);ruff-baseline-comparison.json(19/19 same);static-gates.json 的 full_production_ruff_clean=false、global_mypy_clean=false。
处置:保持声明;若要清零另开片,不在本片用 ignore 消红。
P3-1(时间窗)保守检查不是单调时钟证明
_validated_commit_observation 的 started <= committed <= now 只做时区/窗口拒绝;时钟回拨/前跳可能误拒或放宽;交接已声明不是 monotonic proof。P3。
P3-2(SIGKILL 范围)两例仅最小事务边界
真实信号/独立恢复,但不覆盖完整 daily、broker publication、SQLite 耐久或断电;交接已明确。P3。
P3-3(observer/cleanup 失败后的 active)
observer 或 _clear_active 失败时 active/backups 可能残留,由后续持锁恢复清除;journal 不变;交接已说明。P3。
P3-4(默认 OFF,无生产接线)
新通路只能由内部 capture_inputs=True 触发;生产 main 未传;无 CLI/config/flag;未来接线必须先单独审查;本片不改变默认 scheduled 行为。P3(按设计)。
P3-5(自然样本分离)
11-04 acceptance 为 live c1f4b8f / 42d207d6…,PASS、strategy WARN、3/3 行情准入;这是已发布热修的自然观察,不是 A2 ac025f0f… 的 ON 样本;五日目标未完成,也不关闭 A2。P3。
六、未证明事项与边界
完整自动 T1→T2 生命周期;hermetic 运行环境;更广故障/耐久性矩阵;断电/磁盘耐久;真实 broker publication 全链路。
候选 ac025f0f… 的 A1 发布/迁移/旧 writer 回滚证明;scheduled certification 字节等价;CI。
离线 ops 只读适配(5.B):唯一正式 run 选择、v1/OFF→NOT_APPLICABLE、v2 缺锚→UNKNOWN、错绑定/重复 audit/旧 run 拒绝、不读当前缓存/不联网/不恢复/不补发——尚未实现。
晨验/WebUI 接线、自然 ON 样本、明确发布授权;本片不关闭 A1/A2/Phase B。
七、三个独立判定
正确性:PASS。 精确字节摘要、observer 时序/lease/回滚边界、显式 capture 限制、默认 OFF、receipt 形态与身份/时间校验、同 as_of 隔离、失败保留、两例 SIGKILL、5g 消费均通过独立复跑;未发现 P0/P1。
提交/推送:允许精确范围。 三个生产文件 + 两个新测试 + 本片证据/交接;按 slice.patch 与 before 绑定提交;不得 git add -A,不得混入主目录其他 A2 片、三份九月计划、私有 capture 或 live 数据;提交后检查新 CI。不是整棵 dirty tree 的总批准。
部署 / A2 闭合:不具备。 需候选 A1 证明、离线 ops 适配、晨验接线、自然 ON 样本、CI、用户明确授权、无 writer/避开 07:00–07:20/保留 live config 的 R6 条件。live 仍 c1f4b8f;A2 仍 OPEN;Phase B 未启动。DEPLOY HOLD;A2 OPEN;Phase B not started。
(本轮只读仓库/证据/live 11-04 报告;所有测试/指纹/比较器在 /tmp/hermes-a2-5h-audit/ 独立 venv 与临时 baseline 执行;未对仓库执行 add/commit/push/deploy,未运行 official daily、morning_acceptance 主程序、行情刷新或 IBKR。)