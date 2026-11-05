# A2 3C-5h-C：晨验只读接线合同与实施计划

日期：2026-11-04，Asia/Shanghai。基线 HEAD `8d16ad8ba639341a38ca5c29e278d12b81bb8efe`，实际增量基线是已审的当前累积候选，不是 HEAD 导出的旧实现。

**当前交付仅为现状核对、隔离导入可行性探针与后续计划。没有晨验接线实现，没有新增源测试或生产安装。DEPLOY HOLD；A2 OPEN；Phase B 未启动。** B 与两项修正的批准见 `2026-11-04_a2_3c5h_b_external_audit_{report,followup}.md`；不把它借给未来 C 的新字节。

## 1. 目标与非目标

目标：在原晨验的 `operational_observations` 增加一次、只读、绑定本次正式运行的辅助发布观察；让缺证据保持 UNKNOWN，让明确 OFF 保持不适用，不改原有七项主检查及运行/策略/认证判定。

不做：WebUI、轮询、自动补发、锁/恢复/DB 连接、新锚点服务、捕获开关、行情/外部源/IBKR 刷新、改 CI、安装系统脚本或 LaunchAgent、部署。也不借此处理 15 条类型债/19 条 Ruff、A1 迁移或其他 A2 子项目。

## 2. 已核对的工程约束

| 现有位置 | 事实及接线含义 |
|---|---|
| ops/morning_acceptance.py:125 collect_acceptance | 先收七项 checks，再收独立 observations；应复用此结构，不增加第八项主检查。 |
| :190 总体判定、:236 readiness、:630 certification | 主失败来自既有 checks，认证另有发布/自然运行规则；不能用辅助 OK 清除原 FAIL/PENDING。 |
| :49 render_markdown | 观察栏只渲染 status/detail/evidence；只加嵌套 JSON 字段会在 Markdown 丢失主/辅助状态区别。 |
| :760 _collect_operational_observations | 已有 retention/admission/migrations，各自语义保留；WARN 可进 summary，不必另造汇总框架。 |
| :491 _verify_transaction_v2 | 已用 importlib 按已部署源路径加载标准库 validator，不能从此推定普通 import 一定可用。 |
| 系统任务 com.hermes.morning-acceptance | 只读 plist 确认用 /usr/bin/python3 -B 运行独立 libexec 脚本，09:10；与仓库脚本不是同一安装位置。 |

仓库 morning_acceptance.py 仍为 `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d`。本机系统 Python 为 3.9.6；开发 venv 为另一解释器。不能新增顶层 `from hermes_escape_top...` 后仅在开发 pytest 下通过就认为系统任务可运行。仓库文件修改也不等于已更新 libexec 安装件。

## 3. 固定输入与加载合同

### 3.1 从本次发布加载，不从开发目录兜底

- 复用 `_collect_release` 确认的 release.name，以 `base/releases/<name>/hermes_escape_top` 固定本次物理源码根，不在加载三个模块之间反复解析 current。
- release_identity 不可确认、目录越界/缺失、源码路径被换成链接/非普通文件或 current 在本轮切换时，本项 UNKNOWN；不改原主失败，不猜旧发布或开发目录。
- 数据根允许 R6 既有合法 data 共享链接，但须在本次收集固定其解析结果；源码模块不允许借链接跳向另一套代码。不能把拒绝源码重定向写成禁止 R6 共享数据根。
- 只有三个已审模块参与读取：core/data/transaction_evidence.py、core/reporting/broker_publication_status.py、core/reporting/scheduled_broker_publication.py。当前 SHA 分别为 b6cfe162...、fbe8c134...、e33a71b5...；完整值见 B source-binding。
- 沿用 importlib，在独立私有包命名空间按上述顺序加载，保留相对导入；不改 sys.path，不导入 pipeline/adapters/broker 或执行项目 __init__，不复用全局已缓存的另一发布模块。调用结束后移除本次命名空间；重复调用/异常后同样清理。
- 不硬编码这三个当前 SHA 为永久允许版本，也不把普通本机源码摘要当签名；模块属于已经确认的本次发布。源码根/模块装载失败应 UNKNOWN / READER_UNAVAILABLE，绝不转去仓库、site-packages 或旧发布找“能成功”的版本。

后续实现优先在现有 ops 脚本增加小的私有装载/观察 helper，不复制 B 或 5g 的判定逻辑，不另建 Python 服务/目录/配置开关。无需为两个不同运行环境新增插件框架。

### 3.2 正式运行与并发边界

- 每次 collect 只调用 B 一次，参数是固定 archive 与本次 Asia/Shanghai acceptance_date，不传任意 run/journal 路径；B 继续独立唯一选择正式 receipt/audit，不复用主验收较宽解析的结果来绕过 B。
- 在主 receipt/audit 读取前及辅助读取后，对固定 receipt/audit 的原始字节做摘要核对；保留读取/解析失败，期间覆盖、增删、替换或发布切换使辅助观察 UNKNOWN / EVIDENCE_CHANGED，不重试选另一个 run。
- 这里的摘要只证明本轮输入未观察到变化，**不能替代 COMMITTED journal 的 producer 原摘要**。绝不把当前 journal 自算值交给 5g 重锚。
- 当 B 返回 run_id/capture_id 且主 audit 有对应值时必须精确一致；不一致为 UNKNOWN。主链失败仍可保留 B 自己核实的辅助声明，但不得用其替换原失败内容。
- 不持 pipeline lease、不恢复/清除 active、不修 receipt。读取前后相同不构成对抗并发 ABA、敌对进程或同用户篡改的安全证明，串行运行纪律与本机信任限制仍在。

## 4. JSON、Markdown 与状态合同

拟新增唯一键：`operational_observations.broker_cache_publication`。使用现有晨验 schema 的可选扩展，不加入 RUNTIME_INTEGRITY_CHECKS / STRATEGY_DECISION_CHECKS。

保留 B 的所有观察字段，包括原 status、publication_status、reason、anchor_source、official_receipt_status、scope、strategy_blocking、cache_contents_verified，以及实际存在的身份/摘要字段；不把缺失 run_id、官方状态或信任来源补成成功。额外补足现有表格需要的 detail/evidence，记录实际读取发布，不能使用 mtime 作为身份或来源证明。

| B/加载结果 | 观察栏 | 对原主结论的影响 |
|---|---|---|
| 明确 v1/OFF，无混合 capture 标记 | INFO / NOT_APPLICABLE / CAPTURE_DISABLED | 无；不是“缓存已发布”。 |
| v2 缺原 commit observation | UNKNOWN / ANCHOR_UNAVAILABLE | 无；不是发布失败，也不是成功或 OFF。 |
| 错身份/未知协议/无唯一正式 run/证据损坏 | B 的 UNKNOWN，保留 reason | 无；不择有利结果或借旧 run。 |
| 无可加载 reader/本轮发布或输入改变 | UNKNOWN，明确装载/一致性原因 | 无；不修改既有 checks 的失败证据。 |
| 5g 经 B 返回 OK/WARN/INFO/UNKNOWN | 原值与 publication_status 原样保留 | 无；OK 只是匹配本机声明，不证明当前缓存/新鲜度/IBKR 可用。 |
| auxiliary OK + official_receipt_status FAILED | 同时显示两者 | 主 scheduled_receipt 继续 FAIL，总体继续 FAIL。 |

Markdown 的 detail 至少明确辅助 status/publication_status/reason、official_receipt_status、anchor_source（未知写 UNKNOWN），不能只显示一个 OK。沿用 _markdown_cell 的转义，不增加账户/持仓/原始 broker tape/错误堆栈或读取当前缓存内容。

WARN 与 UNKNOWN 应可见，并通过现有 operational_warnings 在 summary 中明确标注“broker publication: WARN/UNKNOWN”；UNKNOWN 不描述成 verified failure。INFO/OFF 不加警报；OK 不增加“系统修复/已认证”文案。summary 可以扩展，但原 status/readiness/post_deploy_certification、checks、正式错误详情及 CLI 0/2/3 语义不因辅助结果改变。

## 5. I/O 与发布纪律

仅每次显式晨验收集一次：既有主检查仍运行，B 对 v2 会再查完整输入清单；前后 receipt/audit 摘要也有额外线性读取。当前不声称零 I/O、去重成功或固定毫秒上限，不通过跳过 validator/只比 input_hash 来加速。

实施验证须分别记录代表性 v1/v2 fixture 的 audit 字节数、证据文件数、耗时和调用次数，对照未接线版本；如代表性工作量不合适先停在离线候选，不先上轮询或缓存“最近成功”。跨进程/掉电耐久性不属于本片。

未来上线涉及两个独立工件：R6 发布的 reader 源码与 libexec 晨验脚本。部署 A2 代码、更新系统脚本、启用 capture 各自需要明确批准与原发布门槛；不可因本片计划合并执行。reader 尚缺失的旧发布应报告 READER_UNAVAILABLE，不能通过更改系统 Python、调度时间或默认开关解决。当前主任务/09:10/09:15转述保持不动。

## 6. 逐项实现与验证

### C1：离线集成候选，逐个 RED/GREEN

- 计划修改：ops/morning_acceptance.py；新增 src/hermes_escape_top/tests/test_morning_publication_observation.py，复用原 morning fixture 和已审 B/5g fixture。原七项测试保持，不反向修改旧期望来制造通过。
- 先验证装载：系统 Python -I -S -B 可用；仅指定 release 的三模块，禁用/恶意项目 __init__ 不执行；开发路径和预载同名模块不能替代；连续不同 release、不存在/链接/目录模块、异常清理均有覆盖。
- 再验证结果：真实 B 的 v1/OFF、v2缺锚、v2匹配与回执部分/失败/缺失、unknown schema/深 JSON；七个主检查原样，原主 FAIL/PENDING 不被辅助 OK 升级。可用 stub 覆盖状态组合，但至少一个真实 producer→receipt→B→晨验的 tmp 集成链，标清 fixture 合成边界。
- 绑定反证：同 as_of 不同 run、借旧摘要、receipt/audit 在收集中覆盖、发布切换均 UNKNOWN；不通过主 reader 的旧解析或 B 的现场摘要兜底。
- 输出：JSON 与 Markdown 同时保留 UNKNOWN、official FAILED 与辅助 OK、本机非签名来源；四个报告文件只写 tmp。对 reader 加 socket/SQLite/写调用禁令，并检查原输入字节/mtime/mode 不变；不要把报告写入本身描述成无写入。
- 精确命令记录：验证执行器必须登记每条完整 argv、所有测试文件、解释器/源摘要、退出码、耗时、日志；pytest 失败不能被总结行覆盖。不得再用“243”这类无法重建的子集摘要代替命令。

### C2：候选冻结与独立外审

- 绑定 C1 开始前完整源码快照及本片 patch；不以 HEAD 代替已审 A/B 前置。新证据另存，不覆盖 A、旧 B、review_fix 包。
- 聚焦：完整原 test_morning_acceptance.py、test_transaction_v2_acceptance.py、B 测试与 C 新测试，明确四文件列表；必要依赖组另列，不能临时改变数量口径。
- 变更 ops 运行字节后，跑全套、治理、相应 Ruff/类型/编译/依赖门禁与四日期 OFF strict；扩大静态债单列。全套/CI 时长实测，不因 20 分钟预算擅自豁免测试。不得把此门禁当作 A1 迁移/自然 ON 证明。
- 外审只批准 C 的新字节及指定前置交互；Git、系统脚本安装、R6 与自然观察仍分开。**本计划不授权自动 commit/push/deploy，也不宣告 A2 闭合。**

## 7. 本轮已做与未做

只读核对源码、现有测试、ops说明与实际 LaunchAgent plist；未执行主晨验或读取今天报告来制造新验收结论。系统解释器隔离探针实际执行：

`/usr/bin/python3 -I -S -B '/Users/liweishi/Documents/New project/hermes-a2-morning-wiring-contract-2026-11-04/import_probe.py'`

退出0，Python 3.9.6；三个现有模块可在私有命名空间装载，sys.path不变、未导入项目正常包/pandas/numpy/ib_insync，命名空间清理完成，三源码摘要前后相同。探针脚本SHA为 `957b6e94ca226c192a59f1798bd28673f20cdb79ca7f7fdf60c17dc6bcda8183`，完整命令/输出记录在同目录 import-probe-result.json。

**该探针没有调用 reader、没有跑 collect_acceptance、没有模拟完整 release 装载拒收或实现 C1；只证明标准库装载机制可行，不是新生产 loader 已通过验证。** 本轮不新增 pytest、不重跑未变代码的2142全套/strict/治理，不冒称这些旧结果覆盖尚未实现的 C。旧源/测试/冻结包保持，只有本文与总计划追加；未 stage/commit/push/deploy，未触 live/刷新/IBKR/任务配置。下一可执行项是 C1 的装载失败/主辅助分层测试先 RED，再做最小离线接线候选。**DEPLOY HOLD；A2 OPEN；Phase B not started。**

## 8. 2026-11-04 后续候选实施

C1 的仓库离线接线候选现已实现，范围仅ops脚本与一个新测试文件，详见 `2026-11-04_a2_3c5h_c_morning_wiring_handoff.md`。前文“尚未实现”与仅导入探针的结论保留为合同成文时点，不冒充当前实现证据。新37项及明确四文件182项通过，系统Python实际tmp收集、真实producer/原摘要转交、主辅助状态分离与读取期变化反证已执行；最终全套与封存状态以交接第8节为准，不用旧2142代替新测试结果。

合同语义未扩大：B/5g与producer未改，原七检查/认证/退出语义保留；前后receipt/audit摘要只做一致性，不替换原journal锚。加载失败或本轮变化为非阻断UNKNOWN，无新开关/调度/安装/刷新或补发。额外复现ops单文件4条既有mypy告警，修正前后消息一致；15模块门禁通过不是全文件类型清零。当前仍为独立外审待审、DEPLOY HOLD、A2 OPEN、Phase B未启动。
