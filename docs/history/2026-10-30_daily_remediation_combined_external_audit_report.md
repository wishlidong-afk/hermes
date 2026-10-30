Hermes 近期故障补丁统一外审报告
结论摘要:组合正确性 PASS;允许按精确路径提交/推送;deploy / A2 闭合不具备。未发现 P0/P1 缺陷,列 P2/P3 观察项。

候选:/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23,分支 codex/daily-failure-evidence,HEAD 2db0cdc562309b6222a69aaee8dbdaf51c763b93,origin 为本机路径。
范围:4 个已跟踪文件 + 2 个新测试文件;git diff = 49 additions / 9 deletions(未含两个未跟踪测试)。
我未修改候选、未 stage/commit/push、未运行 official daily / morning_acceptance.py / IBKR / 行情刷新;所有产物在 /tmp/hermes-remediation-audit/。
一、候选与证据绑定(独立复算)
六个文件当前 SHA 与交接完全一致:

文件	SHA	行/用例
requirements.txt	037be4f2…	certifi pin
requirements.lock	71fc586a…	32 包
run_daily_package.py	abb69acb…	失败步骤 + 失败健康报告
web/health.py	211e9ffd…	冲突去重展示
test_daily_failure_evidence.py	362b877b…	9
test_market_conflict_counts.py	5473f758…	23
证据绑定:

三处证据清单 SHA 全部匹配:daily_failure_remediation/2026-10-23/equivalence.json = 7df7bfe8…;dependency_security/2026-10-23/SHA256SUMS.json = fdf26f21…(18 件);market_conflict_reporting/2026-10-24/SHA256SUMS.json = cbf6118c…(8 件)。26 件逐项摘要 0 不符。
依赖更新仅 certifi 2026.4.22→2026.10.19、urllib3 2.7.0→2.8.0;其余 30 个版本/哈希记录逐项相同,32 包总数不变;constrained regeneration 与候选 lock 的结构化版本、完整哈希集完全一致。
四个 wheel/sdist SHA256 与 PyPI 官方 JSON 一致,均未被 yank;download-verification.json 四项全 match。
market_conflict_reporting/.../before/health.py 与 git archive 2db0cdc 的 web/health.py 字节相同(a73f397c…)。
当前四日期 strict 报告绑定 candidate 343 文件 / 4e2ed959…、baseline 341 / 062eea7f…、seed 57 / 8557342f…,all_equal=true,4/4 空差异;比较器 19540147… 未改、无新增忽略项。
评分指纹实算 42d207d6…,与候选开始前一致;七个核心文件(config、admission、witness、third_source、identity、revision、pipeline)与基线逐字节相同。
旧 daily/dependency 证据绑定 342 / 67fa82a4…(当时尚无冲突计数测试);当前 343 是加入 test_market_conflict_counts.py 后的组合时点。两者是不同增量,未互相覆盖,不能互换。✅
二、三项契约的实现审阅
A. 失败运行证据(run_daily_package.py)
实现与契约一致:

payload 初始化为 None(第 1605 行),仅保存本次 _execute_daily 的返回值;不存在旧 payload/合成 hash 路径。
最终 receipt 前设 context["step"]="run_receipt"(第 1620 行),成功辅助资金流步骤不再被误记为失败位置。
异常路径写 FAILED receipt(第 1633 行),仅当 payload is not None and failed is not None 才尝试失败健康报告(第 1642 行);健康写入用 except Exception 捕获并打印(第 1643–1646 行),原异常由末尾 raise 保留。
_write_run_receipt 写失败时返回 None 并删除旧 receipt(第 1448–1461 行),因此失败路径不会用合成 health 替代缺失 receipt;payload is None 时不写任何报告。
9 个用例覆盖:失败步骤归属、显式/隐式日期、当前 input/decision 绑定、旧 OK 报告被 FAILED/CRITICAL 取代、次级报告失败保留原异常、评分未返回不造报告、FAILED receipt 缺失不造报告、首次健康失败只能由失败报告替代、shadow/manual 不发布官方证据。
我实跑 test_daily_failure_evidence + test_run_receipt_writer + test_health_truth = 75 passed;全套 1513 passed / 201.14s(作者 152.21s;计数一致,环境不同)。
边界:报告 JSON/MD/按日 archive 不是新原子多文件事务,无 outbox/断电保证;无当前 payload 的早期失败无法形成完整绑定报告;这些在交接中已明确,未发现越界承诺。

B. 依赖安全(requirements.txt / requirements.lock)
pip-audit -r requirements.lock: 0 known vulnerabilities(exit 0)。
旧 lock: 4 个不同 advisory ID(urllib3 PYSEC-2026-4175/4176/4177;certifi PYSEC-2026-4320),exit 1。当前 pip-audit 打印 5 行,因为 certifi 的 PYSEC-2026-4320 同时列出 fix 2026.10.18 与 2026.10.19 两个修复版本,不是 5 个不同漏洞。
离线探针(旧/新两环境,均 network_attempts=0、tls_verification_enabled=true):
旧 certifi 2026.04.22 / urllib3 2.7.0:超长 chunk line 接受,受影响根 emSign ECC Root CA - G3 存在,exit 1。
新 certifi 2026.10.19 / urllib3 2.8.0:超长 chunk line 拒绝(Response chunk size line exceeded maximum allowed length),受影响根 移除,exit 0。
生产源码扫描未发现自定义 proxy_ssl_context/CERT_NONE/verify=False;仅在 test_safety_invariants.py 的禁用模式字符串中出现。部署环境的代理配置、OS/JVM 信任库未核实,urllib3 2.8.0 的代理 TLS 行为变更不能视为已覆盖。
旧基线环境 32 包、新候选环境 32 包;pip check 兼容;候选安装的 certifi/urllib3/numpy/scipy/pandas 与 lock 一致。
C. 冲突去重展示(web/health.py)
仅在 _add_blocked_market_admission 中调用 _market_admission_attempt_summary(第 380 行);该函数只读 rows/rejected_rows,不改变 status、layer、原始计数或 admission 结果。
身份键严格为 (symbol, date, status, candidate_sha256, witness_sha256)(第 900–906 行);五字段必须为非空字符串,后两个必须是 canonical 小写 64 位 hex;否则 unique_conflicts=UNKNOWN。
rejected 过滤与既有 _market_admission_rejected_detail 一致:admitted is False and blocking is not False(第 894–897 行);admitted 行与非 blocking 的延后 BTC 不计入。
行数与原整数 rejected_rows 对账失败、rows 非 list、行非 dict、count 非 int/bool 或 ≤0 → 两者 UNKNOWN;身份不完整但行数对账 → unique_conflicts=UNKNOWN attempts={count}。
23 个用例覆盖:相同身份三行→unique_conflicts=1 attempts=3;任一身份字段不同→2;缺字段/错误类型/非小写 hex→UNKNOWN;计数不符/布尔计数/畸形 rows→两者 UNKNOWN;admitted/deferred 不膨胀;component-only 分层与原始计数不变。
我实跑 test_market_conflict_counts + test_health_truth = 64 passed;离线预览为 rejected=3 unique_conflicts=1 attempts=3,live 10-24 报告仍因旧代码不显示该字段(未部署)。
三、独立执行结果
检查	我的结果
新测试	9 + 23 = 32 collected / pass
64 子集(冲突 + health truth)	64 passed
75 子集(daily + receipt + health truth)	75 passed
4 文件 focused	98 passed / 0.96s
全套	1513 passed / 201.14s
治理	8/8 OK,ibkr_readonly=true
Ruff 变更文件 + 全仓 severe	PASS / PASS
mypy 4 模块	Success: no issues found in 4 source files
compile / pip check / git diff --check	PASS / 兼容 / PASS
候选 pip-audit	0 known vulnerabilities
旧 lock pip-audit	4 个不同 ID(5 行),exit 1
旧/新离线探针	FAIL(exit 1)/ PASS(exit 0),network 0
四日期 candidate strict	343 / 4e2ed959…,all_equal,4/4 空差异
旧 runtime 四日期	4/4 payload 与七业务摘要与 candidate/冻结记录一致
指纹	42d207d6…(candidate = baseline)
自然报告(只读复核):

日期	状态	完成至 as_of	关键证据
10-22	FAIL	2026-10-20	SOXL PRICE_MISMATCH(3.1067%)
10-24	FAIL	2026-10-22	FNGU VOLUME_MISMATCH(25.1322%),third=NEITHER_WITHIN_POLICY
10-25	PASS	2026-10-23	receipt/audit/transaction PASS
10-26	PASS	2026-10-23	同一完成日期,不算新交易日
10-27	PASS	2026-10-26	
10-28	PASS	2026-10-27	
10-29	PASS	2026-10-28	
10-30	PASS	2026-10-29	5 个不同完成日期;JSON 2054b6f3…、MD fd040446… 与交接一致
10-30 报告 release.name=2db0cdc_20260922_233427、post_deploy_certification=CERTIFIED、strategy_decision=WARN(IBKR stale、dollar age=7d、NAAIM retired),总体 PASS;这是旧 live 2db0cdc 的自然观察,不是候选样本。

四、P0 → P3 Findings
P0:无。P1:无。

P2-1(安全,残余)部署环境代理 TLS 未核实
位置:requirements.lock:557(urllib3 2.8.0);交接 “proxy TLS 行为变更”段。
触发:部署环境若通过代理并依赖 destination TLS 覆盖 proxy TLS。
影响:urllib3 2.8.0 的官方行为变更可能在未审计的代理配置下改变证书校验语义;本仓库源码无自定义 proxy TLS,但未核实部署环境/OS/JVM 信任库。
证据:源码 grep 仅命中 test_safety_invariants.py 的禁用模式字符串;交接 §2 明确披露“未核实部署环境代理配置”。
处置:部署前单独核实代理配置与信任库,或在部署清单中列为显式检查项;不要用“源码无自定义代理”替代环境核实。
P2-2(展示,低)240 字符截断可能压缩原有 detail
位置:web/health.py:380(新 summary 前插)、:396([:240])。
触发:原有 rejected_detail/evidence_text 很长且前面新增约 38 字符的 summary。
影响:原有 detail 可能比改动前更早被截断;仅影响页面文案,不影响计数/状态/原始 rejected 字段。
证据:测试断言 FNGU 2026-10-23 VOLUME_MISMATCH 仍在 detail 中;无超长 detail 用例。
处置:若页面文案完整性重要,可先展示 summary 再对旧 detail 单独限长;否则接受。
P3-1(daily,边界)失败健康写入只捕获 Exception
位置:run_daily_package.py:1643–1646。
触发:次级健康写入期间收到 KeyboardInterrupt/SystemExit 等 BaseException。
影响:原失败异常可能被中断异常替换;正常 OSError/写入异常已被捕获并保留原异常。
证据:9 个用例覆盖 OSError,未覆盖 BaseException。
处置:可选改为 BaseException;不构成当前契约缺陷。
P3-2(审计口径)旧 lock “4 项 advisory” 与 pip-audit “5 行”
位置:dependency_security/2026-10-23/verification-summary.json(audit_before: 4);baseline-audit.json。
触发:把 pip-audit 输出行数当作不同漏洞数。
影响:certifi PYSEC-2026-4320 因两个 fix 版本被列两次,实际不同 ID 为 4;不影响“旧红/新绿”结论。
证据:我实跑旧 lock 得 5 行、4 个 ID;候选 0。
处置:报告/交接注明“4 个不同 ID、5 行展示”,避免读者误算。
P3-3(自然报告)10-30 认证块的 next_scheduled_at 为 2026-09-23
位置:/Users/liweishi/.hermes/logs/acceptance/morning_acceptance_2026-10-30.json;web/health.py:109–135。
触发:把 next_scheduled_at 读成“下一次运行时间”。
影响:它是 release attestation 后的首个自然调度点(2026-09-22 attestation → 2026-09-23),不是 10-30 的下一次运行;认证状态由 release/policy 哈希与报告时间决定。
证据:current_attested_at=2026-09-22、report_generated_at=2026-10-30、status=CERTIFIED。
处置:文档/页面标注该字段为“attestation 后首个调度点”;不改代码。
P3-4(证据自含性)daily 证据仅 equivalence.json
位置:building/reports/daily_failure_remediation/2026-10-23/。
触发:单独查阅 daily 片证据。
影响:1490 全套日志在 dependency 包中,不在 daily 包;combined prompt 已说明,但 daily 包本身不自含。
证据:目录仅 1 个文件;dependency full-suite.log 为 1490。
处置:若需单片自含,后续补 daily 的 full/focused 日志;当前不影响组合结论。
P3-5(时间点)342 与 343 文件绑定不可互换
位置:daily/dependency evidence(342/67fa82a4…)vs 当前 market_conflict evidence(343/4e2ed959…)。
触发:把旧 342 报告当作当前组合的 strict 证明。
影响:343 多出 test_market_conflict_counts.py;旧报告是当时时点,不能覆盖新字节。
证据:我复跑当前候选得 343/4e2ed959…;342 报告仍在旧包中。
处置:提交/发布时引用 343 报告;旧 342 保留为历史时点。
五、实际检查范围与未覆盖边界
已检查:六文件 SHA/行数/用例数、4 文件 diff 49/9、三份交接、9+23 测试逐行、_run_daily_with_receipt/_write_run_receipt/_write_system_health_report、_market_admission_attempt_summary 及其调用点、lock 结构化 diff/PyPI 哈希/constrained regeneration、旧新 venv 的 pip-audit 与行为探针、全套/治理/Ruff/mypy/compile/pip/diff、四日期 candidate 与 old-runtime、指纹、七核心文件、三处证据清单 26 件、10-22/10-24/10-25..10-30 自然报告只读复核。

未覆盖:云端 CI(无 PASS 声明);候选自身的自然 scheduled 样本(10-30 是旧 live 2db0cdc);部署环境代理/OS/JVM 信任库;报告四文件原子事务/断电耐久性;自动重试/outbox;线上 health 页对新展示的真实渲染;forwarder 下一次自然执行;主目录 A2 3C-5h A/离线适配/晨验接线/完整自动 T1→T2/新指纹 A1 迁移回滚;本机绝对路径的披露不等于凭证审计。

六、三个独立判定
代码正确性:PASS。 三项契约的实现、测试、证据绑定与独立复跑一致;49/9 的改动范围内未发现 P0/P1 缺陷。P2/P3 为残余环境风险、展示截断、口径与时间点说明,不阻断本片正确性。
提交/推送技术许可:允许按精确路径提交这六个文件及相关证据/交接——requirements.txt、requirements.lock、run_daily_package.py、web/health.py、test_daily_failure_evidence.py、test_market_conflict_counts.py,以及 daily_failure_remediation/2026-10-23/、dependency_security/2026-10-23/、market_conflict_reporting/2026-10-24/ 和三份交接/本文。不是整树总批准;不得 git add -A,不得混入主目录 A2、三份九月计划或私有 capture;提交说明须按 daily/依赖/冲突三片分列,并保留“342/343 不同时点、旧红结果不改成绿”的表述。
部署 / A2 闭合:不具备。 live 仍为 2db0cdc_20260922_233427;候选无自然样本、无云端 CI、无部署环境代理/信任库核实、无报告原子事务/断电保证、无自动重试/outbox;forwarder 新等待规则的自然执行仍未观察;A2 的 3C-5h A、离线只读适配、晨验接线、完整自动 T1→T2、新指纹 A1 迁移/回滚均未完成。DEPLOY HOLD;A2 OPEN;Phase B 未启动。
（本次外审只读候选与 live 报告;所有测试/探针在 /tmp/hermes-remediation-audit/ 的独立 venv/临时目录执行;未对候选执行 add/commit/push/deploy,未运行 official daily、morning_acceptance.py、行情刷新或 IBKR 操作。）






用量 25.6M tok
