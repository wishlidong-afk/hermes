已完成，用时 25分12秒
A2 3C-5h-C 晨验只读接线外审报告
结论:C 片及其与 B/5g/producer 的指定前置交互正确性 PASS;允许按精确增量提交/推送;系统脚本安装、R6 部署与 A2 闭合不具备。未发现 P0/P1;P2/P3 为已声明的 A1、信任边界、静态债、证据范围与证据精度。

仓库:/Users/liweishi/Documents/github/hermes,HEAD 8d16ad8ba639341a38ca5c29e278d12b81bb8efe,未提交。
C 增量:ops/morning_acceptance.py(217857aa…,1484 行,仅 105 行新增)+ tests/test_morning_publication_observation.py(e42644e8…,329 行,37 用例)。
我未修改仓库/live/证据;未 stage/commit/push/install/deploy;未运行正式 daily/晨验、行情/外部刷新或 IBKR;测试在 /tmp/hermes-a2-5h-audit/ 独立 venv 与重建的临时 baseline 执行。
一、绑定与基线重建(独立复算)
项目	结果
C 两文件 SHA / 行数	217857aa… 1484 / e42644e8… 329 ✅
C 证据清单	SHA256SUMS.json = a74e9de9…,51 件逐项匹配 ✅
C source-binding.json	2 实现 + 23 依赖,全部匹配 ✅
before/ops/morning_acceptance.py	985c617d… ✅
slice.patch	99e256f2…,可干净应用到 ops 与新测试 ✅
旧 A / 旧 B / review_fix	22 / 24 / 33 件证据原样匹配 ✅
范围	起始 1294 件,1291 件不变;变化为 ops + 两旧文档追加;新测试/交接/证据单列;无 Git/live 写 ✅
我按提示第 3 节原样执行了重建脚本(代码 SHA 含结尾 LF = 1c38a1f9ba642d633701410d8b7fa8ce534db3fb13030c532f2ce23c2e3e721d,先校验脚本 SHA 再运行),输出:

baseline 377 / 24f37156178f8e5953e2534f7502b21af8a7a588cd8bc3c9fd1da5eda5356806;
seed 57 / 8557342fc9b34ecab5670c0770bfc6d92edcf1cff0ae6cdbf356097c86caeb11;
ops_before_sha256=985c617d…;reconstructed_without_authors_old_snapshot=true。
这说明基线确为 B + P2 修正的已审 377,不是 HEAD 旧树,也不是旧 A 375;没有借用作者私有旧快照。

四日期 OFF strict(用上述新 baseline/seed、当前候选、审计解释器):

baseline 377 / 24f37156…,candidate 378 / 3389d65d11028a58590a34a8…,seed 57 / 8557342f…;
all_equal=true,4/4 strict_differences=[],四日期两侧 input_hash 与冻结报告一致;
比较器 19540147… 原字节,无新增忽略项;
差集:仅新增 C 测试;ops/morning_acceptance.py 不在 src manifest,由 C source-binding/before/patch 单独绑定——这点与交接一致,不能把 strict 报告当 ops 背书。
二、C 实现审阅(重点)
A. 主/辅助分离与状态矩阵
collect_acceptance 在第 140 行先取 publication_snapshot,再走原 release/receipt/audit/health;第 180–190 行调用 _collect_broker_publication,写入 operational_observations["broker_cache_publication"],不新增第八 check,不改 checks/readiness/post_deploy_certification/status(第 202–224 行只读地参与 warning/summary)。
主 FAIL:summary 追加 broker publication: WARN/UNKNOWN;辅助 OK 不追加,但 observation 中 official_receipt_status 保留 FAILED,正式 FAILED 与辅助 OK 同时可见。
主 PASS/PENDING:warning_details 已含 operational_warnings,summary 显示 WARN/UNKNOWN;辅助 INFO/OFF 不新增警报。
12 组测试(3 主 × 4 辅助)逐一断言 status/checks/readiness/post_deploy_certification 与无污染基线相同,且行状态/正式状态/摘要/Markdown 正确。✅
原 CLI 0/2/3 语义未被 C 修改;observation 不改变主 status/退出码。
B. 三模块私有加载
_read_publication 用随机 _hermes_morning_reader_<uuid> 命名空间,创建 namespace/.core/.core.data/.core.reporting 合成包(__path__=[]),只加载选定物理发布的 transaction_evidence.py、broker_publication_status.py、scheduled_broker_publication.py。
不执行项目 __init__;不修改 sys.path;不借用开发/旧模块;exec(compile(source.read_bytes(), ...)) 直接编译选定源字节,不用旧 .pyc;finally 删除整个私有命名空间。
package/package.parent/package.parent.parent 任一 symlink、源文件缺失/目录/链接均拒收;release 名做 Path(name).name == name 与 ./.. 拒收。
系统 Python /usr/bin/python3 -I -S -B 实际版本 3.9.6(见 environment.json),测试在恶意 __init__.py 下收集成功,断言 sys.path 不变、无 hermes_escape_top/pandas/numpy/ib_insync 导入、私有模块清理。✅
C. 快照与 EVIDENCE_CHANGED
_publication_snapshot 在主 receipt/audit 读取前记录:base/current 解析、archive 解析、receipt/audit 的流式 SHA;缺失/非普通文件/链接/解析失败返回 None → EVIDENCE_UNAVAILABLE。
_collect_broker_publication 在 B 读取后再次快照,并核对 package.parent == snapshot[0]、receipt/audit 摘要、以及双方已有 run_id/capture_id;任一变化 → EVIDENCE_CHANGED,丢弃可能成功的辅助结果,不重试选另一 run。
测试覆盖 dashboard 读取期间改 receipt/audit/release,以及 reader 内部改 receipt/audit/run identity;均 UNKNOWN/EVIDENCE_CHANGED,不混入成功声明。✅
D. B/5g/producer 不被弱化
C 只调用未改 B 一次,由 B 自行唯一选择正式 run;不把主 reader 的较宽解析当替代;不读当前 broker 缓存;不连接 SQLite/网络;不持锁/恢复/补发。
原 journal SHA 由 B 从正式 receipt 转交;C 的 receipt/audit 摘要只做本轮一致性,不自算 journal 摘要重锚;B 的未知 schema/深 JSON 拒收继续生效。
B 的 OK/WARN/INFO/UNKNOWN、publication_status、reason、身份/摘要、anchor_source 原样保留;C 不改写成主验收 PASS。✅
E. JSON/Markdown 与原七检查
operational_observations.broker_cache_publication 的 detail 同时含 status/publication_status/reason/official_receipt_status/anchor_source;缺失写 UNKNOWN。
Markdown 既有 observation 表(第 70–93 行)按 detail 渲染;测试断言 official_receipt_status=…、anchor_source=LOCAL_PRODUCER_RECEIPT、| broker_cache_publication | {auxiliary} | 均出现;JSON 与报告对象逐字一致。
原 7 checks、readiness 两组、certification、status 与退出码不变。✅
三、独立执行结果
检查	我的结果	作者记录
37 新测试	37 passed / 7.03s	37 / 7.14s
明确四文件关联	182 passed / 16.46s	182 / 16.21s
全套	2179 passed / 1416.34s	2179 / 1421.17s
Governance	8/8 OK,ibkr_readonly=true	8/8
15 文件 mypy	Success: no issues found in 15 source files	PASS
ops 单文件 mypy	4 / 4,消息逐字相同(仅行号移动)	4/4
两文件 Ruff / 全仓 severe	PASS / PASS	PASS
compile / pip check / diff check	PASS	PASS
四日期 OFF strict	377/24f37156…,378/3389d65d…,57/8557342f…;all_equal,4/4 空	同
外部故障演练	13/13,顶层 PASS,network 0,live 未触	同
评分指纹	ac025f0f…(两侧相同)	同
系统 Python	3.9.6,-I -S -B,恶意 __init__ 未执行	同
重建脚本按提示原样执行,基线/种子/ops 旧摘要与预期完全一致;四日期在新建临时目录上独立跑出,未使用作者私有旧快照。

四、P0 → P3 Findings
P0:无。P1:无。

P2-1(A1 门槛,非 C 缺陷)候选指纹 ac025f0f… 仍需 A1 发布/迁移/旧 writer 回滚证明
C 只改 ops/test,指纹两侧仍 ac025f0f…;live 是 c1f4b8f/42d207d6…;11-04 自然 3/3 属 live v1,不是候选 v2 的 ON 样本。
四日期 OFF strict、2179 全套均不能替代 scheduled certification 字节等价、迁移或旧 writer 回滚。P2,保留门槛。
P2-2(信任边界,已披露)本机 producer receipt 不是签名
C 的 anchor_source=LOCAL_PRODUCER_RECEIPT;同用户同时改 journal + receipt/audit、敌对进程/OS 不在保证内;C 的 snapshot 只防本轮非并发变化,不防 ABA/同用户替换。
未来安装/接线必须保留该标注;更强威胁模型需外部锚/WORM,不能靠再包 JSON。P2。
P2-3(静态债,已声明)producer 15 mypy / 19 Ruff,ops 4 mypy 未清零
15 文件门禁 PASS;ops 修正前后各 4 条、逐字相同;global_mypy_clean=false、full_production_ruff_clean=false;无新增 ignore/exclude。
不能把 15 文件 PASS 写成所有修改文件类型清零;C 新测试不在 15 文件 mypy 成员内(仅 Ruff 覆盖)。P2/P3。
P2-4(证据范围,重要)ops/morning_acceptance.py 不在 src strict manifest 内
scripts/compare_pipeline_persistence.py 只盘点 src/hermes_escape_top;C 的 candidate 378 仅比 baseline 377 多一个新测试,ops 的 105 行修改不由 strict 报告覆盖。
C 的 ops 增量由 C source-binding/before/patch 与晨验集成/状态矩阵测试单独绑定;引用 strict 报告时不能声称它证明了 ops 行为。
证据:source-difference.json 的 ops_separately_bound;C 交接第 5 节明确警告。P2(证据范围,不是代码缺陷)。
P3-1(证据精度)内部 12 组 before/candidate 对照未留探针/日志
internal-review.json 自述 12 组直接对照通过,但 probe_saved=false、无保存摘要,仅在内部工具 transcript;19 项 narrow 有记录。
不能把 12 组当包内可独立复算门禁;37/182/2179 与 19 项才是可复算证据。P3。
P3-2(历史 RED/GREEN)初次失败与夹具修正
green-v1 初次 exit 1(v1 fixture audit/health hash 未同步),red-source-paths/io-profile 初次也因夹具失败;随后仅修 fixture 并保留原主检查,最终 37/182 通过。
交接已如实保存;不冒充生产缺陷或一次全绿。P3。
P3-3(异常吞没)_collect_broker_publication 的 except Exception: pass
读取/装载异常一律落到 READER_UNAVAILABLE/UNKNOWN,不泄露堆栈;但也不记录异常类型/位置,排障只能看 detail。
交接称非阻断 UNKNOWN;测试覆盖。P3(可观测性)。
P3-4(系统 Python 3.9.6 vs 运行时 3.11.15)
测试在 /usr/bin/python3 -I -S -B(3.9.6)下收集成功,证明三 reader 语法/依赖兼容;生产安装件运行时是 3.11.15,未在 3.9.6 下跑完整晨验/真实 producer。
environment.json 已记录;不把 3.9 reader 测试当 3.9 生产验证。P3。
P3-5(CI 预算)本地 23:36 vs CI 20 分钟
本地 2179/1416s;CI 未运行,不能据本地 PASS 声称云端绿;交接已分列。P3。
P3-6(旧依赖明示)review_fix 的 ops 依赖已被 C 有意改变
旧 B/review_fix source-binding 的 ops/morning_acceptance.py 摘要 985c617d… 不再匹配当前 217857aa…;C 交接第 1 节明示,旧 24/33/22 包未重写,其余 19 项仍匹配。P3(已披露)。
P3-7(性能诊断)io-profile 是本机夹具
v1 389B/0、最小 v2 401B/2、producer 341KB/256;C 交接明确不是线上延迟承诺/冷缓存/长 audit 增长;不据此优化或跳过 validator。P3。
五、未证明事项与边界
A1 候选 ac025f0f… 发布/迁移/旧 writer 回滚;候选级 CI;自然 ON/v2 样本;系统 libexec 安装件、LaunchAgent/调度、真实晨验;R6 部署。
完整自动 T1→T2、hermetic、断电/耐久性、同用户敌对/ABA、OS 网络沙箱。
3.9.6 下的完整晨验;真实 IBKR;真实 broker 缓存内容/新鲜度。
19 项内部定点与 37/182/2179 已复现;12 组内联对照仍只是补充证言。
六、三个独立判定
代码正确性:PASS。 C 的主/辅助分离、快照/复核、三模块隔离加载、B/5g/producer 不弱化、7 checks/readiness/certification/退出码不变、JSON/Markdown 保留未知与正式状态,均通过逐行审阅、37/182/2179 独立复跑、四日期 strict 与系统 Python 3.9.6 测试;未发现 P0/P1。
提交/推送:允许精确增量。 C 的 ops/morning_acceptance.py + test_morning_publication_observation.py + C 证据/交接/契约;A/B/review_fix 前置按各自片单独标注提交;旧 22/24/33 包、三份九月计划、主目录其他 A2、live、私有 capture 不得混入;不得 git add -A;不得用 src-only strict 给 ops 背书;提交后检查新 CI。
系统脚本安装 / R6 部署 / A2 闭合:不具备。 需 C 与 A/B 的明确提交、候选 CI、A1 发布/迁移/回滚、自然 ON/v2 样本、libexec 安装件与晨验接线、用户明确授权、无 writer/避开 07:00–07:20/保留 live config 的 R6 条件。DEPLOY HOLD;A2 OPEN;Phase B not started。
(本轮只读仓库/证据/live 11-04 报告;重建脚本按提示原样执行于 /tmp;所有测试/比较器/演练在 /tmp/hermes-a2-5h-audit/ 独立 venv 与临时 baseline/seed 执行;未对仓库执行 add/commit/push/install/deploy,未运行 official daily、晨验主程序、行情刷新或 IBKR。)






用量 8.2M tok
