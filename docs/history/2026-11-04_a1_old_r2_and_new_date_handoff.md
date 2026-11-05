# A1 旧 r2 拒收与新业务日期过渡演练

日期：2026-11-04，Asia/Shanghai。

**本片合成机制验证 PASS；未修改冻结生产源码、未提交/推送/部署。A1 尚未完成，DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

承接 `2026-11-04_a2_final_full_suite_and_a1_r1_handoff.md`。上一片的真实旧 r1 → 候选 r2 → 重复 r2 → 旧 writer 拒绝仍按其原字节保留。本片新增旧 r2 与新 as_of 两类验证，不覆盖旧证据，也不将其解释为自然线上样本。

## 1. 范围与绑定

- 原始主仓和 hotfix 仓库只读；主仓仅新增本文及本片证据目录。
- 最终工具工作目录：`/Users/liweishi/Documents/New project/hermes-a2-a1-boundaries-verified-2026-11-04/`。
- 被测候选仍是 `hermes-a2-postcommit-health-2026-11-04/candidate`，512 文件清单 SHA256 `90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa`；未发生变化。
- 候选评分指纹 `ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad`；真实旧 c1f4b8f 的评分指纹仍为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`。
- 三个私有 R6 release：真实旧 c1f4b8f、候选、同候选源码的第二 release。代码、默认配置、批准配置、lock、离线 VERSION 共 594 项；两份候选仅离线 VERSION 和 release 路径不同。
- 旧代码通过上一片 Git blob 绑定及本片复制前后字节比对传递核验；未新增身份豁免、改变预算或修改评分源码。
- 复用上一片同源同环境 **2288 passed**、四日期 OFF strict、治理及依赖结果，本片没有再跑一次全套。仓库外的工具检查不计入 2288。

最终演练工具 SHA256：`067572cc7931acf40026a0e044d4c380add3d97ff0561a4d771e97ec21462dd5`。

## 2. 真实执行序列

六个不同 PID，真实 score_pipeline/认证/修订/持久化；只替换认证时钟，并重定向两个 broker 缓存。数据来自 Git 跟踪数据与测试夹具，加合成估值 50；不是 live 数据或 live 配置。

所有调用 include_ibkr=False、capture_inputs 默认 OFF，身份格式 v2，**事务协议仍是 v1**。新日期使用夹具中实际存在的 2026-06-01 行，不是只推进墙钟。认证时钟合成设在 2026-06-03，各次均为 FINAL；不声称自然日程运行。

| 步骤 | 实际结果 |
|---|---|
| old_r1 | 真实旧代码为 2026-05-29 建 r1，七产物 COMMITTED |
| old_r2 | 只在私有夹具将 SOXL 当日 OHLC/adj_close 同比例乘 1.025，刷新私有 manifest；真实旧代码建立 r2 |
| candidate_blocked | 候选对同日旧 r2 报原始 `same-date decision revision budget exhausted`；七个已存在业务文件 SHA 与 audit 字节均不变 |
| old_repeat | 拒收后旧 writer 仍能重复原 r2，未重建链或额外消耗预算 |
| new_date | 保留旧 audit/state，候选以实际新 as_of=2026-06-01 建新 r1 |
| new_release_repeat | 同候选代码的第二 R6 release 再评分，新日期仍 r1、同 semantic_hash/decision_id |

成功序列 **[1,2,2,1,1]**，中间另有一次预期拒收。最终 5 条成功 audit 与 5 条 SQLite score_runs；返回报告/audit/state 的认证与 input_hash 逐项一致。六进程网络尝试均为 0，两个 broker 缓存没有文件，结束后无活动事务指针。

前驱直接断言，不以 ID 相等代替：旧 r2 及 old_repeat 的 supersedes_decision_id/previous_decision_hash 均保留旧 r1；June1 首次及跨 release 重复的两个前驱字段均为空。新日期后重新计算旧 audit 字节前缀摘要，原记录仍保留。没有清 audit/state、手写修订链或扩大预算。

## 3. 观察差异与结论边界

旧 r1 → 旧 r2 的语义差异仅出现在 history_hashes/SOXL、scored_snapshot_hash、decision_outputs_hash：实质行情变化确实传播到了真实评分，不是仅换 operation ID 构造 r2。

June1 跨 release 的 semantic_identity 差异为空，scorer_release_hash 则确实不同。原始 input_hash、来源路径、完整 manifest 和其他观测字段没有被重写为相同值；不把语义稳定称为完整 payload 字节相等。

PID、UUID、私有目录及派生 SHA/ID 是本机本轮记录。换目录独立复跑应核对字段关系和机制，不能要求整份 JSON 或 decision_id 跨目录相同。

本片说明：**旧 r2 不能靠安装候选解除；新业务日期可以在本合成样本中建立独立链。** 不证明任意生产数据、实际 live 配置、新指纹生产发布、ON/v2 或自然周末/周一序列。

## 4. 验证工具问题与处置

未为这些问题修改生产实现：

1. 初次 old_r1 成功后，mutator 错用大写 CSV 列名，在修改行情前报 KeyError。真实格式为小写 date/open/high/low/close/adj_close；修正并先验证字段集合，在全新私有根重跑。原失败工具、日志和根保留。
2. 后续正常六步先通过，但内部静态复核指出：父进程日志可能跟随链接；父 token 不能单独证明 OS 隔离；清单可缩减/遗漏额外可导入文件；缺少直接前驱断言。工具补强后再以全新根完整复验。
3. 最终输出用排他创建、O_NOFOLLOW 及父链接检查，拒已有文件/悬空链接。worker 先核对实际 OS 网络限制，并要求工具和 binding 的只写打开被 OS 拒绝；探测不截断、不写入内容。其 profile 仅放行私有业务数据/tmp/cache 和本次单份报告，不允许写工具、清单或其他报告。
4. 固定 512 源清单文件自身 SHA；594 项材料的规范化摘要固定为 `08e37a470b7c6b6497aef56c828977b3925f04f0d5b2dd8050484de5343b36ac`，并核对完整 Python 文件集合。历史修改要求精确私有真实路径且拒文件链接。
5. 复核又指出清理 launch 前的 PRIVATE 父链接检查顺序；最终在 gate 首行及任何 unlink 前拒绝 ROOT/PRIVATE 链接。该修正经内部定向复核接收，再于最终根重跑六步。
6. 最终 **11 项工具拒收**通过：无受控启动、缺清单、错工具摘要、清单缩空、链接输出、已有输出、额外 Python、PRIVATE 父链接、第二 release 配置漂移、VERSION 漂移、旧源码漂移。检查故意改动的只是私有实验副本，随后恢复并重验 594 项。上一片原 11 项全套/父 token 检查作为未变依赖复用，不混算成新执行数量。

内部复核者 Hume 仅静态审工具，未替作者运行评分；不构成用户独立外审。工具 token、SHA 和 OS profile 不是对抗同用户恶意代码、并发祖先换链的新安全边界，也不是签名。

## 5. 最终验证与证据

| 检查 | 结果 |
|---|---|
| 最终六进程机制 | PASS，22.62s |
| 独立事后核对实际 audit/SQLite/journal | PASS；5 行成功、七产物 COMMITTED、前驱正确 |
| 最终工具拒收 | 11/11 PASS，未调用评分 |
| 本片四工具 mypy | 0 issue，原始参数及日志入包 |
| 本片四工具 Ruff 指定 E/F/I、120 列 | PASS；不是全仓完整规则零债声明 |
| 候选 512 文件及准备材料 594 项 | 前后摘要一致 |
| 原主目录 1370 文件、两原仓 Git HEAD/index/config | 未变 |
| 上一片冻结证据 45 件及 manifest | 未变 |

新包：`building/reports/a2_a1_boundaries/2026-11-04/`。

**44 件绑定文件 + SHA256SUMS.json = 45 件**；manifest SHA256：`91e97ee8a83f13f99a23d510af7ce34da4022323c0e50a128a0c793e2c134204`。

包括最终工具、准备/执行绑定、六份报告与日志、独立 postcheck、11 项拒收、精确执行记录、原失败记录、补强前工具、内部复核处置与保留核验。工具副本仅供阅读，不应在证据包目录运行。未复制私有 DB、完整 capture、真实账户或持仓。

## 6. 下一片

本地 A1 四类机制中，旧 r1、旧 r2、新业务日期已分别获得所述受控证据；**v2 活动事务回滚边界尚未补齐**：

- PENDING 活动指针：真实旧 writer 应拒绝；升级 writer 如何恢复及其业务前态需逐项验证。
- COMMITTED 但活动指针未清：不能误判为未提交后回滚，应确认旧 writer 拒绝及升级恢复保留提交内容。
- COMMITTED 且指针已清：不能宣称旧 writer 无条件拒绝；还需确认它是否继续进入真实身份/预算守卫及可接受行为。

不重跑未变化源码的 27 分钟全套。之后仍有实际 live 配置/数据绑定、最终集成外审、精确 Git 授权/CI、发布与安装授权、自然 ON/v2 和既有开放项；本片不替这些门槛授权。

**未运行官方 daily 或晨验，未刷新行情/外源，未连接或刷新 IBKR，未修改 live/主系统任务/配置。DEPLOY HOLD；A2 OPEN；Phase B 未启动。**
