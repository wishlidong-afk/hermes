# A2 3C 前置：证据锚点保留保护

日期：2026-10-03。仓库：`/Users/liweishi/Documents/github/hermes`，分支 `hermes-docs`，HEAD `68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 1. 判定与范围

**保留前置补丁已实现并验证，待外审；3C 真实入口尚未接线，A2 OPEN。未提交、推送、部署或访问 live。**

前一批 3B 仍待独立外审。本轮不越过这个 checkpoint 去修改 pipeline，而是补其交接中已经登记的前置缺口：COMMITTED journal 是最终输入清单的外部摘要锚点，不能在生产接线前仍允许既有数量/容量清理把锚点删掉。

本轮实现文件只有：

| 文件 | 内容 |
|---|---|
| `ops/prune_runtime_artifacts.py` | terminal v2、未知协议及带证据字段的 legacy 记录保护；计划和执行共用判定；manifest 拒收；容量报告 |
| `src/hermes_escape_top/tests/test_evidence_anchor_retention.py` | 21 项隔离测试，其中一项使用真实 v2 事务提交和最终绑定 |

文档：本文、`ops/README.md`、`docs/PRODUCTION_RUNBOOK.md`、3B 交接的时点回注。三份九月计划未动。

工作区仍累积此前 history_versions、decision_inputs、3A、3B 的未提交变更。**`git diff HEAD` 不等于本轮增量**，其中 prune 的 namespace/v2 active 兼容是上一批工作。3B 收尾 prune SHA 为 `8e6945706ceb3592f39b63127aa1c90173e97577d5b8b064b6790e1aee08b7cd`；该旧原文未另行保存，仅有历史哈希，不能凭此哈希宣称已经提供可逐行还原的增量基线。外审应审当前累积 prune 源码，同时区分本文列出的职责。

本轮未改 pipeline、事务实现、输入归档模块、identity/revision、评分/路由、config/flag、依赖、比较器或部署脚本。

## 2. 实现契约

### 2.1 暂时全保留，而非自动 GC

以下 terminal journal 不进入数量或容量删除集合：

- `schema_version=hermes-score-run-transaction-v2`：原因 `decision_input_evidence_anchor`。不要求输入 bundle 当前完整才保护；损坏证据也不得借清理自动消失。
- schema 既不是缺省 legacy，也不是已知 v1：原因 `unknown_transaction_protocol`。
- 缺省或 v1 标签下仍出现 `capture_id` / `input_binding` 键，或 artifacts 列表中有 `DECISION_INPUT_EVIDENCE` 角色：原因 `evidence_markers_on_legacy_record`。键值为 None 仍保护，不把字段缺值当成普通旧事务。

全部 v2 terminal 状态均保护，包括 `COMMITTED`、`ROLLED_BACK`、`RECOVERED_ROLLBACK`。后两者不被宣称为成功输入锚点，暂保留它们只是避免在完整证据 GC 尚未定义前过早删除诊断记录。

无证据标记的已知 v1 或缺省 legacy terminal 记录仍可清理。active 的旧保护机制、其他 release/backup/audit 类别及锁入口保留。

### 2.2 执行旧计划必须复查

计划生成与 `_validate_delete` 使用同一个保护判定。执行时重新读取当前 manifest，不信任旧计划的候选分类；已变为 v2 或不确定证据记录的目标以 `skipped` 保留。

专属用例先从 v1 fixture 生成删除计划，再把其 manifest 标签改成 v2，证明 apply 拒删；这是对旧计划边界的攻击性 fixture，**不声称正常生产 writer 会原地转换一个已提交 run 的协议**。

manifest 本身为链接（含断链）或不是 JSON object 时拒收。生成计划时跳过不可信记录，执行旧计划时记录拒收并不删除目录。腐坏 JSON 的跳过/拒删方向原已存在，本轮增加回归，不伪称为新修缺陷。journal namespace 和 run 目录链接沿用 3B 的保护。

### 2.3 容量必须说真话

`summary.score_transaction` 新增：

- `protection_reasons`：已解析 terminal 清单中按内容保护的路径及原因，不冒称包含所有 active-only 原因。
- `retained_bytes`：计划执行后会保留的、该已解析 terminal 清单中的字节数。
- `capacity_exceeded`：上述 retained_bytes 是否仍超过配置容量；受保护锚点不会因超限被强行删除。

这些不是全盘占用统计：pending、畸形/不可读/非 terminal 目录以及 bundle/history 版本不在这份字节统计内。主 APPLY 报告的 PASS 只表示允许的删除操作完成，**不表示容量达标或完整证据健康**。本批未新增通知、WebUI 或新的健康判定。

既有排序/数量选择算法未改：受保护记录仍在 terminal 清单中占排序名次，不是另给 v1 增加 50 个独立配额。容量计算也包含受保护 terminal 字节；必要时可以清理无保护 v1，但不能因此清理锚点。旧“数量/容量目标”并非所有受保护项都能容纳的硬上限。

## 3. TDD 和验证

逐项红转绿：真实 COMMITTED v2 在零保留/零容量下原会进入删除集合；旧计划原能删除后标为 v2 的记录；容量报告原无字段；未知协议原被当作旧 terminal；六种 legacy 标签/证据标记组合原可删；linked manifest 与 non-object manifest 的拒收缺口也先复现再修。断链的误报从 already_missing 改为明确 symlink 拒收。普通 v1 和 v2 rollback 组是正向补覆盖，不冒称旧代码有错误。

| 检查 | 结果 |
|---|---|
| 新测试文件 | 21 项；真实 v2 提交 1、legacy 证据标记 6、旧计划 1、未知协议 1、不可信 manifest 4、普通 v1 清理 6、v2 rollback 保留 2 |
| 六文件定点组合 | **159 passed，2.85s** |
| 全套 | **1686 passed，154.31s**（3B 收尾 1665 + 新增 21） |
| Governance | **8/8 OK，ibkr_readonly=true** |
| 本轮两个源/测试完整 Ruff | PASS（0.15.22） |
| 全仓 E9/F63/F7/F82 | PASS |
| prune mypy | PASS（2.3.0，1 file） |
| 两文件编译 | PASS，缓存转存 /tmp |

新用例全部写入 tmp_path。真实 v2 提交用例对 manifest 与两份证据文件保存字节，执行保留计划后逐个比较不变。它使用 3B 的业务 fixture，不是完整 scheduled pipeline，也不是自然线上样本。没有执行 live retention、daily、刷新或 IBKR。

### 3.1 证据时点与 SHA256

| 文件 | 当前 SHA256 |
|---|---|
| `ops/prune_runtime_artifacts.py`，446 行 | `7d52be95fe428a621c84f9ef8f2eec795ac7a8d5b49d5dbea82bb2d0764d6888` |
| `test_evidence_anchor_retention.py`，185 行 | `170392908b7fffb16c4431ea97595f3e826873de7ba4dfcc37214541342808b8` |

3B 两份 JSON 未重生成：equivalence `4ed4c08caed7fd357d5cfc24aaa9dc4a87769d9fe33ece3522da6e0dcce71b45`；legacy probe `c9714d069bcfb05ce14d059b86ab00a323f02d5c30d2d31d44bf32d98855fa19`。

直接读取 3B candidate source evidence，对其中 **197 个非测试 package 文件**逐个重算 SHA，全部与当前相同。评分指纹仍为 `9394490dd2db713f558080fc0239258f240ef82873c8731752f7095c8457ea66`。所以沿用该未变生产 package 的默认 v1 四日期 strict 证据；本轮**没有重跑比较器**，旧 351 文件 manifest 不代表新增测试后的完整当前树，也不覆盖 ops 脚本。prune 新行为由本批专属回归验证。

相对于 HEAD 的指纹依然已经因 3B 改变；不能把“本补丁指纹未再变”说成“A1 发布条件已满足”。不增加比较器忽略项、迁移豁免或修订预算。

## 4. 复现与外审

只在仓库测试隔离根操作，不对真实 live 运行任何入口。临时解释器不是永久承诺，外审可安装同 lock/dev 的兼容环境。

```sh
PY=/tmp/hermes-urllib3-tests-20261002/bin/python
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests/test_evidence_anchor_retention.py \
  src/hermes_escape_top/tests/test_runtime_retention.py \
  src/hermes_escape_top/tests/test_score_transaction_v2.py \
  src/hermes_escape_top/tests/test_transaction_v2_acceptance.py \
  src/hermes_escape_top/tests/test_morning_acceptance.py \
  src/hermes_escape_top/tests/test_ops_entrypoints.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  FRED_API_KEY=hermes-review-synthetic-key "$PY" scripts/check_governance_consistency.py
env RUFF_CACHE_DIR=/tmp/hermes-a2-anchor-audit-ruff "$PY" -m ruff check \
  ops/prune_runtime_artifacts.py src/hermes_escape_top/tests/test_evidence_anchor_retention.py
env RUFF_CACHE_DIR=/tmp/hermes-a2-anchor-audit-ruff "$PY" -m ruff check \
  src/hermes_escape_top scripts ops --select E9,F63,F7,F82
env MYPY_CACHE_DIR=/tmp/hermes-a2-anchor-audit-mypy "$PY" -m mypy \
  --ignore-missing-imports --follow-imports=skip ops/prune_runtime_artifacts.py
git diff --check
```

外审必答：

1. 全部 v2 terminal 是否同时抵御数量和容量删除，且在 apply 时重新检查？
2. 未知协议/证据字段缺值能否被当成普通 v1；保护是否不等于认证有效？
3. 链接、断链、非 object、坏 JSON 能否授权旧计划删除；原来已正确拒收的方向是否被误称新修复？
4. 无证据 v1 三种 terminal 状态是否仍可删，其他清理类别/共同锁是否未退化？
5. 容量数字的范围与 APPLY PASS 的含义是否如实，是否把“超限但保留”说成“硬容量已达标”？
6. 本轮增量与累积 HEAD diff 是否区分，源码 SHA 和旧 3B JSON 是否分时点，是否伪造最新四日期重跑？
7. 本轮是否未改 pipeline/事务/身份/配置/flag/预算，未碰 live，未把保留保护说成完整 A2？

分别给出代码正确性、提交/推送、部署/A2 闭合三个判定。本文和作者测试记录不构成独立外审批准。

## 5. 残余边界与下一步

- 这是临时全保留，不是引用计数 GC：尚未协调 audit 压缩归档、输入 bundle、历史版本和源码档案的生命周期；也不保证每份旧档案永久可重放。
- 主 schema/保护字段靠当前 journal 内容识别，不是签名或抵御同用户恶意重写的安全边界。不可读/畸形记录不进入删除清单，但本批不新增其巡检告警。
- 既有 active 指针异常读取、全盘容量观测、断电耐久等更广问题未在本补丁重新设计，不据此宣称所有 retention 故障都闭合。
- 3B 的旧 writer active guard、真实输入捕获缺失、完整非空状态重放缺失及 A1 发布证明限制仍然成立。

下一步先对 **3B + 本前置补丁**外审。之后才进入 3C 的冻结边界/入口设计，明确默认 OFF 是否接入以及 capture_pre_run_state 与 pending transaction 的衔接，不能删守卫硬接。生产接线前仍需完整引用保留政策、隔离全路径重放与发布证明。

## 6. 后续状态注记

用户继续推进后，仅新增了显式 v2 冻结前像导出原语，未做生产入口接线。保留补丁两份源码及本文此前的 1686 测试、351 文件旧对照引用仍是各自历史记录；最新全套为 1710、最新四日期候选清单为 353 文件。详见 [前像导出交接](2026-10-03_a2_transaction_before_images_handoff.md)。3B + 本保留补丁 + 新原语仍须联合外审，评分入口接线和部署门槛没有跳过。

## 7. 同日联合外审结论注记

2026-10-03 联合外审已覆盖本片及 3B/export 交互，结论 PASS；本文原“待独立外审/仍须联合外审”为当时时点记录，已被联合结论取代。原正文、历史 SHA 和旧测试记录不回写。来源见 [联合报告](2026-10-03_a2_joint_external_audit_report.md) 与 [澄清](2026-10-03_a2_joint_external_audit_clarification.md)。当前候选冻结，可按用户授权提交/推送；**DEPLOY HOLD，A2 OPEN，Phase B 不启动**。临时全保留仍不等于完整引用式 GC 或硬容量达标。
