# 最终整树外审更新：接收与处置

日期：2026-11-05，Asia/Shanghai。

**已接收独立外审更新：最终候选正确性 PASS（审计员所述限定范围）、建议精确 Git 整合/提交/推送；部署 HOLD，A1 生产证明 OPEN，A2 OPEN，Phase B 未启动。本轮没有产品修复、Git 写操作或部署。**

## 1. 原文来源与本轮核验

原附件：`/Users/liweishi/.codex/attachments/c59a26e9-b527-4637-b178-98e04b24f1ed/已粘贴的文本.txt`。

原文归档：`docs/history/2026-11-05_final_integrated_external_audit_update_report.md`。

两者 SHA256 同为 `f0238cf22fef1c87ba218f0e742100ce72e41b712af5b83088a4755445c4951f`，10863 字节。按原字节保留，包括 CRLF，不补 LF、不改措辞。以下澄清均在本文记录，不回改审计员原文。

本轮实际重新核对：

- 最终候选 512 文件逐项符合 `90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa` 清单，零漂移。
- MU 证据 JSON SHA `1200bd416ba9de133f8e833d234d1e3c94754c6319699430d2408de233a3a64a`；manifest SHA `3691d0e069f6d9745575ad7231af0e6824e090ce80d7183efae9781281e8e0f0`，与报告一致。
- MU 附注中的八个源文件 SHA 仍匹配；未把本轮只读核验说成重新执行评分或全套测试。
- 原主目录 1370 个登记文件及两原仓 Git index/config 未变；本轮 Git 查询只读，设置 GIT_OPTIONAL_LOCKS=0。

原文引用其“上轮最终整树外审”，但该完整报告不在本次附件中，当前指定的项目报告目录也尚未定位该原文。这里接收的是本次更新中明确给出的结论；不能伪称已读到或复现其上一轮全部日志。后续应补原报告或路径作为来源归档，**不因此擅自要求第四道外审或新增审批步骤**。

## 2. Findings 的处置

### MU 不构成候选缺陷

接受结论：low=791.030029296875 对 782.0，差异 1.1547% 超过既有 1% 上限；canonical 没有追加当日行，第三源仍 research_only，SOXL 实际 9/10 观测，strategy_data=OK、auxiliary_flows=DEGRADED。没有修准入、覆盖历史或“两票对一票”放行的依据。

P3-1 健康提示精度作为独立、非阻断诊断改进登记。**本轮不修改 health.py，不混入冻结候选，不以此更改阈值或重跑 official。** 当前报告无需产品代码修复。

其余运行时点、研究第三源、component-only、C 未安装、证据归属和连续 OK 的记录保持各自边界，不把同一事件拆成多个独立产品缺陷。既有开放项不由本附注关闭。

### 引用口径的精确化

1. **连续 OK：**现存并冻结的 11-04 JSON 为 consecutive_ok=3、target_days=5；11-05 为 consecutive_ok=0。本文没有证据支持实际已达到 5 连 OK；原报告的“3/3 或 5”不能作为既有计数引用。保持其历史原文，只在后续使用精确字段。
2. **两个版本轴：**当前 live 的身份 schema 是 identity-v2，事务协议是 recoverable-journal-v1。报告中“live v1”若被引用，必须限定为事务协议；不是旧身份 v1。候选新增的 v2 事务 opt-in 与身份 v2 是不同概念。
3. **见证摘要：**外层 witness_sha256 绑定比较函数接收的供应商/短字段映射；raw_comparison.witness.sha256 绑定含 date/timestamp、长字段名的规范化 bar。两者投影不同，不要求互相相等，也不能调换“规范化”口径后据此判漂移。
4. **执行耗时与静态债：**作者冻结日志是 2288 passed/1620.79s；审计员所述 2288/1606.88s 是其引用的上一轮来源，不能写成作者本轮执行。已核冻结材料支持“指定 15 文件 mypy PASS、wrapper 4 条 mypy/17 条 Ruff”；报告另述的更广 15/19、ops 4 应保留为其上轮口径，在取得原报告/命令日志前不重命名或假称本轮复现。

本轮未改变报告的 PASS/HOLD 判定，也未将上述澄清冒充新的代码审计或独立复跑。

## 3. 下一可授权动作

外审建议允许进入精确 Git 整合与 CI；**建议不等于用户已经授权操作**。当前精确最终候选尚无集成提交，过去对 c1f4b8f 的提交/部署授权不自动适用于它。

建议授权范围：

1. 新建独立整合目录和 `codex/` 分支，以真实 c1f4b8f 为起点；两原仓与冻结候选不改。
2. 仅按最终 54 条实现差异整合，再逐项核 512 清单及脚本权限；文档、公开证据和本报告接收记录单独显式列清单。
3. 排除三份九月计划、私有 capture、账户/持仓/DB、实验临时目录；不 git add -A，不复制候选私有 `.git` 当成新提交。
4. 精确提交并推送至 **GitHub wishlidong-afk/hermes** 的审查分支，再检查该精确提交的真实 CI。未授权合并主分支时，不自动合并。
5. 不部署、不安装 libexec、不改 live config/调度、不启用 capture、不重跑 official、不刷新行情/外源或 IBKR。

特别注意远端：主仓 origin 是 GitHub wishlidong-afk/hermes；热修来源仓 origin 是另一个**本地目录** `/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23`。不能在来源仓直接 push 并声称已推到 GitHub；授权后应只在新整合目录明确设置目标，原仓 remote/config 保持不动。

CI 通过与实际配置/清单过渡证明、发布窗口、单次 R6、libexec 安装及自然 ON/v2 观察依然分别处理，不用“代码外审 PASS”跳过它们。

## 4. 接收证据

目录：`building/reports/final_audit_reception/2026-11-05/`。

四件绑定 JSON 加 manifest，共五件；manifest SHA256：`1e1f5c7a7b83b928fc26e4a699d6d00247e6a8223de192e5cf4039e76e0bc576`。

包含原文绑定、候选/MU 核验、逐项处置与只读 Git 预检。没有重跑未变源码的 2288、499 或四日期，没有创建分支/stage/commit/push/fetch/merge、安装或部署。**下一步等待针对上述 Git 范围的明确授权；部署继续 HOLD。**
