# A2 3C-5h-C：晨验辅助发布观察接线候选

日期：2026-11-04，Asia/Shanghai。**仅仓库离线候选，尚未安装到系统任务、未启用 capture、未获得独立外审或部署授权。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

## 1. 范围、前置与增量

本片从 B + 两项 P2 修正的已审字节继续，不从 HEAD `8d16ad8ba639341a38ca5c29e278d12b81bb8efe` 重建未提交的前置。合同为 `2026-11-04_a2_3c5h_c_morning_wiring_contract.md`；B 外审接收为 `2026-11-04_a2_3c5h_b_external_audit_followup.md`。

| 本片源码 | 状态与最终 SHA-256 |
|---|---|
| ops/morning_acceptance.py | 修改，1484 行，217857aa94632ba89db62db630864b56d231e1bc27dd371f9db022187b4698b9 |
| src/hermes_escape_top/tests/test_morning_publication_observation.py | 新增，329 行，e42644e8726d783dbd3eb212e98459d4c3d9964222c9bc00755db40209331021 |

ops 修正前为 `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d`，before 副本和 slice.patch 单独绑定。旧 B/review_fix 的 source-binding 将该 ops 摘要登记为依赖；本片有意修改它，不再声称旧 B 的所有依赖仍匹配当前树。旧冻结包不重写，A 的13项仍匹配；review_fix其余19项保持。

生产增量仅在 ops 脚本，不改 B、5g、producer、事务、身份、评分、config/flag、比较器、依赖、CI、WebUI或部署脚本；原 morning/v2 测试不改。没有新 CLI 参数、开关、调度、目录索引或补发机制。实际系统任务仍执行独立 libexec 安装件，不是仓库此文件；本片不能写作线上已修复。

## 2. 实际数据通路

新增 `operational_observations.broker_cache_publication`，不增加第八项主检查，不改两组 readiness 检查集合或部署认证规则。

1. 在主 receipt/audit 读取之前记录 current 物理发布、固定 archive、两原始文件的流式 SHA；文件缺失/非普通文件/链接/解析根失败保留未知。
2. 使用本次 `_collect_release` 已确认的发布名定位 `base/releases/<name>/hermes_escape_top`；在私有随机包命名空间只加载三个现有标准库 reader，不执行项目 __init__，不改 sys.path，不使用已导入开发模块/旧发布缓存。
3. 源模块及其目录/发布层级链接、缺失、目录冒充均拒收；直接编译选定源字节，不用旧 .pyc。finally清理本次命名空间。
4. 调用未改 B 一次，由 B 自行唯一选择正式 run；不把主 reader 的较宽解析当成 B 的替代，不读取当前 broker 缓存、不连接 SQLite/网络、不持锁/恢复/补发。
5. 结束时再次核对 current/archive/receipt/audit，及双方实际提供的 run/capture 身份；不一致即 UNKNOWN / EVIDENCE_CHANGED，丢弃可能成功的辅助声明，不重试选另一 run。

这两个 receipt/audit 摘要是本次读取一致性检查，不是 journal producer 锚点；5g仍由B转交正式receipt中的原journal摘要，改坏journal后不得现场重锚。

## 3. 状态与失败语义

- 明确 v1/OFF：INFO / NOT_APPLICABLE / CAPTURE_DISABLED，不误报已发布。
- v2 缺观测：UNKNOWN / ANCHOR_UNAVAILABLE；未知 schema、深 JSON、缺失辅助回执或原摘要拒收继续保留 B 的 UNKNOWN。
- 无法确认发布、没有有效读取快照、缺/坏源码分别保留 RELEASE_UNVERIFIED / EVIDENCE_UNAVAILABLE / READER_UNAVAILABLE；不回退开发目录或旧安装。
- 有效 v2：保留 B/5g 的 OK/WARN/INFO/UNKNOWN、publication_status、reason、身份/摘要及本机来源字段，不改写成主验收 PASS。
- 正式 FAILED 和辅助 OK 可并存；原 checks/status/readiness/certification 仍失败，不“消红”。PENDING也不能被辅助OK提升。
- WARN/UNKNOWN在观察表及summary明确显示，包括主FAIL时；保留原主失败check ID和详情。INFO/OFF不新增警报。原CLI 0/2/3语义不变。
- JSON保留完整观察字段；Markdown通过现有detail列同时显示status/publication_status/reason/official_receipt_status/anchor_source，缺失写UNKNOWN。无需改渲染架构。

本机producer声明不是签名；OK不证明当前缓存内容/新鲜度/IBKR连通。原始输入的前后相同不是敌对同用户、并发ABA或OS级隔离保证。装载失败不泄露异常堆栈或broker内容，仍是非阻断运维UNKNOWN；不是悄悄补证据或扩大主验收许可。

## 4. 逐项验证与归属

新增37项，覆盖：真实v1路径、五类源码重定向/缺失、收集中三类文件/发布变化、12组主PASS/FAIL/PENDING与辅助四状态、系统Python隔离加载、四类真实B未知证据、五类真实v2声明、真实producer通路、循环链接、reader期间变更/错run、异常后跨release不串模块。

| 验证 | 当前执行结果 |
|---|---|
| 新文件 | 37 passed / 7.14s |
| 明确四文件关联 | 182 passed / 16.21s，完整argv保留 |
| 全套 | 2179 passed / 1421.17s，exit 0；不是2142+37算式推定 |
| Governance | 8/8 OK，ibkr_readonly=true |
| 两文件完整Ruff / 全仓severe | PASS / PASS |
| 原15文件mypy门禁 | PASS，无新ignore/exclude |
| 扩大ops单文件mypy | 修正前4条、当前4条，消息逐字相同、仅行号移动；未清零 |
| compile / pip check / diff check | PASS |
| 外部故障演练 | 13场景各自达到预期，顶层PASS、零网络、未触live；不是十三源全OK |
| 四日期OFF strict | all_equal=true，4/4空strict差异 |

关联argv明确列出 `test_morning_acceptance.py`、`test_transaction_v2_acceptance.py`、`test_scheduled_broker_publication.py`、`test_morning_publication_observation.py`，不是旧243/外审247子集。运行记录包含解释器、完整参数、源前后SHA、退出码、耗时和原始日志。

新增功能先RED：缺观察键、源码链接被接受、三类收集期变化仍INFO、主FAIL遗漏辅助WARN/UNKNOWN摘要、循环链接让收集抛RuntimeError；各自修正再GREEN。初次v1的GREEN尝试还因新fixture把audit hash规范化后未同步health hash而失败，随后只修新fixture，旧主检查保持。此记录保留，不冒充生产缺陷或一次全绿。性能探针初次也因仓库外pytest未加载isolated_data_dir失败，已显式复用既有fixture后重跑，不改生产代码。

真实producer集成使用既有receipt_run/broker_run夹具，在tmp持真实lease跑实际评分/commit/receipt，再进晨验；夹具对报告/配置/外部边界已有stub且include_ibkr=False，不是自然scheduled/真实IBKR/完整daily验证。主健康材料仍是原晨验合成夹具，与该producer业务日不匹配时主FAIL如实保留。观察阶段对网络/SQLite/write_text/write_bytes加禁令，输入字节/mtime/mode不变，真实B只调用一次。

系统Python `/usr/bin/python3 -I -S -B`实际完整收集tmp v1，恶意项目__init__未执行、sys.path不变、无开发包/pandas/numpy/ib_insync导入，私有模块清理完成。这比上一片仅装载模块的可行性探针更进一步，仍不是安装件验证。

## 5. I/O、比较器与指纹边界

三个夹具各做修改前/后3次诊断：v1 audit389 bytes/0输入文件；最小v2 audit401 bytes/2输入文件；真实producer v2 audit约341KB/256输入文件。后者主FAIL是健康日期夹具边界，辅助INFO是未发布，不冒充完整主验收成功。

本轮完整producer样本：原收集约0.042-0.045s，接线后约0.098-0.099s，每次调用B一次。不是线上延迟承诺、磁盘冷缓存基准或长audit增长测试；不声称零I/O，保留每日一次线性读取及重复v2材料校验开销。不为加速跳过validator或缓存最近成功。

四日期基线377/24f37156...，候选378/3389d65d...，种子57/8557342f...。src清单差集只有新增测试；**比较器既有src根不覆盖ops，本片关键ops增量靠单独source-binding/before/patch及晨验集成测试证明，不靠strict报告给ops背书。** 比较器19540147...原字节、忽略集不动。

评分指纹两侧仍 `ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad`，不代表它等于live的42d207d6...或已完成A1发布/迁移/旧writer回滚证明。producer15条既有类型债/19条Ruff仍未处理；本片ops的4条类型告警单独复现，不能将15文件门禁PASS写成全部修改文件类型清零。

## 6. 授权与尚未完成

未stage/commit/push/deploy，未执行正式daily/晨验主程序，未刷新行情/外部源或连接/刷新IBKR；所有收集和报告写入都在测试tmp。未修改live、libexec安装件、LaunchAgent、旧Codex任务、09:10/09:15或配置/flag。

候选CI未运行；本地长全套与CI20分钟预算分开记录，不擅自改超时、删用例或承诺云端一定快/慢。A1候选发布/迁移/旧writer回滚、自然ON/v2样本、完整自动T1→T2、hermetic/更广故障/断电耐久性等依旧未完成；live v1的自然观察不能补齐。

下一步是本片冻结候选独立外审；不是安装系统脚本、启用capture或再做一次R6。未来R6 reader工件、libexec晨验工件与capture启用须各自明确批准和部署前置检查。**DEPLOY HOLD；A2 OPEN；Phase B not started。**

## 7. 外审必答

1. before/patch是否绑定当前已审B前置，而不是HEAD旧树？ops是否单列，不借src-only manifest覆盖？
2. 系统Python不带site-packages时可运行吗？仅加载指定发布三源码，拒链接/旧模块，异常后私有命名空间清理吗？
3. 合法R6 data共享链接是否保留？current/receipt/audit改变或双方身份不一致会UNKNOWN吗？
4. B/5g/producer、原journal摘要及schema/深JSON拒收是否未弱化？有无重算journal兜底或跳过validator？
5. 正式FAILED与辅助OK是否同时显示？原七checks、readiness、认证及退出码是否不变？
6. Markdown是否保留未知/正式状态/本机来源，而不只显示OK？
7. 真实producer集成与状态组合stub、性能夹具与自然样本是否分清？
8. 完整argv、RED/GREEN失败原因、类型债、全套耗时与CI预算是否如实保存？
9. 原A/B包是否冻结，review_fix旧ops依赖被本片有意修改是否明示？
10. 是否没有Git/安装/部署/刷新/IBKR授权外操作，A2/Phase B与自然观察门槛是否保留？

## 8. 最终封存

最终全套 **2179 passed / 1421.17s**，验证调度器退出0；37新测试、明确四文件182关联、治理8/8、静态/编译/依赖/故障演练/四日期OFF strict均已执行，源前后摘要一致。源码和测试在最终全套期间没有改动，不用中途结果替代最后字节。

新证据目录为 `building/reports/a2_production_capture/2026-11-04/3c5h_morning_wiring/`：25项源码/依赖绑定，51件证据，另有清单本身；`SHA256SUMS.json`自身SHA-256为 `a74e9de973493a6763026a33a4eadb8d6f54df3ae0f6bc0ff8505f9c63ec4d8e`。包括before/ops、可干净dry-run的slice.patch、完整验证argv/源前后SHA、最终/RED/GREEN日志、旧告警对照、三个最终性能JSON、环境及内部复核声明。没有复制私有capture、broker tape、数据库/WAL或真实账户数据。本交接不进入清单，避免自摘要循环。

开始1294件已列举仓库文件中1291件原字节不变；变化仅ops与两旧文档追加（本合同/总计划），两文档旧前缀匹配。新增为本测试、本交接和独立证据包。旧A22件、旧B24件、review_fix33件及三清单全部匹配，不为新增C刷新旧包；review_fix的ops依赖变化按第1节明确说明。

新一轮内部只读复核未报P0/P1/P2，独立19定点通过，消息和命令存于internal-review.json。复核者还自述12组直接before/candidate主状态对照通过，但仅在其工具记录里以内联stdin执行，未另存探针/日志或摘要；这是补充复核证言，不冒充包内可独立复算的必需门禁，更不是外审批准。作者37/182/2179与完整日志独立保存。内部复核代理已结束。

复算时可从当前候选隔离副本删除C新测试、用before/ops覆盖该ops文件，重建代码基线；核对src清单377/24f37156...，不要用HEAD旧代码代替B前置。四日期的种子单独来自既有HEAD归档数据，必须核对57/8557342f...；不拿当前可能已变的live/共享data替换。记录的源/种子/解释器/比较器SHA均需先审后用；before并非完整环境归档，私有runner路径也不是对外永久存储承诺。

本地全套23分41秒与CI20分钟预算分列，未改CI或声称云端绿；候选级CI仍待真实提交后验证。独立外审待执行，Git、libexec安装、R6、capture启用和自然观察均未获本轮授权。**本片完成本地实现/验证及封存；DEPLOY HOLD；A2 OPEN；Phase B not started。**
