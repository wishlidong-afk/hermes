成。我按第 5 节的 12 问逐条执行:8 项声明 SHA 全核、逐行审消费者与演练器、独立重跑正向与负向演练、独立重做四日期 strict、全套与静态门禁,并额外做了一次跨进程的规范化快照诊断。

外审结论
本批正确性:通过。 恢复消费者与演练器未发现可利用缺陷;正向/负向演练我独立重跑后与冻结证据结构逐项一致。
允许提交/推送:可以,但请把"本批是 ca7dda9 之后的新实现范围、需单独审查"写进提交说明(你第 9 行已这样表述,照用)。
部署 / A2 闭合:不具备。DEPLOY HOLD;A2 OPEN;Phase B not started。
1. 范围与字节绑定
✅ HEAD 现为 ca7dda9 feat: freeze jointly audited A2 recovery candidate;git diff HEAD 为空。我核对了提交内容:11 个受跟踪实现文件的 blob 哈希与我上一轮联合外审的 19 项逐个相同,说明联合外审批准的对象确实被冻结进了这个 commit,而没有夹带改写。

✅ 工作区仅本批 6 条未跟踪路径(4 源码/脚本 + 3 证据 + 本文,其中证据目录含 3 个 JSON);三份九月文档在清单外、未改动。

✅ 8 项声明 SHA 全部命中:transaction_restore.py a8f466ee…(110 行)、verify_a2_isolated_replay.py 2fe12046…(352 行)、两个测试 354e346f…/dbcf2d89…、三个 JSON fbe47776…/9a8c059f…/57a4d8b4…、比较器 19540147…(未改)。

2. 消费者契约(第 1–5 问)
边界	我的核对结果
外部锚先行	✅ 先 checked_path 取 journal → 先比外部传入的 journal SHA → 才解析;自算摘要不参与真实性判定,文档第 39 行如实说明
COMMITTED/v2/run/binding	✅ schema_version==v2 + status==COMMITTED + run_id 一致;v1/pending/ROLLED_BACK/错 run 四种在测试里都被拒绝且不建目标;decision_id/input_hash 必须与 input binding 相等
不弱化协议	✅ 直接复用 validate_inventory(精确七业务)与 validate_input_evidence(manifest 摘要、逐文件摘要、无未登记文件)
描述符精确性	✅ pre_state.json 顶层字段集合必须恰为 4 个键,schema/capture_mode/binding 精确比对,set(state["artifacts"]) == business
前像对齐	✅ 逐文件对齐 journal 的 existed/snapshot_format/before_mode/before_sha256;before_mode 用 type(mode) is not int 排除 bool;PRESENT 路径必须是该 capture 下精确的 pre_state/archive/<name> 且已登记
登记集合 = PRESENT 集合	✅ 第 89–91 行强制 registered == {prefix+pre_state/+verified};额外、未登记、缺失都拒绝
ABSENT	✅ 规范形态、不建空文件;全 ABSENT 情形有专测;文档明说"不证明首次安装"
✅ WAL 未被打折:恢复 SQLite 时以 mode=ro&immutable=1 读冻结 backup并跑完整逻辑状态校验;有专测验证"已提交 WAL 行出现在恢复结果",且恢复产物里没有 -wal sidecar。不是把 live main 当 immutable 漏读 WAL。

✅ 输出与副作用:目标必须为新目录(已有/悬空链接/位于 source data·history·legacy 内全部拒绝),布局 archive/*0600 + source_transaction.json 0400 + restoration.json 0400、根 0700,与文档一致;发布失败清 staging 且 source 逐文件字节不变(有专测)。

✅ 诚实边界:明文承认"不是签名/同用户边界""业务内容先整读入内存""依赖 Hermes 包,不是 /usr/bin/python3 标准库可独立消费""不是任意脱离原 store 的 bundle 导入器"——与实现一致。

3. 真实管道演练(第 6–9 问)
✅ 三个 worker 确为独立子进程:_child 用 subprocess.run([sys.executable, … --worker …]),冻结证据里三个 PID 各异,我重跑也是三个不同 PID。

✅ 前态真实非空:_nonempty_state 逐库 COUNT(*),证据 nonempty_pre_state=true;演练自检把它纳入 PASS 条件。

✅ mock 范围正确:只截 socket.connect/connect_ex/create_connection(计数并 fail-loud)、pipeline.build_soft_data、ibkr.positions.read_positions、ibkr.executions.read_executions、pipeline.datetime;评分、路由、reentry、持久化函数均未 mock,比较器未改。

✅ 字典顺序修复是真的:tape 用 sort_keys=False 写出、copy.deepcopy 读取;文档第 108 行说明的顺序敏感性在代码里可见,且没有靠忽略字段绕过。

✅ 负向对照是真的、且我独立复现:我重跑 --probe-net-liq-change,结果与冻结的 negative_replay.json 在 status=FAIL、strict_differences=['payload','artifact:audit_log.jsonl','artifact:hermes_state.sqlite']、30 条差异路径集合完全相同、input_hash_equal=true、reader_calls={soft:1,positions:1,executions:1}、network_attempts=0、source_unchanged=true 上逐项一致。这证明"市场 input_hash 相同也能因 broker 净值差异被抓出",比较不是靠 input_hash 走捷径。

✅ 正向演练我独立重跑:status=PASS、artifacts_compared=7、strict_differences=[]、input_hash_equal=true、三端口各一次、network_attempts=0、source_unchanged=true、replay_transaction_status=COMMITTED、execution_sync_status=NO_MATCH、源指纹 358 文件。

✅ fixture 边界与 NO_MATCH 都未被夸大:证据与文档都写明 production_capture=false、ISOLATED_MECHANISM_REHEARSAL_NOT_PRODUCTION_CAPTURE、v2 producer 是 fixture、历史输入仍是 RETROSPECTIVE_AS_OF_MATCH;NO_MATCH 明确未冒充 successful auto-confirm 分支证明。

4. 门禁与四日期(第 11 问)
检查	我实测
新增恢复/演练测试	32 / 6
focused 八文件	205 passed,31.73s
全套	1748 passed,192.13s
Governance	8/8 OK,ibkr_readonly=true
Ruff(新 4 文件 + 全仓 E9/F63/F7/F82)	全部 PASS
mypy(新模块/脚本 + CI 四模块,6 files)	零 issue,无新增 ignore
compileall / pip check / diff --check	全 PASS
指纹	仍 03b94995fba06e849eef7468d1ba3e9f67bd8038296dfd8cf0e47a694533ad73
✅ 四日期 strict 我独立重做(基线 git archive ca7dda9):all_equal=true,4/4 strict_differences=[];基线 353/be475704…、候选 356/d9137193…、seed 77/c119ae18… 与冻结 JSON 逐字一致,三个清单我都用同款 canonicalization 重算 MATCH,四个 input_hash 与文档第 159–162 行一致。比较器未改、无新增忽略项。候选 356 − 基线 353 = 本批 3 个新源文件,数字自洽;演练报告另登记的 358 文件(含脚本与 requirements.lock)与比较器的 src/hermes_escape_top 口径不同,文档第 164 行已明说,没有混称。

5. 发现
F1(中,建议提交前在交接里补一句)——两个规范化摘要跨机器不可复现,但它们被当成了可引用锚点。 replay.json 把 normalized_reference_sha256 / normalized_replay_sha256 记为 c8ba2bf7…,并要求外审"核本次冻结报告与登记 SHA"。我实测:在同一工作区、同一解释器下重复运行结果稳定(两次都得到 0d837361…),但对作者冻结值 不一致;我另外验证该快照里没有任何绝对路径残留(/Users/...、/private/tmp、hermes-a2-isolated-replay 出现次数均为 0),所以不是路径归一漏洞,而是环境相关的非易变字段进了快照。同一轮里 reference 与 replay 的摘要仍然相等、差异路径集合与作者完全一致,所以这是"绝对锚点不可复现",不是"等价性不可复现"。建议:要么把这两个字段在交接里降级为"仅本机/本轮记录、不作跨环境核对项",要么在归一化里补齐那个环境相关字段。这不影响 PASS 判定,但会影响别人按第 137 行去核对它们。

F2(低,记录)——演练读取的是当前 HERMES_DATA_DIR,不是冻结 seed 清单。 rehearse() 用 Path(os.environ.get("HERMES_DATA_DIR", str(PACKAGE)))/"data" 作为只读 seed,所以在这台机器上,如果 shell 里恰好有 HERMES_DATA_DIR 指向 live shared runtime,演练会把 live 的 history/soft_history 只读复制进临时根(读完即删,不写 live)。同时这也意味着独立重跑的输入未必等同于作者那份 77 文件 seed。建议:在文档或脚本里显式要求/回显所用 seed 的指纹(报告里已有 input_manifest_sha256,但 seed 指纹未登记),避免"在不同输入上跑出相同结构"这种无法区分的情形。

F3(很低)——两处 KeyError 而非 ValueError 的畸形清单路径。 rows[relative] 与 state["artifacts"][relative] 在键缺失时抛 KeyError。正常流程不可达(validate_inventory 已强制 role/路径/精确集合),测试也只断言 ValueError;属 fail-closed 的错误类型不够干净,不必为此改代码,若日后加固可顺手统一成 ValueError。

6. 残余边界(我确认仍存在,不因本批全绿消失)
真实生产入口的 v2 事务提前声明与读取端口绑定、真实 source/runtime/依赖归档、真实 COMMITTED 外部锚进入运行与 retention 链、多状态/多日期/successful auto-confirm 分支重放、A1 新指纹发布迁移证明与 R6、自然观察 —— 均未完成。本批只是离线消费者 + 隔离机制演练;NO_MATCH 是本次唯一被走到的 execution_sync 分支。文档第 264–272 行与 DEPLOY HOLD / A2 OPEN / Phase B not started 的判定我支持。

(复核产物:/tmp/review-replay-pos.json、/tmp/review-replay-neg.json、/tmp/review-norm-probe*.py、/tmp/review-b6-equivalence.json、/tmp/review-b6-baseline;未改动仓库任何文件。)