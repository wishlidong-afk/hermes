# A1 稳定决策身份：实施交接与独立外审指南

日期：2026-09-05（北京时间）。本文件不是外审通过报告，也不是部署授权。

## 1. 审计范围与当前状态

- 基线：`25073bbd6bf79797e53f78492974f5a6ebacc207`，主目录 `/Users/liweishi/Documents/github/hermes`。
- 候选：`/Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity`，分支 `codex/a1-decision-identity`。
- 审计范围是候选工作树的 `git diff HEAD` **加全部新增文件**，不是主目录的 diff。
- 本批只做 A1。未改 live、没有运行生产 daily/刷新、没有连接 IBKR、没有 commit/push/deploy。
- A2 原始历史版本档案、Phase B 来源/数据根治理、WebUI、评分阈值和路由均不在本批。
- 状态：实现与离线验证完成；独立外审和发布准入未完成。

### 实现文件

| 文件（相对候选根） | 改动 |
|---|---|
| `src/hermes_escape_top/core/data/decision_identity.py` | 新增决策输入投影、实际历史截面、有效配置和代码指纹 |
| `src/hermes_escape_top/core/data/decision_revision.py` | 分离身份与观测，旧身份迁移，保留修订预算，严格读取旧链 |
| `src/hermes_escape_top/pipeline.py` | 仅一行：向认证函数传入已经计算并按 as_of 截断的 histories |
| `src/hermes_escape_top/tests/test_decision_revision.py` | 语义、迁移、消费者、审计损坏与预算回归 |
| `src/hermes_escape_top/tests/test_scheduled_revision_sequence.py` | 独立进程真实 scheduled 事务及七产物恢复测试；附离线 worker |
| `scripts/verify_decision_identity_migration.py` | 用真实基线/候选代码验证跨版本迁移和回滚拒绝，不连接外部服务 |

本文件与 `building/reports/a1_decision_identity/` 的 JSON 是说明和生成证据，不是独立正确性证明。

## 2. 已确认的原始缺陷与修复

旧身份把随机 admission operation ID、完整目录 manifest 和决策输入混在一个 hash 中。
同一 as_of，周六 r1、周日 r2，周一即使实际输入不变也可能报：

```text
same-date decision revision budget exhausted for 2026-08-28: r2
```

TDD 首次实跑：原 7 项测试加控制组通过；operation_id 和未来 BTC 两个反例均因上面的预算异常失败（8 passed / 2 failed）。
另外把真实 scheduled 序列测试指向未修改的基线源码再次运行，旧版同样在第三次事务抛预算异常；不是仅证明新测试能走通。

### 新身份契约

1. `semantic_identity` 包含 as_of、评分快照投影、各标的 as_of 内历史 hash、决策 soft 输入、有效 config、评分逻辑指纹、已计算的评分/路由/再入场等结果 hash。
2. histories 来自 pipeline 的实际 snapshot universe，不维护第二张 symbol 表。每帧再截断 `index <= as_of`，保留行、列、缺失值和数值；未来 BTC 行不会进入身份。
3. soft 的角色与启用状态复用现有 `source_relevance`。研究/未启用记录不进入语义投影；未知记录保守处理。只移除已知抓取时间键，发布时间、来源、可见性及未知字段仍保留。
4. 顶层 `_...` 说明、`web` 和 `paths` 不进入有效 config hash。runtime、IBKR 配置及其他未知配置仍保守纳入；本批没有修改这些配置。
5. 代码指纹排除 tests/Web/scripts/research/reporting 和身份认证本身，其余 Python 文件逐个绑定。它是保守的代码指纹，不承诺核心源码注释变化也能自动识别为等价。
6. 完整 manifest、原始 `input_hash`、完整 soft/config/policy hash、release、operation ID、completed_through、认证时间仍写在每次观测中。既有 manifest/admission 校验没有变弱。
7. `decision_outputs_hash` 绑定已经算出的实际决策，用于捕获同快照但状态驱动动作不同的情况，不再次评分。它不包含运行 ID、数据库路径或落盘回执。

这是保守输入集合，尚不是每个因子最小历史窗口分析。A2 的可重建历史版本档案尚未实现，不得把本次 history hash 误称为“旧原始数据已完整归档”。

## 3. 修订、迁移和回滚契约

### 外层格式不变，身份算法单独版本化

```text
schema_version = hermes-decision-certification-v1
identity_schema_version = hermes-decision-identity-v2
MAX_DECISION_REVISIONS = 2
```

原因：实际旧版 allocator 把所有未知外层 schema 当成未认证 legacy。直接写 v2 外壳会使回滚后的旧 writer 重建 r2，绕过链条。因此保留它能识别的外壳，在新字段中明确区分新算法。

- 相同语义、相同 finality：沿用 revision、decision ID、supersedes 和首次修订原因。
- PROVISIONAL -> FINAL：仍消耗一次修订；没有把所有日期强制标 FINAL。
- 第三次真实语义变化：继续拒绝，事务回滚。
- 当前 finality 的周六规则未改；源最终定稿日历属于单独政策迁移。

### 旧 v1 的证明要求

旧记录没有 as_of 历史截面，不能用今天的数据编造其历史 hash。仅当以下条件均满足才关联：

- 旧审计 payload SHA、原 v1 identity SHA 和 decision ID 可验证；
- raw snapshots、完整 soft 证据、完整 manifest、完整 config、policy 与当前观测一致；
- 实际决策结果投影一致；
- 发布来源在明确的 `25073bb -> 本候选 scoring_logic_hash` 映射内。未知旧 release 或后来改动评分逻辑时不自动豁免。

旧 r2 等价重核验保留原 `decision_hash` 与 ID，新增 `semantic_hash` 和完整迁移引用；后续按 semantic hash 分配修订，原 hash 继续服务现有 report/overlay 消费者。
旧 r1 在 finality 推进时生成 r2 并引用原 ID。旧审计从不原地修改。

### 必须明确的发布限制

**旧 v1 同日期的完整 manifest 已变化时，本候选拒绝自动迁移，包括仅未来数据追加的情况。**
这是旧证据粒度不足造成的迁移限制，不是新 v2 日常重跑规则。不能声称安装代码就会解除已有同日 r2 阻断。

部署前必须单独取证：当前 as_of、revision、完整 manifest、发布证明是否满足过渡条件。
不满足时等待自然新决策日期，或先补充经外审认可的历史版本证明；不得删除审计、加预算、手动补跑 official 或伪造旧 hash。

回滚到旧 writer 可读取新外壳并保留预算守卫，但不保证它能在同一日期继续认证。真实回滚测试结果为 **fail closed，七产物不变**，不是“回滚后旧 writer 可以无条件正常续跑”。

## 4. 验证矩阵

| 检查 | 结果 |
|---|---|
| 改前两个 helper 反例 | 2 个预期 FAIL，均为 revision budget exhausted |
| 新 scheduled 测试指向真实旧源码 | 预期 FAIL，第三次真实事务耗尽预算 |
| 初轮定点组合 | 51 passed（随后增加回滚外壳守卫） |
| 最终身份+scheduled focused | 34 passed |
| 最终全套，导出合成 FRED key | **1444 passed / 145.02s** |
| 治理 | **8/8 OK**，未修改治理基线来放行 |
| 四日期 strict payload + 七产物 | `all_equal=true`，2022-01-03 / 2022-01-25 / 2026-05-29 / 2026-06-04；各 7 产物，strict differences 均为 0 |
| 真实 v1 r1/r2 -> 新身份 -> 旧 writer 回滚 | `REAL_V1_MIGRATION.json`，两组 PASS；回滚明确拒绝且七产物 SHA 不变 |
| 外部故障演练 | **13/13 PASS**，network_used=false，live_data_touched=false |
| 全仓 Ruff severe | **PASS**，E9/F63/F7/F82 |
| 精确 CI mypy + 两个身份模块 | **PASS**，6 files，零 ignore/exclude 新增 |
| 身份模块、测试和迁移 verifier 完整 Ruff | **PASS** |
| pipeline.py 完整 Ruff | **2 个基线原有 finding**：F401 第42行、F841 第97行；基线/候选结果相同，未清理无关代码 |
| 编译 / diff --check | **PASS**；编译缓存位于临时目录 |
| 环境依赖兼容 | **PASS**，32 packages compatible；未安装或改动生产 venv |
| 硬编码迁移指纹对照 | **MATCH**，候选 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a` |

工具：测试 Python 3.11.15；独立工具环境 Ruff 0.15.22 / mypy 2.3.0。
“全部静态检查零问题”不是本批结论：严重安全检查和类型检查通过，但上面两项 pipeline 非严重 lint 仍在。

生成证据相对候选根：

- `building/reports/a1_decision_identity/FOUR_DATE_STRICT_EQUIVALENCE.json`
- `building/reports/a1_decision_identity/REAL_V1_MIGRATION.json`
- `building/reports/a1_decision_identity/EXTERNAL_FAILURE_DRILL.json`

真实 scheduled 测试：2026-05-29 决策，模拟北京 05-30、05-31、06-01、06-02 四个早晨；每次独立进程、相同隔离数据根、不同真实 session ID、追加未来 BTC，得到 `[1,2,2,2]`。
四个成功 run 各有 COMMITTED / 7 artifacts，state 与 audit 中身份一致，audit 正好四条。
随后改 as_of 内真实 BTC close，认证失败，四个 SQLite、两个 JSONL、一个 dated soft snapshot 的文件 SHA 全部恢复。
网络连接被 worker 显式禁止，`include_ibkr=False`。原有各持久化 checkpoint 故障恢复测试也全绿。

strict 比较器未更改，也没有添加忽略字段。它仍是 manual 路径的全 normalized payload、表结构/行/值、JSONL 顺序与七业务产物对比。
原有时间戳、临时路径、随机事务 envelope 和时间戳派生 audit payload_hash 的归一化契约不变。
新 scheduled 行的认证字段本就有意改变，不能用 manual 的 all_equal 代替 scheduled 序列证明。

## 5. 外审执行方法

请在候选工作树检查，不要审错主目录。先确认基线源码仍是 `25073bb`、生产文件无额外修改；否则另建该 commit 的只读基线 worktree。

```bash
git status --short
git diff --check
git diff HEAD -- src/hermes_escape_top/core/data/decision_revision.py src/hermes_escape_top/pipeline.py
git ls-files --others --exclude-standard

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests FRED_API_KEY=a1-synthetic-test-key /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/liweishi/.hermes-v3/.venv/bin/python scripts/check_governance_consistency.py

PYTHONDONTWRITEBYTECODE=1 /Users/liweishi/.hermes-v3/.venv/bin/python scripts/verify_decision_identity_migration.py --baseline-source /Users/liweishi/Documents/github/hermes --candidate-source /Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity --output /tmp/a1-independent-migration.json

PYTHONDONTWRITEBYTECODE=1 /Users/liweishi/.hermes-v3/.venv/bin/python scripts/compare_pipeline_persistence.py --baseline-source /Users/liweishi/Documents/github/hermes --candidate-source /Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity --seed-data src/hermes_escape_top/data --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 --python /Users/liweishi/.hermes-v3/.venv/bin/python --contract strict --output /tmp/a1-independent-strict.json
```

一次一个验证进程，不运行全窗口回测。迁移 verifier 使用普通 Python 模式（不加 `-O`），依赖既有测试 fixtures 和 worker。先审 verifier，再相信生成的 JSON；每次运行都是全新临时根，不复用作者留下的数据库。

### 必须逐项回答

1. operation ID 和未来 BTC 两个独立变量都不再消耗新语义 revision 吗？观测差异是否仍可见？
2. 历史 close/volume、soft 来源/可见性、实际动作、有效配置和逻辑变化是否仍改变身份？
3. 是否扩大 budget、固定 UUID、取消 witness、修改 config/flag 或给比较器加忽略项？
4. scheduled 测试是否真的进入独立进程的评分事务，并核对失败前后七产物？
5. v1 r1/r2 是否可追溯，旧 ID/旧 hash 的消费者绑定是否明确？未知/不足证据是否拒绝？
6. 旧 writer 回滚后是否仍识别预算，还是把新记录当 legacy 重置？
7. 乱序、损坏、缺失和超过旧 64 MiB 窗口的审计是否可能静默从 r1 开始？
8. 是否过度宣称“任意旧链都可迁移”“部署马上解除旧冲突”或“原始历史版本已归档”？
9. scoring fingerprint 的排除集合和硬编码迁移映射是否与本批实际 diff/独立等价性证据一致？
10. 全套、治理、静态、drill 和四日期 strict 是否可独立复现？

请分别给出代码合入、提交推送、部署三个判定，不把“代码 PASS”自动提升为“当前 live 状态可以部署”。

## 6. 发布门槛与剩余观察

本轮未执行下面任何生产步骤：

- 独立外审通过；主目录集成、提交推送、CI 绿；
- 只读检查旧链迁移条件或自然新 as_of 过渡条件；
- 用户明确批准后，无 writer、避开北京 07:00-07:20、保留 live config，单次 R6；
- 不通过部署手动重跑 official daily；
- 自然观察完整周末/周一同 as_of 序列与 finality 推进，核对官方 audit 次数、七产物、health/report 绑定和独立晨检；
- A1 未闭合之前不启动生产 Phase B 迁移。

剩余局限：身份投影保守、审计查询改为流式全读（增加线性读取开销）、同时失去审计与状态的历史无法凭空恢复、实际生产新身份尚无自然运行样本。上述限制不得隐藏在全套测试绿的结论后面。
