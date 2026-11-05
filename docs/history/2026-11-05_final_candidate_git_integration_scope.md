# 最终候选 Git 整合范围

日期：2026-11-05，Asia/Shanghai。

用户已明确授权：在独立目录/审查分支精确整合、提交、推送并检查 CI；不合并默认分支、不部署、不安装 libexec、不启用 capture、不刷新或补跑。

## 冻结来源

- 起点：真实已发布提交 `c1f4b8fc1df23876fefeccd33bc08e0270627f9e`。
- 被测候选：`/Users/liweishi/Documents/New project/hermes-a2-postcommit-health-2026-11-04/candidate`。
- 源清单：512 文件，`90842a116706bb48fa17f1b2c207649252073ac074db7f8110d0b87d775448aa`。
- 实现增量：清单内相对 c1f4b8f 的 54 条路径；复制后 512 项字节与执行位全部匹配。
- 评分指纹：`ac025f0f93d16ee3b97e1aaa8f7e70b49801032d81085453b7e5531eae8e7dad`。
- 运行时锁：`71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62`。

本提交不含新的产品修复。独立外审更新、接收澄清与 MU 运行附注保持原文；缺失的上一轮完整外审原文仍按接收记录标明，不能伪称已补齐。MU 提示精度 P3 未混入冻结实现。

## 精确交付范围

54 条已审实现增量，加 21 份 11 月 4/5 日的既有交接/外审文档，以及以下九份完整公开证据包（267 文件，含各自 manifest）。另新增本文和本次来源校验摘要，不复制候选私有 `.git`。

- `a2_release_integration/2026-11-04`
- `a2_postcommit_health/2026-11-04`
- `a2_final_gates/2026-11-04`
- `a2_a1_boundaries/2026-11-04`
- `a1_v2_rollback/2026-11-04`
- `final_external_review_preflight/2026-11-04`
- `final_integrated_external_audit/2026-11-05`
- `market_quarantine_followup/2026-11-05`
- `final_audit_reception/2026-11-05`

证据目录均位于 building/reports。按 manifest 枚举后逐项复制并校验，没有泛选未跟踪目录。三份九月计划、私有 capture、账户/持仓/DB、实验临时目录均排除；没有 git add -A。

## 隔离与验证

两原仓保持不动，使用独立、无硬链接的克隆。新目录的 origin 明确为 GitHub wishlidong-afk/hermes；没有继承来源仓指向本地目录的推送目标。作者身份复用既有 c1f4b8f 提交，仅设置在新仓局部配置，不改全局身份或凭证。

首次测试收集因日报模块按目录层级探测真实 home 下的旧解释器而被 OS 隔离拒绝。记录该失败后，仅将自建克隆移到更深目录重验；没有修改源码、替换函数、放宽 OS 规则或跳过用例。

同一冻结源的 2288 全套、499 定点及真实 c1f4b8f → 候选四日期 strict 继续按各自证据引用，不称为本次重新执行全套。新 Git 状态的测试收集、Git/字节/权限检查及云端 CI 另外记录。

新隔离布局测试收集为 2288 项、退出 0；敏感模式扫描在初始 342 条显式路径内没有命中。54 条实现与新增交付文件的 diff --check 通过。全暂存区的原始 diff --check 仍报告冻结日志/patch 中的空格、历史外审原文 CRLF 和旧提示末尾空行；这些是须原字节保留的证据，不格式化、不改其 SHA，也不声称整包没有空白告警。

仓库工作流只对默认分支推送或 PR 触发。本次不改工作流/20 分钟预算；在合并预览安全且来源一致时创建草稿 PR 触发 CI，不自动合并。最终提交 SHA、PR 与 CI 结果以实际交付记录为准，不能从此前通过推定云端已绿。

**本文件不授权部署。A1 生产发布证明 OPEN；A2 OPEN；Phase B 未启动；DEPLOY HOLD。**
