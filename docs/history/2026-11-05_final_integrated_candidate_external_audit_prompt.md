# Hermes 最终集成候选统一外审

整理日期：2026-11-05，Asia/Shanghai。

**请求独立审查最终冻结整树及其证据链，不是重复给某个历史分片盖章。当前仅 READY FOR EXTERNAL REVIEW；没有新的外审结论，也没有 Git 或部署授权。DEPLOY HOLD；A1 生产发布证明未闭合；A2 OPEN；Phase B 未启动。**

## 1. 必须先识别正确对象

| 对象 | 精确位置/绑定 |
|---|---|
| 真正被测候选 | `/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate` |
| 候选源清单 | 512 文件；`90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa` |
| 候选评分指纹 | `ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad` |
| 候选 runtime lock | `71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62` |
| 真实已发布基线 | `c1f4b8fc1df23876fefeccd33bc08e0270627f9e` |
| 基线 Git 对象来源 | `/Users/liweishi/Documents/New project/hermes-r6-offline-tools-2026-10-30` |
| 基线只读 archive | `/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/live` |
| 共同祖先 | `2db0cdc562309b6222a69aaee8dbdaf51c763b93` |
| 原 A2 主仓 | `/Users/liweishi/Documents/github/hermes`，HEAD `8d16ad8ba639341a38ca5c29e278d12b81bb8efe` 加冻结未提交增量；不是本次最终发布树 |

候选的私有 `.git` 仅为夹具枚举等测试保留旧元数据，HEAD 仍是 c1f4b8f，**不是集成后的提交**。不能只看 git diff/HEAD 就把它当成已经提交的候选；以冻结清单逐文件校验，再核对来源。候选也不是原 A2 主目录原样部署版。

在 512 文件清单内，相对真实 c1f4b8f 有 **54 条新增/修改路径**。完整路径及双方 SHA 见本片 `candidate-vs-live-source.json`；这个计数不包括整个仓库的文档、数据、证据或 Git 元数据，不能称为全仓总差异。

主仓的三份范围外计划不得混入：

- `docs/history/2026-09-05_dated_update_schedule.md`
- `docs/history/2026-09-05_post_release_a_20_dimension_review.md`
- `docs/history/2026-09-05_stabilization_update_plan.md`

## 2. 本次联合实现范围

请先按 source delta 清单逐行审查，再以未变文件核对上下文，重点是跨模块契约：

1. `pipeline.py`、`core/data/decision_revision.py`、`core/data/run_transaction.py`、`sqlite_snapshot.py`、`transaction_evidence.py`：默认 OFF、唯一 v2 生命周期、WAL 前态、提交权威状态、输入绑定、认证 observer、预算与旧 writer 守卫。
2. `core/reporting/decision_inputs.py`、`history_versions.py`、`runtime_capture.py`、`transaction_restore.py`：归档、来源/顺序/选择绑定、恢复目标和双根保护、selected legacy 两种已验证布局、旧 API 兼容边界。
3. `core/reporting/broker_capture.py`、`broker_publication_status.py`、`scheduled_broker_publication.py` 与 `ibkr/positions.py`、`executions.py`：只读 reader、broker tape、提交后缓存/回执发布与失败隔离；没有下单授权。
4. `scripts/run_daily_package.py`：同时保留 c1 热修的失败步骤标签、离线部署保护、FAILED 健康报告，以及 A2 的可选提交观测。评分真实返回之后的 translate/write_artifacts/post_run_diff/state_commit 失败，保留本次 score_payload 和 COMMITTED 事实，不取旧 audit/payload 冒充本次失败输入。
5. 日报热修保留：`ops/run_daily.py`、`ops/verify_live.sh`、`scripts/deploy_to_live.sh`、依赖锁、`web/health.py` 及相关测试，不可因 A2 合入回退。11 条原热修路径逐字节保留、日报入口为手工合并，分别见 integration-resolution/hotfix-retention。
6. `ops/morning_acceptance.py`、`ops/prune_runtime_artifacts.py`：晨验只读消费者、已提交锚点保留、读者失败和旧证据不提升为成功；ops 不在评分指纹内，须单独核对源码摘要。
7. 四个隔离/中断演练器、全部 source delta 中的测试，及下文 A1 仓库外工具：确认真实生产函数执行、真实信号、真实旧源码、反证方向和披露限制；演练工具不等于新增生产调用方。

未改评分指纹排除集、修订预算或比较器忽略项。不能因“评分指纹相同/变化”单独判为行为等价/不等价，须看对应的完整输出和过渡证明。

## 3. 冻结证据索引

所有路径位于 `/Users/liweishi/Documents/github/hermes/building/reports/`。每包先核 SHA256SUMS.json 自身，再逐项核文件；作者生成报告不是其自身正确性的独立证明。

| 目录 | 绑定文件数，不含 manifest | manifest SHA256 |
|---|---:|---|
| `a2_release_integration/2026-11-04` | 38 | `f90080bf62fcefc116b90c5623811d9a13336cc086cc360ed7bd7ca775ad84d0` |
| `a2_postcommit_health/2026-11-04` | 24 | `958ed44498c80000501fa7d8767866dca13bb1bfa43c9d1f7c112f84c82c6267` |
| `a2_final_gates/2026-11-04` | 45 | `e171778ffb5198da45f4b8d53c8fbbfa84e26ac83558e44e6ce738189ac386cb` |
| `a2_a1_boundaries/2026-11-04` | 44 | `91e97ee8a83f13f99a23d510af7ce34da4022323c0e50a128a0c793e2c134204` |
| `a1_v2_rollback/2026-11-04` | 89 | `abc36c9f30529c8b76d166dcb270ce2ae8dd6b484fc968d9a6c3c062bbf89767` |
| `final_external_review_preflight/2026-11-04` | 6 | `c44534768cd2ba0ea1e24ec53a95e6f5b89191b416f76c45e61a1740c705eaae` |
| `final_integrated_external_audit/2026-11-05` | 7 | `41e824a4958c16fcb9ae321c8abc7d8db4df26a62d4f1d0b268000104d7ba16b` |

解释器：`/Users/liweishi/Documents/New project/hermes-a2-integration-2026-11-04/venv/bin/python`，Python 3.11.15、NumPy 2.0.2、pandas 2.3.3、SciPy 1.13.1；runtime 32 pins。精确执行参数、cwd、环境和退出码均见各包 verification-runs.json。不要把不同包中重复执行/复用的覆盖范围相加为更多独立用例。

## 4. 已执行验证及各自边界

### 整树与健康修复

- 最终冻结 512 文件整树：**2288 passed in 1620.79s**，前后源未变。日志在 a2_final_gates。不是从原 2179 加新增测试数预测出来的结果。
- 最终健康修复组合 **499 passed**，含 15 项提交后失败矩阵；RED/GREEN、夹具 v1/v2 角色修正记录在 a2_postcommit_health。代码未变后没有重跑 27 分钟全套。
- 治理 8/8、最终依赖兼容、指定 15 文件 mypy、severe Ruff、编译/差异检查的同源证据复用。日报 wrapper **4 条 mypy、17 条完整 Ruff 既有债**仍在，不声称全仓零债；精确消息见 static-debt 及前后日志。
- 健康补丁仅使用当前调用真实返回的 score_payload；pipeline 内部提交后、返回前就失败的路径不在该补丁声称范围内，不得用旧缓存“补齐”。

### 新补的最终整树对真实已发布旧版 strict

上一份 strict 仅比较“集成候选 → 健康修复”；本片另实际执行 **真实 c1f4b8f archive → 最终候选**，不借用该增量证据。

- 四日期：2022-01-03、2022-01-25、2026-05-29、2026-06-04；**4/4 equal，strict_differences=[]，30.84s，退出 0**。
- 比较完整 normalized payload 和七项业务产物。现有规范化包括时间、临时根、派生 audit payload_hash 与事务运行 ID；未新增忽略项，不能称为原始文件逐字节相等。
- 比较器 SHA256 `19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d`。
- 比较器范围内基线 **344 文件**逐项重算 Git blob，对应真实 c1f4b8f；候选 **383 文件**逐项 SHA 核对；种子 57 文件。这与额外覆盖 ops/scripts/workflow 等的整树 512 清单是不同计数轴。
- HOME、TMPDIR 均在新私有根；OS 拒网络、拒真实 `.hermes` 读取、只准实验根写入。include_ibkr=False；未读取真实 broker 缓存或连接 IBKR。
- 本证据覆盖默认配置、跟踪历史种子、capture OFF 的 score_pipeline 持久化；**不是正式 scheduled 的 A1 认证等价、实际 live 配置/数据重算，也不是 ON/v2 自然样本**。

### 当前身份 v2 的 A1 机制

- 真实旧 r1/FINAL → 候选 r2 → 重复 r2；旧 writer 回退按真实预算拒绝，七产物不变。
- 真实历史输入变化由旧代码建立旧 r2；候选拒绝，旧 r2 仍可重复。真正新 as_of=2026-06-01 建 r1，跨两个候选 R6 release 稳定，旧 audit 前缀与前驱字段保留。成功序列 [1,2,2,1,1]，中间另有预期拒收。
- v2 三态：PENDING 真实 SIGKILL → 旧版指针拒绝 → 候选持锁回滚 → 旧 r1 重复；COMMITTED-active 真实 SIGKILL → 旧版指针拒绝 → 候选只清指针不回滚 → 旧版预算拒绝；COMMITTED-clean → 旧版进入预算守卫拒绝。
- v2 最终 13 个不同 PID、两次 SIGKILL、七业务逻辑/权限对账、audit/state、264 件归档证据和旧 writer 拒绝时原始字节保护已核对。
- 不把 SIGKILL 当断电；不把“本样本 r2 预算已满”推广为“无活动指针时旧 writer 永远不能运行”。
- 工具内部审阅发现的问题已定向修正并在新根复验；内部审阅不是用户独立外审。工具 token/哈希不是对抗同用户恶意代码或并发祖先换链的签名/新安全边界。

## 5. 实际 live 的只读事实：均注明时点

**采集时间为 2026-11-04 22:04:35–22:04:36+08:00；不是 2026-11-05 当前发布窗口，也不是今天的新晨验。** 全程 OS 拒网络和实验根之外写入，没有导入或运行 Hermes 业务入口。

- live VERSION `c1f4b8f 20261031_113642`，188 个非测试 Python 文件逐项匹配真实已发布提交。
- 最新 scheduled：as_of=2026-11-03、identity-v2、r1、FINAL、预算 2；audit/SQLite 的认证与 input_hash 一致。事务 recoverable-journal-v1，COMMITTED、7 产物、active absent。
- SQLite 仅在 WAL/SHM/journal 均不存在时以 mode=ro&immutable=1 读；采集前后主文件及 sidecar 状态重验，不使用可能更新 SHM 的 live 备份/恢复操作。
- 11 月 4 日现成晨验 JSON/Markdown 一致：总体 PASS、runtime_integrity PASS、strategy_decision WARN、CERTIFIED；正式 receipt/audit/事务/watchdog PASS。8766 WARN 是该报告的历史 HTTP 证据，本轮没有再请求端点。
- 绑定健康报告列出 IBKR 快照陈旧 INFO、NAAIM 付费退役 INFO。Dollar WARN 未在该份绑定报告单列，不能据此推定今天/当前 Dollar 正常或异常，也不能挪用旧报告的 Dollar 状态。

### 三项不能忽略的发布约束

1. **清单时点已变化。** 正式认证绑定完整 manifest `2f95f3b97adbe83280cdccc2dcbcf8f1b53c9e9d41e96b61cf6d9945c35250ee`；采集时当前 manifest `669d779762f83f0d4ea86bf61163f19880e358e8a261d063b5a23626f869ee88`，frozen_at=2026-11-04T01:20:10.811411+00:00。当前 55 项文件与当前清单逐项匹配。此差异不自动证明正式决策失效或源损坏，但不能声称“今早认证已经绑定此刻整份清单”，也不能从 r1 直接推断现在发布必定安全消耗 r2。
2. **实际 live 配置没有用于合成演练。** live 原字节 SHA `5cff823ecaec5a5e9b8595f102e7f25d888ab9d1b2f7efb5dc856ec832d67d09` 与 attestation 匹配，readonly=true。相对候选默认配置，三个已批准开关在 live=True/default=False：use_btc_spot_witness、use_cboe_official_indices、use_market_admission_gate；另四个 key 在 live 缺省、候选默认显式 False：use_cd_trend_dedup、use_fred_vintage_pit、use_indicator_cache、use_route_set_transition_buffer。**原始配置 7 处差异不等于 7 个开关翻转**，不应为统一外观改 live 配置；实际加载/身份过渡仍需专门绑定证明。
3. **系统晨验 libexec 不是候选版本。** launchd 实际入口仍为 `/Users/liweishi/.local/libexec/hermes-morning-acceptance/morning_acceptance.py`，SHA `985c617d739b7e45dd9b77d4af3ada440f10e7c6cae6f27c87cbbd283660029d`；候选 ops SHA `217857aa94632ba89db62db630864b56d231e1bc27dd371f9db022187b4698b9`。C reader 按候选实现动态加载包内 broker_publication_status/scheduled_broker_publication，并非一个假定的 libexec 同目录 helper。不能只部署 R6 后就宣称 launchd 已运行 C；需另行审核/授权安装，不改调度。

源配置/七业务文件/receipt/audit/当前 manifest/绑定健康报告在采集前后摘要一致。曾观察 writer 名称匹配数为 0，但未获取锁，**不构成当前无 writer 或已预留发布窗口证明**。

## 6. 建议独立复核顺序

1. 先核所有包 manifest 与最终 512 源文件；检查候选不是错误主仓/旧 HEAD，基线来源真实；审 54 路径差异表的范围与新增文件。
2. 逐行审联合范围与已有热修保留，尤其唯一 v2 生命周期、COMMITTED 权威边界、WAL 前态、认证与正式 receipt 的身份绑定。
3. 审 postcommit 失败健康报告：真实当前 payload、原始 FAILED 与异常保留、无补跑/旧证据代替；核 15 项失败矩阵与接口外限制。
4. 审恢复与归档消费者的默认 OFF/opt-in/目标保护/顺序选择；不把有限 legacy 布局或外置 soft 根保护夸大。
5. 审 broker/receipt/晨验只读交互及提交后缓存失败语义；分别核完整生产模块与离线工具字节，不借老分片 PASS 覆盖新字节。
6. 先读比较器契约/规范化，再独立复核或重跑真实 c1f→最终候选四日期 strict；源/种子/Python/工具绑定不可只信 all_equal 标签。
7. 按原命令自行复现重点测试与整树 2288；若选择复用未变源码的日志，请明确说明复用，不声称自己重跑。对实际当前工具做对应静态检查，完整债不允许悄悄 ignore。
8. 独立复跑 A1 机制时使用全新合成根，遵守工具内绑定与准备顺序；换目录后的 UUID/绝对路径/派生 ID 不要求整份 JSON SHA 相同，检查结构关系、真实 PID/信号/原始拒绝和业务对账。
9. 核 live 时点与真实配置、manifest 差异；若复取证必须只读，不因旧 JSON 合理就把它升级为当前窗口/生产发布证明。
10. 搜索越界操作与秘密/账户/持仓泄露；测试可在审计员私有环境执行，禁止修改作者树/冻结证据、live、配置、system task、audit/state 或 source flags。

## 7. 请分开给出结论

- 最终候选联合正确性：PASS / FAIL / 有限范围；列 P0→P3、精确文件行号、复现实验和残余风险。
- 是否建议按精确清单做 Git 整合/提交/推送；这只是审查建议，不替用户实际授权，不能 git add -A。
- A1：哪些本地机制已成立、哪些实际 live 配置/数据/发布时间绑定仍缺失。
- 部署：在现有未获精确提交/CI/libexec/capture 启用授权及自然证据情况下维持 HOLD，或逐项说明所需证据；不能用本地测试全绿授权直接上线。
- A2/Phase B：不得从本次任一 PASS 推导为完整 A2 已关闭或 Phase B 已启动。

云端 CI 尚未针对最终提交执行；本地全套约 27 分钟，现有 CI 20 分钟预算是待实测风险，不能直接假称云端一定失败/通过、砍用例或擅改超时。后续实际私有数据的隔离过渡实验、精确 Git 操作、单次 R6、libexec 安装和 capture 启用均需按各自范围明确授权；不借部署重跑 official。

**本文件是可交付的外审请求，不是作者自行签发的外审报告。未运行今日晨验或正式日报，未刷新行情/外源、未连接或刷新 IBKR，未提交/推送/部署。**
