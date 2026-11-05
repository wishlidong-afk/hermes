A2 3C-5h-B 离线适配 + 两项内部 P2 修正外审报告
结论:两项内部 P2 均已复现并闭合;当前 B 版 + 修正的正确性 PASS;允许按精确范围提交/推送;部署与 A2 闭合不具备。未发现 P0/P1;P2/P3 为已声明的 A1、信任边界、静态债与证据精度。

仓库:/Users/liweishi/Documents/github/hermes,HEAD 8d16ad8ba639341a38ca5c29e278d12b81bb8efe,未提交。
本片只改 core/reporting/scheduled_broker_publication.py(163 行,e33a71b5…)与 tests/test_scheduled_broker_publication.py(457 行,023f2646…);旧 B 两文件 252ff929…/144aeace… 仅作修正前对照。
我未修改仓库/live/证据;未 stage/commit/push;未运行 official daily、晨验、行情刷新或 IBKR;测试在 /tmp/hermes-a2-5h-audit/ 独立 venv 执行。
一、绑定核验(独立复算)
项目	结果
两当前源码 SHA / 行数	e33a71b5… 163 / 023f2646… 457 ✅
新证据清单 SHA256SUMS.json	fb66f8eb…,33 件逐项匹配 ✅
source-binding.json	2 个实现 + 18 个依赖,全部匹配 ✅
before/ 两源码	252ff929… / 144aeace…,匹配 ✅
slice.patch	c3c46049… 可干净应用到 before 两文件 ✅
旧 B 证据	24 件全部匹配,清单 b9d8515b… ✅
旧 A 证据/源码	13 源码 + 22 证据匹配 ✅
旧 B 源码清单	377 / 570da621… ✅
当前候选清单	377 / 24f37156…;与旧 B 差集仅 2 修改、0 新增、0 删除、375 共有不变 ✅
范围	起始 1256 件,1251 件原字节不变;变化为 2 源码 + 3 文档追加;旧前缀匹配;无 Git 写/live 变更 ✅
二、两项 P2 修正的独立审阅
P2-1:未知外层 audit schema 曾可产生辅助成功
修正位置:scheduled_broker_publication.py:103–117。

仅当记录含 payload 包裹时才检查外层 schema;明确存在时必须为 escape-top-greenfield-audit-v1;无该字段的历史包裹仍接受;未包裹的旧 score-v1 payload 走原 payload schema 检查,不套用外层要求。
未知字符串 / null / 数字(future-audit-v999、None、0)在 v1 与 v2 链条下均拒收为 UNKNOWN。
正常控制保留:已知 audit-v1 外层、无 schema 历史包裹、legacy 未包裹 score-v1。
测试证据:RED 6 failed + 2 supported controls passed;GREEN 8 passed;当前文件 86 项全过。
我逐行确认:未知外层先于 payload 解析被拒;row.get 的默认值只对缺失字段放行,不会把显式 None/0 当默认;as_of/input_hash 外层冲突另有拒收。✅
P2-2:过深 JSON 的 RecursionError 曾逃逸为非结构化异常
修正位置:scheduled_broker_publication.py:59(只读边界的异常集合加入 RecursionError)。

receipt 的未使用字段、历史 audit 行含超过解释器递归深度的数组时,json.loads 抛 RecursionError;现在转成默认 UNKNOWN,不提高递归限制、不跳过坏行、不猜唯一 run、不改文件。
不捕获 MemoryError/SystemExit;不宣称文件大小/内存耗尽/同用户资源安全。
测试证据:RED 2 failed(RecursionError);GREEN 2 passed;断言原文件字节不变。
我确认 _object 对所有 receipt/audit/journal 解析生效;深 JSON 在 receipt 与历史 audit 行两条路径都返回 UNKNOWN。✅
适配器其余契约(重点复核)
选择:只读固定 run_receipt.json 与 audit_log.jsonl;receipt 必须 finished scheduled OK/FAILED、ok 对应、时区感知、北京时间 acceptance_date;唯一 scheduled audit、同 as_of/窗口/身份;重复/损坏/多行/未知 envelope 一律 UNKNOWN,不跳过猜唯一。
模式:v1/OFF 且无 capture 标记 → INFO/NOT_APPLICABLE/CAPTURE_DISABLED,不读 journal、不调 5g;v2 无 observation → UNKNOWN/ANCHOR_UNAVAILABLE,不自算摘要;v2 observation 无效 → UNKNOWN/ANCHOR_INVALID;有效 observation → 用原 journal_sha256 调未改 5g,状态原样传递。
身份:observation 9 字段精确、schema/protocol、32/64 小写 hex、as_of/run/capture/decision/input/committed_at 与 receipt/audit/journal 元数据匹配;started <= committed < finished+1s;same as_of 同 decision 但不同 run 不能借旧 receipt;journal 改动不能现场重锚。
信任:anchor_source=LOCAL_PRODUCER_RECEIPT;不是签名;5g 返回 UNKNOWN 仍 UNKNOWN;official_receipt_status 独立保留,辅助 OK 不覆盖 FAILED 正式 receipt。
只读:checked_path 拒 symlink/目录/FIFO;重复键拒收;无 socket/sqlite/写文件;测试对比字节、mtime、mode 不变。✅
三、独立执行结果
检查	我的结果	作者记录
新文件	86 passed / 12.09s	86 / 10.35s
六文件关联(作者分组)	作者日志 243;我用其自然七文件分组得 247	243 / 83.69s
全套	2142 passed / 1525.79s	2142 / 1420.48s
Governance	8/8 OK,ibkr_readonly=true	8/8
新两文件 Ruff / 全仓 severe	PASS / PASS	PASS
15 文件 mypy	Success: no issues found in 15 source files	PASS
compile / pip check / diff check	PASS	PASS
四日期 OFF strict	baseline 377/570da621…,candidate 377/24f37156…,seed 57/8557342f…;all_equal,4/4 空	同
比较器	19540147…,未改	同
评分指纹	ac025f0f…(基线/候选相同)	同
外部故障演练	13/13 各自预期,顶层 PASS,network 0,live 未触	同
说明:作者的 focused-tests.log 只留 243 passed 摘要,verification-runs.json 未记录该六文件命令;我用其自然分组(adapter 86 + 5h-A 两文件 40 + 5g 70 + anchor 7 + transaction_v2_acceptance 19 + run_receipt_writer 25 = 247)得到 247 通过。86 与 2142 均精确复现;243 的精确成员无法从包内独立重建,见 P3-1。

四、P0 → P3 Findings
P0:无。P1:无。

P2-1(A1 门槛,非本片缺陷)候选指纹 ac025f0f… 仍需 A1 发布/迁移/旧 writer 回滚证明
位置:scoring-fingerprint.json;decision_identity.py 未改(0765fe3c…)。
触发:把 2142/四日期 OFF strict 当作 A1 发布等价证明。
影响:候选指纹 ac025f0f… 与 live c1f4b8f/42d207d6… 不同;11-04 自然 3/3 属于 live v1,不能作为候选 v2 的 ON 样本;scheduled certification 字节、迁移、旧 writer 回滚仍未证明。
证据:OBSERVATION.md、5h-A/5h-B 交接;指纹三 scopes 分列。
处置:A1 门槛保留,另做发布/迁移/回滚证明;不得加等价豁免。
P2-2(信任边界,已披露)本机 producer receipt 不是签名
位置:适配器 anchor_source=LOCAL_PRODUCER_RECEIPT;契约第 3 节。
触发:同用户同时改 journal + receipt/audit,或敌对进程/OS。
影响:B 版选择/匹配只能证明“本机官方调度与 receipt 存储按现有纪律可信”;不能防同用户篡改,不能替代外部固定摘要/签名。
证据:5h-A 交接第 3 节;适配器注释;测试只证明本地链路。
处置:接线时标注来源;未来如需更强威胁模型,另设外部锚/WORM,不靠再包 JSON。
P2-3(静态债,已声明)扩大 15 条 mypy / 19 条 Ruff 未清零
位置:pipeline.py、run_daily_package.py(既有);新模块/test 自身通过。
触发:把“15 文件 mypy PASS”读成所有修改文件全净。
影响:既有类型/Ruff 债仍在;本片未新增 ignore/exclude,也未清零。
证据:static-gates.json 的 global_mypy_clean=false、full_production_ruff_clean=false;unchanged_expanded_debt: 5h-A has 15 mypy/19 Ruff。
处置:保持分列;清零另开片。
P3-1(证据精度)focused 243 的精确六文件命令未记录
verification-runs.json 只有 new-tests/governance/static/full/strict 等,focused-tests.log 仅摘要 243;我用自然七文件分组得 247。
影响:243 这一子集不能从包内逐项复算;但 86 新文件与 2142 全套精确复现,全集的证明力更强。
处置:后续在 verification-runs.json 记录 focused 的完整命令/文件列表;当前不把 243 当作唯一可复算门禁。
P3-2(标签修正)首次 strict 报告的人工显示标签
首次 equivalence.json 的人类可读标签继承了旧 A 阶段文字;实际 baseline/candidate 源/种子绑定从一开始就是旧 B 的 377/570da621… 与修正候选 377/24f37156…。
后续 equivalence-final.json 以正确 B→修正标签单独重跑;两报告源/种子/4/4 全等一致;label-correction.json 记录,未手改旧 JSON。
处置:引用 equivalence-final.json;保留初次输出作审计轨迹。P3。
P3-3(资源边界)深 JSON 只闭合 RecursionError
修正把 RecursionError 转 UNKNOWN;不处理 MemoryError、超大文件或同用户资源耗尽;交接已声明不是资源安全保证。P3。
P3-4(调用责任)辅助 status=OK 可与 official_receipt_status=FAILED 并存
适配器保留两个字段;辅助声明不覆盖主链 FAIL。未来接线必须同时读 official_receipt_status,不能只看 status。测试 test_publication_observation_cannot_rewrite_a_failed_official_receipt 已固定。P3(接口使用责任)。
P3-5(时间语义)秒精度窗口不是单调时钟证明
started <= committed < finished+1s 只做保守边界;时钟回拨/前跳可能误拒或放宽;交接已声明。P3。
P3-6(旧 B 审计覆盖)旧 B 本身未独立外审
本片外审覆盖“B + 修正”当前字节;旧 B 24 件证据保持原样,只证明修正前字节;5h-A 的 PASS 不自动覆盖 B。P3(已披露)。
五、未证明事项与边界
A1:ac025f0f… 的发布/迁移/旧 writer 回滚;scheduled certification 字节等价;CI 20 分钟预算未实测(本地约 24 分钟)。
晨验/WebUI 接线、I/O 频率、自然 ON/v2 样本;11-04 live c1f4b8f 的 3/3 与五日目标不属于候选。
完整自动 T1→T2、hermetic 环境、更广故障/耐久性、断电/磁盘耐久。
生产调用方仍为零;adapter 仅测试调用;无 CLI/config/flag/调度启用;无补发器/锁/DB/新目录。
六、三个独立判定
正确性:PASS。 两项内部 P2(未知外层 schema、深 JSON RecursionError)均已复现、修正并由 RED/GREEN 与 86 项测试固定;选择/模式/身份/锚点传递/只读边界/失败语义均通过独立复跑与逐行审阅;未发现 P0/P1。
提交/推送:允许精确范围。 scheduled_broker_publication.py + test_scheduled_broker_publication.py + 新证据目录 3c5h_offline_adapter_review_fix/ + 本修正交接;旧 B 24 件、旧 A 13/22、三份九月计划、主目录其他 A2 片、live 均不得混入;不得 git add -A;提交后检查新 CI。不是整棵 dirty tree 的总批准。
部署 / A2 闭合:不具备。 需 A1 发布/迁移/回滚证明、晨验/WebUI 接线、自然 ON 样本、CI 预算实测、用户明确授权、无 writer/避开 07:00–07:20/保留 live config 的 R6 条件。live 仍 c1f4b8f;A2 仍 OPEN;Phase B 未启动。DEPLOY HOLD;A2 OPEN;Phase B not started。
(本轮只读仓库/证据/live 11-04 报告;所有测试/比较器/演练在 /tmp/hermes-a2-5h-audit/ 独立 venv 与临时 baseline/seed 执行;未对仓库执行 add/commit/push/deploy,未运行 official daily、morning_acceptance 主程序、行情刷新或 IBKR。)