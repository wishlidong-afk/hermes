# A1 稳定决策身份：外审结论归档

审计日期：2026-09-05。来源：用户在本对话提供的独立外审报告。
本文归档其判定、证据和限制，不把实施者的整理称为再次独立审计。

## 范围

- 基线：`25073bbd6bf79797e53f78492974f5a6ebacc207`。
- 候选：`.worktrees/a1-decision-identity`，分支 `codex/a1-decision-identity`。
- 审阅的是候选 `git diff HEAD` 加全部新增文件，非主目录空 diff。
- 实现范围、复现命令和迁移限制见同目录 `2026-09-05_a1_decision_identity_external_audit_handoff.md`。

## 三个独立判定

| 项目 | 外审判定 |
|---|---|
| 代码合入主目录 | APPROVE |
| 提交推送候选分支 | APPROVE |
| Live 部署 | HOLD，需取证迁移条件、主目录集成、CI 通过及用户明确批准 |

P0/P1/P2：无。P3 一项：完整 lint 结论绑定工具版本。
外审用项目声明的 Ruff 0.15.22 复现了全部声称；用 0.16.5 得到额外非严重项，主要涉及 verifier 的 shebang 和 subprocess 调用。
当前项目已锁定 0.15.22，本批不升级 lint 工具、不改已审实现来追随不同版本。

## 外审独立复现

| 检查 | 外审结果 |
|---|---|
| 全套，合成 FRED key | 1444 passed，145.13 秒 |
| Governance | 8/8 OK，ibkr_readonly=true |
| 真实基线/候选迁移 verifier | PASS；v1 r1 路径 [1,2,2]，v1 r2 路径 [1,2,2,2] |
| 旧 writer 回滚 | 两组均 FAIL_CLOSED_WITHOUT_LEGACY_RESET，七产物 SHA 前后相同 |
| 四日期 strict payload + 七产物 | 4/4 equal，零 strict differences，比较器无改动 |
| 外部故障演练 | 13/13 passed，无网络、无 live 写入 |
| 全仓 Ruff severe | PASS |
| CI 四模块 + 身份两模块 mypy | PASS，6 files |
| 身份模块、测试、verifier 完整 Ruff 0.15.22 | PASS |
| pipeline 完整 Ruff | F401:42、F841:97 两项，与基线相同 |
| compile、diff --check、pip check | PASS，32 packages compatible |
| scoring_logic_hash | 与明确迁移映射中的 42d207d6b6c8… 一致 |

## 核心审阅结论

1. 随机 operation ID、完整 manifest 等观测差异不再消耗新的语义 revision；每次观测仍留证。
2. as_of 内 close/volume、soft 来源/可见性、实际动作、有效 config 和评分逻辑变化仍改变身份。
3. 修订预算仍为 2，未固定 UUID、取消 witness、修改 config/flag 或放宽比较器。
4. scheduled 回归确实使用独立进程和真实七产物事务，失败后完整恢复。
5. 保留 v1 外壳、另加 identity-v2，防止旧 writer 回滚时把新记录当 legacy 重建链。
6. v1 迁移要求完整证据；旧 ID/hash 可追溯，证据不足拒绝。
7. 审计全量流式读取；损坏、缺失但状态仍在等情况拒绝，不默默重启 r1。
8. 配置、阈值、路由、依赖 pins、密钥与 live 数据未变。

## 仍须守住的门槛

旧 v1 同 as_of 的完整 manifest 已变化时，本候选拒绝自动迁移。安装代码不保证解除已存在的 r2 阻断。
合入与推送不能代替只读迁移预检；预检也不能代替用户的单独部署批准。

获批部署仍须无 writer、避开北京 07:00-07:20、保留 live config，执行一次标准 R6；不得借部署人工补跑 official daily。

实施方流程澄清：完整周末/周一的自然新身份观察属于首次部署后的结案条件，不要求在首次部署前取得尚未运行的新版本样本。外审的部署 HOLD 保持不变。

身份投影保守、流式审计线性开销、审计与状态同时丢失无法重建、生产新身份尚无自然样本、代码字节指纹不自动豁免注释变化等残余风险仍保留。A1 未闭合前不启动生产 Phase B。
