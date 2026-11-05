# 最终候选全套验证与 A1 首条过渡演练

日期：2026-11-04，Asia/Shanghai。

**最终冻结候选全套 2288 passed；A1 首条机制序列 [1,2,2] 与真实旧 writer 回滚拒绝通过。未修改生产源码、未提交/推送/部署。完整 A1 尚未完成，DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

本记录承接 `2026-11-04_a2_postcommit_health_remediation_handoff.md`。当时“最终整树全套未执行”的时点状态现已补齐；旧文件及旧证据包保持原字节。新的验证工具全部在仓库外，主目录只新增本文和本轮证据目录。

## 1. 冻结对象与本轮全套

| 对象 | 结果 |
|---|---|
| 实际候选 | `/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate` |
| 源码清单 | 512 文件，SHA256 `90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa` |
| 日报源码 | `a897b2dfcadcdac770d2c3a242db2e6661f06b8698b0854c03b4cfd0dd4ac8f2` |
| 评分指纹 | `ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad` |
| runtime lock | `71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62`，未变 |
| 全套 | **2288 passed in 1620.79s（27:00）**，runner 墙钟 1621.40s，退出码 0 |
| 测试前后 | 512 个登记文件摘要全部一致；并非测试过程中持续改源码后拼接结果 |

使用上一轮独立 Python 3.11.15 环境；命令为 `python -B -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider --durations=20`，完整绝对命令、解释器、数据隔离环境和源码绑定在 verification-runs.json。FRED_API_KEY 为合成值，未使用生产凭证。

2288 是实际完整执行结果，不是把旧 2179、定点 499 或新增用例数加出来的预测值。仓库外的本轮 A1 工具不在这 2288 项内；其 11 项拒收检查、四进程评分演练和独立 postcheck 分别登记，不混算。

生产源未变，复用上一轮同源同环境的四日期 OFF strict、8/8 治理、32 pin/依赖兼容、指定 15 文件 mypy、severe Ruff 和编译结果；不声称本轮重跑它们。引用绑定在 reused-evidence.json。此前日报 4 条 mypy / 17 条完整 Ruff 债仍未清零。

## 2. CI 时间风险

本机全套实际超过仓库 CI 的 20 分钟预算，但本轮没有触发云端 CI，不能据此宣称云端必定超时或通过。未修改 workflow、提高超时、删测试或降低断言。

日志保留最慢 20 项，主要是实际子进程重放、ON/legacy 变体和故障恢复；本轮最慢单项为 23.73s。后续先实测最终提交的 CI，再决定独立分组/预算处理；分组须隔离数据根、两个 broker 缓存及临时目录，不能用共享状态并行或跳过重放来“变绿”。

## 3. 本次 A1 只验证哪一条

现有 verify_decision_identity_migration.py 验的是早期旧身份格式迁移，不能代替本次身份 v2 → 身份 v2 的代码指纹过渡。本片另做一个受控小演练，**只覆盖旧 r1/FINAL 场景，capture 全程默认 OFF，事务协议仍为 v1。**

工作目录为 `/Users/liweishi/Documents/New project/hermes-a2-final-gates-2026-11-04/`。

- 旧版：真实 `c1f4b8fc1df23876fefeccd33bc08e0270627f9e` 的 188 个非测试 Python 文件，逐个以 Git blob 重算核对，并核对配置、批准配置和 lock。
- 候选：冻结源的 197 个非测试 Python 文件，复制件逐个核对；同样核对配置、批准配置和 lock。没有为了演练改认证器、评分逻辑或预算。
- 数据：Git 跟踪数据与现有测试夹具，加合成估值 50。使用仓库默认配置，不是实际 live 配置/数据重算。两个私有 R6 release 共用同一私有数据/估值根，VERSION 为明确的离线标记。
- 时间：合成 as_of=2026-05-29，认证时钟设于 2026-05-31，使初始认证为 FINAL；不是自然周末/周一样本。
- 执行：四个不同 PID，真实 score_pipeline、认证和事务；只替换时钟，不替换评分/动作/认证器。include_ibkr=False，并重定向两个 broker 缓存；网络 audit hook 与 sandbox-exec 隔离启用，四进程网络尝试计数均为 0，缓存目录无文件。

| 顺序 | 代码 | 观察 |
|---|---|---|
| old_r1 | 真实旧 writer | 身份 v2、FINAL、r1；七产物 COMMITTED |
| candidate_r2 | 冻结候选 | 同 as_of 正常升 r2，supersedes/previous hash 绑定旧 r1 |
| candidate_repeat | 同一候选 | 仍 r2、同 semantic_hash/decision_id；观察字段可变化 |
| old_rollback | 真实旧 writer | 原始 revision budget exhausted；七产物 SHA 前后完全相同，没有 legacy 重置 |

postcheck 直接读取本轮私有 audit 和 SQLite：恰有三条成功记录，返回报告/audit/state 的 decision_evidence 与 input_hash 一致，预算仍为 2，无 identity_migration 豁免。提交 journal 均为 COMMITTED、七产物；回滚尝试未追加成功审计行。

## 4. 实际差异，不偷换为“完全相等”

旧 r1 → 候选 r2 的完整认证差异路径已保存：包括认证时间、修订/ID/前序绑定、release、raw snapshot/soft 证据、operation ID、semantic hash，以及 semantic_identity.scoring_logic_hash。**语义身份内部仅评分代码指纹不同。**

旧→候选及候选重复的 decision_outputs 差异路径均为空；这里只指 decision_outputs 所定义的 scores/regime/sizing/routing/reentry/weights/confidence 投影，不能称为完整 scheduled payload 字节相等。原始 input_hash/来源证据没有被改写或强行统一。原始估值来源路径另从真实 audit 提取，见 a1-transition-observations.json。

候选重复时，认证差异仅 certified_at 与 market_admission_operation_id。该样本证明代码指纹即使未改变决策投影，也正常消耗一次同日修订；**不能据此将当前 live 的任意 r2 宣称为可安全发布。**

报告内 PID、时间、UUID、私有 R6 绝对路径、由这些输入派生的身份/原始 SHA 属本机本轮记录。独立换目录重跑应核对机制与字段关系，不能要求整份运行 JSON SHA 或 decision_id 跨目录相同；包内 SHA 仅绑定本轮冻结证据。

## 5. 工具问题与处置

验证工具没有混入冻结生产源码，准备/审阅过程保留原记录：

1. 初版复制器错误地排除了所有名为 data 的路径，误伤 core/data；当时尚未评分。旧 helper 和 preparation 保留，修正为只排顶层数据目录，并在新私有根重建材料，不覆盖旧准备记录。
2. 内部静态复核发现两个工具 P2：worker 可绕过全套/受控父进程；候选非 Python 材料和执行时漂移没有重验。均先修工具，再执行评分。
3. run/worker 现在都要求精确 manifest、512 文件、成功 full-suite 及源未变，并逐个重验当前冻结文件和 393 项准备材料；worker 另校验父 PID、step 和随机 launch token。父进程唯一正常路径通过 sandbox-exec 启动。
4. checker 重比两侧 config、policy、lock，并绑定 VERSION。preparation 时的 helper SHA 与最终执行 helper SHA 分列，不能将旧准备摘要冒充最终工具字节。
5. 独立 11 项拒收检查覆盖缺失/失败/错树的全套记录、配置/policy/lock/Python 漂移、直接 worker、错父 PID/step/token。故意扰动的仅是自建实验副本，检查后逐项恢复；没有修改原配置或清除业务链。
6. 工具 mypy 初次在动态模块属性赋值处报两条错误，改用显式 setattr 后四工具 mypy 零 issue，完整 Ruff 通过。初次日志保留，11 项拒收在最终工具上重新通过。

最终 a1_r1_transition.py SHA：`d3cf05c609caa56a0b36047f59ac3e6415c78fd86af15af91ec5435eff3c4b6c`。393 项材料在评分前后再次核对一致。

内部复核者 Zeno 已定向接收两个工具 P2 的修正，无新增 finding；只做静态读取，没有替作者跑评分或全套。它不是用户独立外审。受控父进程/本地摘要不是对抗同用户恶意代码的新安全边界，也不是签名。

## 6. 新证据与未完成门槛

新包：`building/reports/a2_final_gates/2026-11-04/`。45 件绑定文件，加 SHA256SUMS.json 共 46 件；manifest SHA：`e171778ffb5198da45f4b8d53c8fbbfa84e26ac83558e44e6ce738189ac386cb`。

包含全套完整日志及慢用例、精确命令、工具与修改前副本、各阶段来源绑定、11 项拒收、四份演练 JSON/日志、postcheck、原证据引用和保护核验。包内 tools 是冻结审阅副本；实际运行位置见命令记录，不要直接在证据目录执行并覆盖它。没有归档私有数据目录、DB、真实账户/持仓或 broker capture。

本轮原 1370 个主目录文件、既有修复证据包、原 Git HEAD/index/config 及冻结候选保持不变。只新增本文和本轮证据，不修改旧交接的历史正文、不混入三份九月计划。

下一片按依赖继续，字节不变时不重复这次 27 分钟全套：

- **旧 r2**：用真实旧代码/真实输入变化建立 r2，再验证候选拒绝与七产物保护，不能伪造链或清 audit/state。
- **新业务日期**：保留旧链，验证确实换 as_of 后建新链及跨 release 稳定；合成行情/日期须明示，不把墙钟跨日当业务日推进。
- **v2 回滚边界**：分别验证 PENDING、COMMITTED 但活动指针未清理、已完整清理的情况；默认 OFF 本片不能替 ON 恢复证明。
- 最终集成外审、精确 Git 授权/提交、云端 CI、实际 live 配置/数据绑定、单次 R6/libexec 安装及 capture 启用授权仍分开处理。
- 自然 ON/v2、周末/周一观察及 A2 其他既有开放项仍未完成。没有补跑 official，没有刷新行情/外源或连接 IBKR，没有修改 live/调度。

**本地全套门槛已补齐，A1 只完成第一条合成机制演练；不批准部署，不关闭 A1/A2，不启动 Phase B。**
