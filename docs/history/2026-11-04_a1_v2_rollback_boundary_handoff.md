# A1 v2 活动事务回滚边界

日期：2026-11-04，Asia/Shanghai。

**三类本地合成机制 PASS；未修改冻结生产源码、未提交/推送/部署。A1 生产发布证明未完成，DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

承接 `2026-11-04_a1_old_r2_and_new_date_handoff.md`。上一片旧 r1、旧 r2、新业务日期均为所述离线机制证据；本片补 v2 PENDING / COMMITTED-active / COMMITTED-clean 三类旧 writer 回退边界。旧文档和冻结证据原字节保留。

## 1. 范围与来源

- 最终工具目录：`/Users/liweishi/Documents/New project/hermes-a1-v2-rollback-final-2026-11-04/`。
- 三套新私有根分别运行 pending、committed_active、committed_clean，均从跟踪数据与测试夹具重新准备，不复制上一片已经写过的 audit/state。
- 复用上一片已审准备器 `verify_boundaries.py`，SHA256 `067572cc7931acf40026a0e044d4c380add3d97ff0561a4d771e97ec21462dd5`。每根 594 项旧/候选/第二候选 release 的代码与配置等材料前后重验；第二候选 release 本片未运行。
- 实际旧代码是 c1f4b8fc1df23876fefeccd33bc08e0270627f9e；实际候选仍是 `hermes-a2-postcommit-health-2026-11-04/candidate`，512 文件清单 SHA256 `90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa`，评分指纹 `ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad`。
- 同源、同环境的 2288 全套、四日期 OFF strict、治理及依赖检查复用，没有重跑或加总本片工具数量来改写 2288。
- 只修改仓库外的验证工具。主仓只新增本文和证据目录；live、生产配置、flag、预算、认证器、事务实现、比较器、部署工具均未改。

最终 driver SHA256：`dd804e34ed7a59b3db23643b07b4701482053dc5d3b653513eadaec991cc06f4`。

## 2. 演练方式

每个场景先用真实旧 writer 为 as_of=2026-05-29 建 FINAL r1，再运行候选的真实 score_pipeline，显式 capture_inputs=True，建立真正 v2 输入归档与事务。身份格式两侧均为 identity-v2；不是旧身份 v1 迁移。时钟合成设在 2026-06-03，不是自然 scheduled 样本。

include_ibkr=False，两个 broker 缓存重定向到空私有目录。OS profile 拒网络、拒私有数据/tmp/cache/本次报告之外的写入，并拒真实 `.hermes` 读取；worker 还核对实际 OS 限制与受控父进程。13 个不同 PID，网络尝试均为 0，最终缓存目录均为空。

没有替换评分、认证、动作、状态持久化或恢复逻辑。两个中断钩子只包裹真实 RuntimeCapture.finish 或 `_clear_active`，先让原绑定/提交实际完成，再记录检查点阻塞；父进程核对握手 PID，发真实 SIGKILL，要求实际退出码 -9。恢复另由新进程持真实 pipeline lease 调用生产恢复 API。

## 3. 三类结果

| 场景 | 中断/提交状态 | 真实旧 writer | 候选恢复 | 后续旧 writer |
|---|---|---|---|---|
| pending | 完整绑定后、提交前，PENDING，SIGKILL | PersistenceRecoveryError，引用 V2_REQUIRES_UPGRADED_WRITER；七业务文件、指针、既有 v2 journal/evidence 摘要不变 | RECOVERED_ROLLBACK；七业务逻辑内容和权限回到捕获前；264 件未提交证据清除 | 真实评分重复原 r1，ID 相同；成功审计修订 [1,1] |
| committed_active | 已 COMMITTED、指针清理前，SIGKILL | 同一指针守卫拒绝；七业务文件、指针、v2 材料不变 | 只清活动指针/备份，不回滚；COMMITTED journal SHA、264 件证据及七业务内容保留 | 进入真实修订预算守卫，revision budget exhausted；七业务文件与既有 v2 材料不变 |
| committed_clean | 候选正常提交并清理完成，无中断 | 不存在活动指针阻断，进入真实修订预算守卫；revision budget exhausted | 不需要恢复 | 七业务文件及既有 COMMITTED v2 journal/evidence 不变；成功审计修订 [1,2] |

committed_active 的成功审计同样为 [1,2]。全部最终活动指针缺失。每场景最终恰有 2 条 audit 与 2 条 SQLite score_runs；认证、input_hash、前驱关系一致。COMMITTED 输入绑定的 decision_id/input_hash 与实际第二条成功记录一致，证据逐文件对 journal after_sha256 重算。

PENDING 恢复以 **SQLite 逻辑摘要 + 其它业务文件字节摘要 + 文件权限**比较，不把 SQLite 备份/恢复后的物理字节相等当作承诺。旧 writer 被拒绝时则七个业务文件的原始 SHA 全部前后相等。失败尝试可以留下自己的失败 journal；本片只要求既有 v2 journal/evidence 不变，不把全部事务目录无新增当成生产契约。

### 重要限制

“已清理 COMMITTED 后旧 writer 被拒绝”在本样本依赖 **旧 r1 → 候选 r2，预算已满**。不能推广成“旧 writer 在无指针时永远不能运行”；例如另一日期只有候选 r1，旧代码逻辑不同可能合法消耗 r2，必须按实际身份/预算另行判断。

本片不证明断电/磁盘耐久性。SIGKILL 只模拟进程中断；没有突然掉电、存储损坏或 broker/cache 生产发布实验。

## 4. 工具审阅与早拒绝

初轮三场景及独立 postcheck 均 PASS，原工具与结果在原私有目录保留。随后增强证据：保存每个子进程的真实命令、PID、退出码、SIGKILL 记录；保存并比对 v2 journal/evidence SHA；导入前拒 case 父目录链接。

内部静态复核 Leibniz 指出一项工具 P2：逐场景预检会在早先场景已经评分后，才发现后续根的 gate/输出冲突，且 summary 未列入预检。最终 driver 的 run 首行改为 preflight_all：在第一个子进程之前检查三套 gate、所有 stage JSON/stdout/stderr/process JSON 以及三份 summary，不存在且非链接才继续。两个针对后续场景 summary 的普通文件/链接反证均要求 launch.call_count=0，已通过。

复核者定向确认该 P2 已闭合；仅静态读取，未替作者执行评分，不构成用户独立外审。最终代码在三套全新根完整复验，不用初轮 PASS 代替最终字节结果。

9 项工具拒收：未声明 case、case/stage 不匹配、parent 模式带 worker 参数、未进入 OS 隔离的 worker、driver 摘要不匹配、报告链接、后续场景已有 summary、后续场景链接 summary、cases 父目录链接。检查本身不调用评分。复用准备器的既有 11 项检查按未变依赖引用，不宣称本片重跑。

工具摘要、token 和 OS profile 不是对抗同用户恶意代码或并发祖先换链的新安全边界，也不是签名。

## 5. 验证与冻结证据

| 项目 | 最终结果 |
|---|---|
| 三场景实际进程矩阵 | PASS，46.16s，13 个不同 PID，2 次真实 SIGKILL |
| 实际 audit/SQLite/journal 独立 postcheck | PASS；[1,1] / [1,2] / [1,2]；七业务角色与证据摘要核对 |
| 工具拒收 | 9/9 PASS；两个后置冲突均未启动任何评分子进程 |
| 本片四工具 mypy | 0 issue |
| 本片四工具 Ruff E/F/I、120 列 | PASS；不声称全仓完整 lint 零债 |
| 候选 512 文件、三套各 594 项准备材料 | 前后摘要不变 |
| 原主仓 1370 文件、两原仓 Git HEAD/index/config | 不变 |
| 上三份冻结证据包 | 内容与 manifest 均不变 |

静态检查初次有 postcheck 空列表类型标注及 exporter 长字符串格式问题，已修正，仅重跑相关静态检查；未重跑已无相关行为变化的 46 秒进程矩阵。原始失败日志保留。没有扩大 ignore/exclude，没有为“全绿”删场景。

新包：`building/reports/a1_v2_rollback/2026-11-04/`。**89 件绑定文件 + SHA256SUMS.json = 90 件**。

manifest SHA256：`abc36c9f30529c8b76d166dcb270ce2ae8dd6b484fc968d9a6c3c062bbf89767`。

包含最终工具、三套来源绑定、13 份报告/进程元数据/stdout/stderr、3 份场景汇总、postcheck、guard、静态记录、初轮对照与内部审阅处置。没有复制私有 DB、完整 capture、真实账户或持仓。工具副本供审阅，不应在证据目录执行。

## 6. 下一步，不提前结案

截至本片，拟定的 **旧 r1、旧 r2、新业务日期、v2 三态回滚**四类本地机制已有分别冻结的证据；这不是完整 A1 生产发布证明，也不是 A2 完成比例。

下一步先整理这棵最终集成候选的统一外审范围与实际 live 只读取证清单，不再修改冻结实现去追逐新功能：

1. 最终整树独立外审：集成的热修、提交后失败健康报告、当前代码指纹与全部 A1 演练一起核对；旧分片 PASS 不自动授权当前整树。
2. 实际 live 配置、as_of/revision/finality、完整 manifest 与 release/输入证据绑定；本片默认配置与夹具不能替代这些事实。只读取证，不做 official 重算或刷新。
3. 明确精确 Git 整合与提交授权，取得真实最终提交并跑 CI。当前候选的私有 `.git` 仍不是集成后的提交；本地 27 分钟全套与 CI 预算风险须如实处理，不能假称云端已通过。
4. 单次 R6/libexec 安装及 capture 启用分别授权；无 writer、保留 live config、不补跑 official，随后等待自然 ON/v2/周末周一样本。
5. A2 其他开放项保持原定义；断电耐久、IBKR/cache 路径和自然观察不因这三例 PASS 自动关闭。

**未运行官方日报或晨验、未刷新行情/外源、未连接或刷新 IBKR、未修改 live/调度/配置。部署 HOLD；A1 生产证明未闭合；A2 OPEN；Phase B 未启动。**
