# 日报评分返回后的失败健康报告修复

日期：2026-11-04，Asia/Shanghai。

**本片在新隔离副本中完成修复和验证：15 项新测试、499 项组合、四日期 OFF strict 均通过。原源码和上一轮候选/证据未改；未提交、推送、部署或安装。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

本记录承接 `2026-11-04_a2_hotfix_isolated_integration_handoff.md` 第 5 节的 P2。该问题现为“指定评分返回后场景已在隔离候选修复”，不是“live 已修复”，也不取代其他阶段门槛。旧交接的 OPEN 为当时记录，原字节保留。

## 1. 根因和最小改动

原调用为 `payload = _execute_daily(...)`。内部真实评分及七项业务事务已经完成，但 translate、write_artifacts、post_run_diff 或 state_commit 随后失败时，函数不能正常返回，外层 payload 仍为 None。失败回执能写出，而失败健康报告被 `payload is not None` 条件跳过，因此旧报告可能继续留存。

生产差异仅在 `src/hermes_escape_top/scripts/run_daily_package.py`：

- 既有调用内 context 的类型允许携带真实评分结果。
- run_score_pipeline 正常返回后，将同一个结果引用保留在本次 context 的 score_payload 中。
- 外层异常时，仅在尚未收到正常返回结果时取回这个本次引用。
- 原 scheduled 限制、真实 FAILED 回执写入成功条件、原异常重新抛出逻辑均不变；不改变已经 COMMITTED 的业务事务。

没有从旧报告、audit、broker cache 或历史 snapshot 重建 payload；没有新增通用缓存、observer、CLI 参数、开关或恢复机制。context 每次调用重新创建，不写入业务 payload、回执或身份输入。

未改 pipeline、认证/修订、预算、身份投影/排除集、准入/witness、config/flag、依赖、比较器、WebUI、ops、CI 或部署工具。capture 默认仍 OFF，不新增正式入口传 True。

## 2. 精确候选与来源

| 对象 | 绑定 |
|---|---|
| 基线 | `/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/candidate`，上一轮冻结的完整整合副本 |
| 当前候选 | `/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate` |
| 基线日报 SHA256 | 750895d04548896ff475e13e344cedd85a87bd7bae74c8ca47fe7e18cc9e9570 |
| 当前日报 SHA256 | a897b2dfcadcdac770d2c3a242db2e6661f06b8698b0854c03b4cfd0dd4ac8f2 |
| 新测试 SHA256 | 3b4a52d81148b8936043dbddbcd67d8a42dbee7f0a6fa25798b5aba3546f9634 |
| 当前源码清单 SHA256 | 90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa |
| 两侧评分逻辑指纹 | ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad |
| runtime lock SHA256 | 71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62，未变 |

源码清单包含上一轮相同的 src/ops/scripts/workflow/requirements 范围和夹具，新增测试后为 512 个文件。相对上一轮仅一个生产文件修改，加 `tests/test_postcommit_failure_health.py`；不是相对原仓库 HEAD 只有这两个差异。完整候选仍包含此前累积 A2 和已发布热修整合，须分别引用各自审查来源。

私有 Git 元数据沿用此前副本，仅供既有测试枚举 tracked 数据。HEAD 仍不是集成提交或本片发布标识；没有创建分支、提交、暂存或推送。

## 3. RED/GREEN 和测试口径

第一项先在基线字节复现：真实隔离评分事务 COMMITTED、七项业务文件和当前提交锚点都在，但翻译异常后报告仍是 previous-input，而不是本次 audit 的 input_hash。`red-translation.log` 为 1 failed。最小修复后同一项 1 passed，日志及当时测试 SHA 均保留。

随后扩展为 15 项：

| 场景 | 项数 | 主要验证 |
|---|---|---|
| 翻译异常 | 4 | capture OFF/ON × 显式/自动业务日期；真实 FAILED 健康 JSON/Markdown 和归档绑定本次输入 |
| 写出、diff、状态提交异常 | 6 | 三步骤 × OFF/ON；准确 failed_step、原异常语义、七产物字节不回滚、COMMITTED 不变 |
| 二次健康存储失败 | 2 | OFF/ON；确有本次报告尝试，但不覆盖原始错误、不伪装成功 |
| FAILED 回执写入失败 | 1 | 不合成回执，不凭 payload 伪造健康证明；业务提交保留 |
| 下一次调用在评分返回前失败 | 1 | 不借前一次 payload 或 observation，旧审计字节不变 |
| 非官方评分后失败 | 1 | 不发布正式回执或正式健康报告 |

扩展测试首次为 6 failed / 9 passed，原因是新 helper 误将 v2 的 role 字段要求施加于 v1。日志显示真实失败报告已经生成，失败点为测试的 KeyError。只修新测试：v2 仍按 BUSINESS 角色筛选，v1 按其原格式取七行，再共同断言精确 business_paths 集合和七文件字节。未改生产协议，也未改旧测试或放松七产物检查。该次日志原样保留，不冒称又发现六个生产缺陷。

修正后 **15 passed / 60.98s**。随后在最终相同字节一次执行上一轮 484 项加新 15 项，结果 **499 passed / 217.18s**，完整 16 文件命令在 `verification-runs.json`；不是将多轮重复次数相加。

夹具复用真实评分/认证/事务，数据根及两个 broker 缓存路径在 tmp、网络调用受既有夹具拒绝、include_ibkr=False。翻译等故障点和外部外围存在替身。打印的 LIVE 指的是私有数据根中的参数分支，不是操作真实 live。不是完整官方 daily、自然 scheduled 或真实 broker 演练。

## 4. 其他验证

| 检查 | 本轮结果 |
|---|---|
| 四日期 OFF strict | all_equal=true；2022-01-03、2022-01-25、2026-05-29、2026-06-04 全等，零 strict differences |
| 治理 | 8/8 OK，ibkr_readonly=true |
| 新测试完整 Ruff | PASS |
| 全仓 severe | src/scripts/ops 的 E9/F63/F7/F82 PASS |
| 指定 15 文件 mypy | PASS，精确命令保留，无新 ignore/exclude |
| 日报扩大 mypy | 前后均 4 条，消息及重复次数完全相同 |
| 日报完整 Ruff | 前后均 17 条，消息及重复次数完全相同 |
| 编译 / pip check / diff check | PASS；git diff --check 不涵盖 untracked 新测试，新测试另有 Ruff/编译检查 |
| runtime | 复用上一轮私有 Python 3.11.15 环境，32 个 pin 重新逐项核对，未重新解析或安装依赖 |
| 源保护 | 本轮开始时的 1370 个主目录文件、上一轮候选 511 个登记文件、旧整合包 38 件绑定证据全部未变；两原仓库 HEAD/index/config 未变 |
| 补丁还原 | 在另一私有普通目录应用 increment.patch，两个差异文件字节全部等于当前候选 |

严格比较使用未改动比较器、同一个解释器及基线夹具数据，两侧均默认 capture OFF/include_ibkr=False；覆盖评分 payload 与七项业务持久化，不运行日报包装步骤。因此它证明历史评分/产物没有回退，**不单独证明新失败诊断行为**，后者由上述真实隔离故障测试证明。比较器只登记 src，ops 等另在完整候选清单绑定。

仍没有执行当前整合树的全套测试，不能引用旧 2179 当作本树全套结论。也未重跑依赖漏洞扫描或外部故障演练：依赖及相关源字节未变，本片不据此新增相应通过声明。

## 5. 内部复核和限制

Hubble 对两侧差异与新测试进行了只读静态复核，未发现本片新增可达的 P0–P3 问题或已证实的测试假阳性；没有替作者跑测试。记录在 internal-review.json，不能写成用户独立外审或部署批准。

必须保留的边界：

- 评分函数内部若已提交但在返回前失败，仍没有本次真实返回结果，本片不会读取旧 audit 拼造报告。这不是所有 COMMITTED 后故障的全面修复。
- 正常返回后的六字段 observation/result 交叉检查保持原状；失败分支原本不经过它。本片保留真实生产者链条的绑定，不宣称拒绝任意人为篡改的 payload 或提供新的防篡改边界。
- 健康存储自身不可用或 FAILED 回执不可写时，仍保留 FAIL/缺证据和原错误，不保证报告一定产生；旧文件留存不等于被认证为本次证据。
- 未证明健康报告多文件发布的断电原子性、SIGKILL 恢复、磁盘耐久性或同用户敌对并发安全。
- 指纹不变不等于已解决 live 42d207d6... → ac025f0f... 的 A1 发布/预算/旧 writer 回滚问题。

## 6. 新证据包与下一步

新包为 `building/reports/a2_postcommit_health/2026-11-04/`，24 件绑定文件加 SHA256SUMS.json，共 25 件。manifest SHA256：`958ed44498c80000501fa7d8767866dca13bb1bfa43c9d1f7c112f84c82c6267`。

包含源码清单、保护核验、静态债对照、内部复核摘要、两文件增量补丁、严格比较 JSON、精确命令和本轮全部日志。源副本和回归夹具留在上述私有工作目录；没有纳入真实账户/持仓、live 数据或私有 broker capture。旧 A/B/C、上一轮整合包和三份九月计划不改。

下一步是针对这版冻结候选补最终整树全套，并安排当前身份 v2 的 A1 过渡/预算/新日期/真实旧 writer 回滚证明；本片四日期已完成，不在字节不变时重复制造同一证据。完整集成外审、精确 Git 授权与云端 CI 仍单独验收。

发布、libexec 安装、是否启用 capture 仍须各自明确授权。未运行正式日报或晨验、未刷新行情/外源、未连接或刷新 IBKR、未修改 live 或系统调度。**当前是本地候选修复完成，不是生产修复完成；DEPLOY HOLD，A2 OPEN，Phase B 不启动。**
