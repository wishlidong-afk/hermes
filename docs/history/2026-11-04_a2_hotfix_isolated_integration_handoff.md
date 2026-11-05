# A2 与已发布热修的隔离集成记录

日期：2026-11-04，Asia/Shanghai。

**第一步隔离集成已完成；最终字节定点 484 passed。不是整树发布认证，未提交、推送或部署。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

本记录继续执行同日 `2026-11-04_a2_release_integration_preflight.md` 的第一步，附带绑定私有依赖环境及相关静态检查。不把 A/B/C 原外审 PASS、旧 2179 全套或 live 已发布版本的 CI 转借给本候选。

## 1. 实际源码位置与范围

实际运行测试的源码位于：

`/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/candidate`

| 来源 | 绑定 |
|---|---|
| 共同祖先 | 2db0cdc562309b6222a69aaee8dbdaf51c763b93 |
| 冻结 A2 | 主目录 HEAD 8d16ad8ba639341a38ca5c29e278d12b81bb8efe，加本轮开始时已存在的已审未提交文件 |
| 已发布热修源码 | c1f4b8fc1df23876fefeccd33bc08e0270627f9e，本地来源为 hermes-r6-offline-tools-2026-10-30 |
| 最终源码清单摘要 | 385d6acec3919e8fe3806e807f79a035fd89e999f4d2211f3f574863d0c1fb24 |
| 评分逻辑指纹 | ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad |

清单登记 511 个文件，范围为 src、ops、scripts、workflow、requirements，含既有测试和数据夹具；不含 Git 元数据、开发环境和生成缓存。清单是源码/夹具绑定，不是全机档案或运行环境 hermetic 证明。评分指纹仍不同于 live 的 42d207d6...，本轮没有处理该发布过渡。

副本带有从热修源码仓库复制的私有 Git 元数据，仅供既有测试枚举 tracked 数据夹具。其 HEAD 仍为 c1f4b8f，**不是集成提交**，不得将它作为候选版本号、干净工作树或已合入的证明。未创建分支或 worktree，也未向任一原仓库写 ref/index/config。

相对冻结 A2，实际工程差异为：预检列明的 12 条热修路径，加新增 `src/hermes_escape_top/tests/test_release_integration.py`，共 13 条。11 条文件与 live 源码逐字节相同；日报入口为保留双方职责的合并结果。全部路径及前后 SHA 见 `integration-resolution.json`、`hotfix-retention.json`。

机械合并还带入 live 侧 37 条既有文档/证据路径，在 resolution 单独列出；它们不是本轮新实现，也不是新候选的验证证据。三份九月计划未带入副本、未修改。原 A2 的源码、测试、旧交接和冻结 JSON 均未被写回。

## 2. 日报入口的六处冲突

人工处理仅发生在副本的 `src/hermes_escape_top/scripts/run_daily_package.py`：

1. 合并 A2 身份观察所需的 re/Callable 与热修离线 guard 所需的上下文、socket、runpy、Iterator 等导入。
2. 同时保留离线 guard 和默认 `capture_inputs=False` 的回执入口。
3. 同时保留当前 payload 上下文和本次 commit observer，不使用上一轮观察值。
4. 正式结束回执前将步骤标记为 run_receipt，同时转交可选 commit observation。
5. FAILED 回执保留本次 observation，并仅在已有当前 payload 和真实 FAILED 回执时生成失败健康报告。
6. 保留离线部署的显式 include_ibkr=False、无刷新约束和非官方预览语义，不新增 capture 开关。

机械/初次人工合并后的日报 SHA 为 `1e437d315f912089b70b63839eba512226df6e9699e22e008cd5e60a9aba085e`。扩大 mypy 发现参数字典展开与 A2 可选 Callable 参数产生一条新增 arg-type；随后将原条件字典绑定为 `broker_options: Dict[str, Any]`，条件和值不变，不新增 ignore/exclude。

最终日报 SHA：`750895d04548896ff475e13e344cedd85a87bd7bae74c8ca47fe7e18cc9e9570`。

新增交叉测试 SHA：`c0cf0eb443289694d8a959387dec9d7b4d8ae6166d1efaf54073464bf76088b7`。

未改原始来源 payload、input_hash、准入阈值、Yahoo witness、第三源研究边界、身份投影、预算、config、flag、比较器或 CI。没有将“两票对一票”变成生产准入路径。

## 3. 新增交叉覆盖与限制

新增文件有 5 项用例：

- 真实隔离 A2 评分事务已提交后，尾部新鲜度自检失败：回执 FAILED、failed_step=run_receipt；保留当前 journal/run/capture/decision/input 绑定，七项业务文件字节不回滚。
- 同一场景生成真实健康 JSON，绑定本次输入和 FAILED 回执，健康仍为 CRITICAL；不以提交成功掩盖失败。
- 二次健康写入失败不覆盖原始 end-state 错误；初次 OK 健康写入失败后，只能替换为带相同提交锚点的 FAILED 回执。
- capture/observer 参数与显式 broker 禁用可同时传递。
- 离线部署 guard 内的非官方预览不能进入 capture producer。

前两项由参数化共同覆盖，最终收集数为 5。复用既有 receipt_run/broker_run/capture_root：数据及两个 broker 缓存路径在 tmp，socket 有拒绝替身，外部刷新不执行，真实评分/认证/事务代码运行；报告外围和交易返回边界存在夹具替身。**不是完整正式 daily、真实 broker、自然 scheduled 样本或全故障矩阵。**

## 4. 当前验证证据

最终 15 文件组合的完整命令保存在 `verification-runs.json` 的 `final-focused-484`；日志登记 **484 passed / 153.30s**，runner 墙钟 153.77s，最终三个关键文件的测试前后摘要一致。不是把多轮重复次数相加得到的总数。

| 检查 | 本轮结果及口径 |
|---|---|
| 原问题 RED | 未整合 A2 副本上，既有热修用例按预期失败：预期 run_receipt，实际 alpaca_flow；完整失败日志保留 |
| 初步 GREEN | 初次整合后热修失败证据 9 项通过；使用旧审计环境，只作行为探针，不作新锁依赖证明 |
| 新锁早期定点 | 原 A2 回执 26、新交叉 5、其余组合 453 分别通过；随后类型修正后重新完整跑上述 484 项 |
| 最终定点 | 484 passed；包括回执/失败健康、部署离线约束/参数位置/回滚、冲突计数、A2 commit observation、B、C、晨验、v2 事务读者和原回执 writer |
| 治理 | 8/8 OK，ibkr_readonly=true；相关配置/治理文件未变，类型声明修正不使其证据失效 |
| 依赖 | 新建 Python 3.11.15 环境；32 个 runtime pin 与最终 lock 逐项一致；editable 安装后 pip check 无不兼容 |
| 指定 mypy | 沿用明确列出的 15 文件门禁，零 issue；不是全项目类型清零 |
| 日报扩大 mypy | A2 原 4 条 → 初次整合 5 条 → 修正后 4 条；最终消息及重复次数与 A2 完全相同，只有行号位移 |
| Ruff | 新测试完整检查 PASS；src/scripts/ops 的 E9/F63/F7/F82 PASS；日报完整 Ruff 仍 17 条，与原 A2 消息及次数相同 |
| 编译与脚本 | compileall、两份部署/验收 shell 语法、candidate git diff --check PASS；后者不覆盖 untracked 新文件，新测试另有 Ruff/编译检查 |
| 原源保护 | 1358 个原 A2 文件摘要未变；两原仓库 HEAD/index/config 均未变 |
| 补丁还原 | 13 条工程路径的 integration.patch 在另一私有普通目录执行 check/apply，全部还原字节等于最终 candidate；未在原仓库 apply |

最终 lock 为 live 已用的 `71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62`，包含 certifi 2026.10.19、urllib3 2.8.0。不是重新解析最新依赖。runtime 先 offline sync --require-hashes，再以该 lock 为 constraints 安装 editable dev；命令、解释器和 32 pin 全列在包内。pytest 9.1.1、Ruff 0.15.22、mypy 2.3.0；开发环境不宣称全量 hermetic 锁定。

## 5. 内部复核发现的开放项

内部只读复核（Carver）未指出上述整合职责丢失，但登记了一项 **P2 继承缺口**：`_execute_daily` 内评分已 COMMITTED 后，若 translate、write_artifacts、post_run_diff 或 state_commit 失败，外层 payload 尚未获得返回值，失败报告条件仍可能为 False，旧健康文件可能留存。

该条件在原热修和 A2 结构中已存在，不是本次类型修正引入。本轮新测试将这些外围步骤替身化，不能拿 484 PASS 声称这些路径已修复。源码因果已核对；复核者自述的纯内存探针没有留存完整脚本/日志，仅作为补充证言，不冒称包内独立可复算门禁。处置：**OPEN，下一片单独回归复现和修复，不在本片夹带新生命周期设计。**

内部复核不是用户独立外审，不授予 commit/push/deploy 权限。producer 及其他文件更大范围的既有技术债也未在此清零；本片仅实算日报文件的 4 条 mypy/17 条 Ruff，不与此前跨模块 15/19 的口径混用。

## 6. 证据包与保存纪律

新包：`building/reports/a2_release_integration/2026-11-04/`。

`SHA256SUMS.json` 绑定 38 件文件，另加 manifest 本身共 39 件。manifest SHA：`f90080bf62fcefc116b90c5623811d9a13336cc086cc360ed7bd7ca775ad84d0`。

包含最终源码清单、逐路径职责/前后摘要、热修保留、依赖、原源保护、13 路径补丁、精确验证命令与全部本轮日志、静态债比较、内部复核摘要及完成边界。初步/最终源码 SHA 不同的日志明确分期，不能互相冒充。37 条 live 旧文档/证据仅登记路径和摘要，不复制成新验证输出。

私有 Git 元数据、虚拟环境、真实 live 数据、broker capture、账户或持仓材料未纳入此包。真实业务执行仅在既有隔离合成夹具中。本轮不运行 morning_acceptance.py 或正式日报、不刷新行情/外部源、不连接 IBKR、不变更 launchd/cron/live。

## 7. 下一步顺序

1. 将第 5 节继承的提交后诊断缺口作为独立小片，先用真实隔离 producer 复现，再修复并验证；不能清除提交证据或将失败改成 OK。
2. 冻结下一版最终候选，在新环境执行整树全套及四日期 OFF strict；**本轮未执行，旧 2179 不能代替。**
3. 针对真实 c1f4b8f 身份 v2 → 最终逻辑指纹，补 A1 发布/预算/新业务日期/旧 writer 回滚矩阵，不借用早期无 identity_schema 的迁移工具结论，不加等价豁免。
4. 最终候选独立外审、精确 Git 集成和云端 CI 分开验收；当前没有集成提交或 CI 结果。
5. 精确发布与 libexec 安装、是否启用 capture，仍需各自明确授权。自然 ON/v2、周末/周一及 A2 既有开放项继续观察；不得补跑 official 制造样本。

**本片完成的是“防止覆盖线上热修的隔离集成 + 交叉验证”。不是完整修复完成比例，不是 A1/A2 闭合，不具备部署条件。**
