# A1 估值来源稳定性：交接与独立外审指南

日期：2026-09-07。实现始于 09-06，恢复后完成验证。

## 1. 范围与判定边界

用户已确认：修后续身份稳定性；旧 r2 证明不足继续拒绝，采用经验证的自然新决策日期过渡。

- 基线：`8fd18f28f4451a4e18c35c2f43a312df5396129b`。
- 候选：`/Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity`。
- 分支：`codex/a1-decision-identity`；送审时为未提交工作树改动。
- 原始审计范围：该工作树相对上述基线的改动，以及下面声明的新增文件。不是主目录旧提交范围。
- 唯一生产改动：`src/hermes_escape_top/core/data/decision_identity.py`。
- 新增测试：`src/hermes_escape_top/tests/test_valuation_decision_identity.py`。
- 新增文档：本文件，不属于实现证据。
- 主目录原有三份未跟踪计划文档不在本批范围内，未动。

**2026-09-07 用户转交的独立外审结论：代码合入 APPROVE、提交推送 APPROVE、部署 HOLD，详见 §9。代码层验证通过也不等于当前旧 v1/r2 能迁移，更不等于线上已恢复。**
送审阶段未提交或推送；外审后进入集成与 CI 验证阶段。部署仍须用户另行明确批准，
不运行生产 daily、不刷新行情/外部源、不连接 IBKR。

## 2. 问题与最小修复

旧 adapter 把找到估值文件的 release 绝对路径作为 source，SOFT 快照也包含此路径。
R6 的两个 release 可指向同一共享文件，却产生不同原始 input_hash；A1 原来的语义身份因此变化。

本批不改 adapter，不改原始记录或 input_hash。仅在语义投影层，对两个已验证的 R6 默认别名
将 source 投影为稳定共享文件路径：

| 当次 release 别名 | 唯一允许的共享目标 |
|---|---|
| `<live>/releases/<release>/data/valuation_snapshot.json` | `<live>/data/valuation_snapshot.json` |
| `<live>/releases/<release>/hermes_escape_top/data/valuation_snapshot.json` | `<live>/shared/hermes_escape_top/data/valuation_snapshot.json` |

识别要求：当前 package 的结构匹配；record.source 精确匹配当次默认路径；data 是符号链接；
目录和文件 strict resolve 均等于预期共享目标；文件存在、为普通文件且可打开。
断链、越界、文件级重定向、目录冒充文件或不可读时拒绝认证。

仅投影 `valuation` 记录 source，以及 SOFT 中来源匹配的 `valuation` 和实际存在的三个估值字段。
其它字段、未知字段、来源理由、可用性、数值和其它源 provenance 均保留。
自定义 `valuation.snapshot_path` 不归一化；未知路径不享受别名等价，保留原字面身份。
两个独立共享文件即使内容相同，也不判为同一来源。

稳定来源仍是这台机器上的真实共享路径，不承诺任意机器迁移等价。
这里的文件检查仅验证当前链接关系和可读性，不声明当时原始文件 SHA 或历史内容不变。
不新增事后读取的文件哈希来冒充评分输入字节证据。

## 3. 明确保留的守卫

- `decision_revision.py` 零改动，旧 v1 六项证明全部保留。
- `MAX_DECISION_REVISIONS=2` 不变；不删 audit/state，不改旧 ID/hash。
- 旧完整 manifest 变化仍是独立迁移障碍。
- scorer 指纹排除集和显式 release 映射未改。该身份文件原本就在认证文件排除集。
- 本次实算评分指纹仍为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`。
- config、flag、pipeline、评分/路由、adapter、比较器、依赖锁、部署脚本零改动。
- 同目录/同输入原始 payload 不被投影函数修改。跨目录的 raw source/input_hash 本来不同，仍然不同。
- 新生日期必须是新的决策 as_of，不能仅凭墙钟跨日、周末或假期认定新链。

## 4. 验证账本

| 项目 | 本轮实测 |
|---|---|
| 改前基线身份/序列测试 | 34 passed |
| TDD 首轮：真实 adapter + R6 两种目录布局 | 2 failed；仅 scored_snapshot_hash/soft_input_hash 不同，正确复现 |
| 首次修复 + 原身份测试 | 35 passed |
| 新增边界/旧链/新日期测试 | 25 passed |
| 最终 focused，含独立进程 scheduled 序列 | 59 passed / 13.98s |
| 精确 CI 四模块 + 两身份模块 mypy | PASS，6 source files，无新增 ignore/exclude |
| 全仓 Ruff severe | PASS |
| 改动源码和新测试完整 Ruff | PASS，工具版本 0.15.22 |
| 真实 v1 writer 的 r1/r2 迁移和旧 writer 回滚 | PASS，使用 git archive 提取的 25073bb 与最终候选 |
| 最终候选真实冻结种子 R6 演练 | PASS，六个独立评分进程；旧链仍拒绝 |
| 全套测试 | **1469 passed / 146.75s**，合成 FRED key 环境 |
| 治理 | **8/8 OK**，`ibkr_readonly=true` |
| 外部故障演练 | **13/13 PASS**，`network_used=false`、`live_data_touched=false` |
| 四日期 strict | **all_equal=true，4/4 equal，零 strict_differences** |
| Compile、diff --check | PASS |
| 依赖兼容性 | `uv pip check --python ...` PASS，32 packages；未安装或升级依赖 |

首次静态检查发现三项 Optional 类型收窄错误，已显式 `isinstance(valuation, Mapping)` 修正。
之后在新目录按最终源码重新跑整组 R6 演练，下面只引用最终证据。
此前 `a1-valuation-stability-2026-09-06/` 目录是中间验证，不能替代最终源码绑定。
测试解释器没有 pip 模块，首次 `python -m pip check` 因 `No module named pip` 无法执行；
改用已有 uv 对同一解释器做只读兼容检查，结果通过，没有为此修改环境。

四日期输入哈希，基线与候选逐个相同：

| as_of | 两侧 input_hash |
|---|---|
| 2022-01-03 | `fa264ec7978261883ad92b15a2f8c745ba4879d0bf014d347fbe50ccba99e592` |
| 2022-01-25 | `d6e8648aa6b990433024a14f984b31fa26ce6991288b4cf8e1647463438aa649` |
| 2026-05-29 | `bdbee206dfcbf3295c405e61ab8425be89190220daf2d0a75655dbbf50574ce3` |
| 2026-06-04 | `98198452eababfe4f1057564b2417f12bd42b1292d36a0c47f6c6df8ed856de3` |

## 5. 最终冻结数据演练

证据根：`/Users/liweishi/Documents/New project/a1-valuation-stability-final-2026-09-07/`。

- `verify.py`：本地演练工具，不部署；外审必须先读再运行。
- `seed_binding.json`：绑定 09-06 捕获的冻结输入和最终候选 Python 文件 SHA。
- `guard.json`：网络连接、live 读取、目录外写入均在实际尝试时被阻断。
- `RESULT.json`：汇总与逐证据 SHA，不是独立可信签名。
- `legacy_writer_regression.json`：实际旧 writer 的两种迁移序列及回滚产物 SHA。
- `STRICT_EQUIVALENCE.json`：四日期原始比较结果，契约 `strict`。
- `EXTERNAL_FAILURE_DRILL.json`：十三项故障演练结果。
- `private/`：权限 0700，含真实配置和账户相关状态，严禁提交或上传。

| 用例 | 结果及准确含义 |
|---|---|
| `legacy_refused.json` | 真实旧 `2026-09-04 / r2` 跨目录仍拒绝：`v1 migration: unchanged snapshot_hash not evidenced`；决策输出投影相同；七产物 SHA 恢复 |
| `new_date.json` | 完整保留旧 audit/state，以合成 `2026-09-11` 测新链机制，r1；不是 09-11 行情或自然运行证据 |
| `relocation.json` | 同合成日期切换第二个 R6 release；raw source/input_hash 改变，semantic_hash/decision_id/r1 不变 |
| `future_observation.json` | 只追加 as_of 之后的合成 BTC 行，并改变 manifest/operation ID；旧 CSV 字节前缀不变；仍 r1/同身份 |
| `material.json` | 实际被读入的估值百分位增加 1，正常升 r2 |
| `budget_refused.json` | 再增加 1，预算耗尽；七产物逐一恢复，原始错误保留 |

成功序列 `[1,1,1,2]`，两个拒绝用例均七产物恢复。每次使用独立进程；成功时 audit/state/返回体
decision_evidence 一致，旧 audit 是新 audit 的字节前缀；没有 active 残留，副本 receipt 不变。
六个评分进程的网络尝试数均为 0，`include_ibkr=False`。

注意：新日期测试刻意没有冒充新行情，沿用冻结行情及旧 admission，明确标记 `synthetic_date_only`。
它只证明身份/事务机制。**不证明新日期行情完整、策略可用、市场准入通过或线上恢复。**
外层 sandbox 禁止读取真实 `.hermes`，禁止网络，写入只允许该证据目录。
评分入口是私有数据根内的 `score_pipeline(run_type='scheduled')`，不是生产 daily 入口。

## 6. 外审复现步骤

先确认候选工作树范围，禁止对主目录或 live 执行修复。设置：

```bash
cd /Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src:src/hermes_escape_top/tests
export FRED_API_KEY=a1-synthetic-test-key
PY=/Users/liweishi/.hermes-v3/.venv/bin/python
TOOLS=/tmp/hermes-review-20260905.HWIKNg/tools/bin
OUT='/Users/liweishi/Documents/New project/a1-valuation-stability-final-2026-09-07'

git status --short --branch
git diff --check
git diff HEAD -- src/hermes_escape_top/core/data/decision_identity.py
"$PY" -m pytest src/hermes_escape_top/tests/test_valuation_decision_identity.py src/hermes_escape_top/tests/test_decision_revision.py src/hermes_escape_top/tests/test_scheduled_revision_sequence.py -q -p no:cacheprovider
"$PY" -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider
"$PY" scripts/check_governance_consistency.py
"$TOOLS/ruff" check src/hermes_escape_top scripts ops --select E9,F63,F7,F82
"$TOOLS/ruff" check src/hermes_escape_top/core/data/decision_identity.py src/hermes_escape_top/tests/test_valuation_decision_identity.py
"$TOOLS/mypy" --ignore-missing-imports --follow-imports=skip src/hermes_escape_top/core/data/market_witness.py src/hermes_escape_top/core/data/market_admission.py src/hermes_escape_top/core/backtest/formal_gate.py src/hermes_escape_top/web/health.py src/hermes_escape_top/core/data/decision_identity.py src/hermes_escape_top/core/data/decision_revision.py
```

工具环境若不存在，可新建隔离工具环境；不要向 live Python 安装或更新依赖。
完整 Ruff 结果绑定 0.15.22，mypy 版本 2.3.0。

四日期 strict 比较使用主目录 `8fd18f2` 对照本候选。比较器文件必须零 diff；每次使用新输出文件。
它检查完整归一化评分 payload 与七业务工件，没有新增忽略项。
该比较器默认 manual_rerun，不应声称它单独覆盖新增的 scheduled 别名路径；后者由 focused 和 R6 演练覆盖。

```bash
"$PY" scripts/compare_pipeline_persistence.py --baseline-source /Users/liweishi/Documents/github/hermes --candidate-source /Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity --seed-data src/hermes_escape_top/data --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 --python "$PY" --contract strict --output /tmp/a1-valuation-independent-strict.json
"$PY" ops/external_source_failure_drill.py --output /tmp/a1-valuation-independent-external-drill.json
"$PY" scripts/verify_decision_identity_migration.py --baseline-source "$OUT/baseline-25073bb" --candidate-source /Users/liweishi/Documents/github/hermes/.worktrees/a1-decision-identity --output /tmp/a1-valuation-independent-legacy-writer.json
```

真实种子复现必须先审核 `verify.py`、冻结种子 SHA 和源码复制范围，再把工具原样放到一个全新的
本地证据目录。依次执行 `prepare`、`run guard`、六个 `run <mode>`（按 MODES 顺序）、`summary`。
工具拒绝覆盖已有 private/case，不要删除现有证据以重跑。整个过程串行，每个评分为独立进程。
原始种子路径是之前捕获的私有目录，不会读当前 live；它不是可公开上传的测试数据。

## 7. 独立审阅问题

1. 是否仅 1 个生产文件变化？config/flag/预算/旧迁移验证/比较器是否均零 diff？
2. TDD 失败是否确由两个真实 R6 路径的来源字符串导致，而非 mock 替代待修函数？
3. 是否仅精确的当前 release 默认路径和已核实的目标获别名等价？是否存在按文件名猜来源？
4. 同字节不同目标、显式配置来源、未知源/字段、数值/来源变化是否仍区分？
5. 断链、越界、不可读是否拒绝？投影函数是否修改任何原始 payload 或 input_hash？
6. 旧 v1/r2 路径变化和完整 manifest 变化是否依然拒绝？真实旧链拒绝后七产物是否恢复？
7. 合成新日期是否完整保留旧 audit/state？是否不经迁移另建该日期正常 r1，并跨 release 重复稳定？
8. 评分新输入是否升 r2，第三次变化是否被拒绝？旧 writer 回滚是否不重置预算？
9. 证据是否绑定最终源码而非最初 35 测试时的版本？工具、输入、输出 SHA 是否逐个核对？
10. 是否明确区分“机制演练通过”“自然交易日期尚无样本”“旧链仍 HOLD”和“线上已修复”？

请分别给出：代码合入、提交推送、部署三个判定。不要用测试绿自动批准发布。

## 8. 发布前仍需处理的事项

09-07 09:11 的只读晨验报告：旧 live 仍 `25073bb`，官方 run 因 `2026-09-04: r2` 耗尽失败。
这是旧版本状态，本批没有部署。watchdog 的 `lag=0` 不能否定评分/认证失败。
报告中的 `GENERATOR_MISMATCH` 伴随当日 scheduled/audit/绑定报告缺失；不据此单独推断代码部署漂移。

- 外审通过、集成/CI 绿、用户明确批准后，才评估单次 R6 发布窗口。
- 不能为了消掉红色提示而重跑 official、清 audit/state 或扩大预算。
- 新旧切换须以真实新的 decision_as_of 和当时证据为准，不能预先承诺某个墙钟日期自动解阻。
- 保留 live config、同一把写锁、无 writer、避开 daily 时间窗口等已有发布纪律不变。
- 仍需新代码自然运行样本及完整周末/周一序列观察；A1 未闭合前不启动 Phase B。

残余限制：当前来源验证不是历史文件内容证明，也不是对同用户恶意并发改符号链接的独立安全边界；
依赖既有评分/部署串行纪律。固定全机共享路径是有意的保守身份，不是跨机器可移植资源 ID。

本补丁按当前 live 尚未启用 A1/v2 的事实，作为 A1 发布前修正。如果发布前发现其他环境已经用
原 A1/v2 建立了同日期身份，本批没有新增该身份版本的迁移豁免，应重新预检而不是假设可无缝替换。
作者已逐行复核差异与上述证据；这不替代独立外审。

## 9. 独立外审结论与集成边界

来源：用户于 2026-09-07 在本任务转交的《外审报告：A1 估值来源稳定性》。
下面是该报告的结论摘录，不把审计员的复现当作本轮作者新跑的结果，也不替代底层证据。

- P0/P1/P2 无；无新增 P3；§8 的残余限制逐项确认属实。
- 范围一致：唯一生产改动仍为 `decision_identity.py`，另有新增测试和本交接文档。
- 外审独立复现：59 focused、1469 全套、8/8 治理、严格四日期等价、13/13 故障演练、
  旧 writer 迁移/回滚及全新冻结目录的六模式 R6 演练全部通过。
- 外审确认来源别名仅限两个已验证默认链接；未知/自定义来源仍参与身份；
  原始 payload/input_hash、旧 v1 证明、修订预算及回滚守卫均未放宽。
- 三个独立判定：**合入 APPROVE；提交推送 APPROVE；部署 HOLD**。

集成前作者复核：主目录和候选 HEAD 均为 `8fd18f2`，两条远端分支亦一致；
候选生产文件 SHA256 为 `0765fe3c23a37a998f6addb91db62930f56689837a8c532b14eebe3a565f39a5`，
与最终冻结证据相同。重新运行 focused 为 **59 passed / 14.06s**。
本节仅补记外审状态，不改变送审后的生产代码或测试。

本轮只允许提交声明的三个文件、快进合入 `hermes-docs`、推送并检查精确提交的 CI。
保留候选工作树供后续复核，主目录三份原有未跟踪计划文档不纳入提交。
提交推送成功不自动解除部署 HOLD；后续必须重新核对自然新决策日期过渡条件，
取得用户明确部署批准，并遵守 §8。不得为清除旧 r2 阻断而补跑 official 或改写历史。

## 10. 09-08 集成前续验

隔夜重新核对：两棵树和两条远端分支仍为 `8fd18f2`，没有新的范围外改动；
生产文件 SHA256 仍与 §9 相同。串行重跑结果：

- 全套 **1469 passed / 156.51s**，合成 FRED key，隔离测试数据。
- 治理 **8/8 OK**；Ruff severe、改动文件完整 Ruff、六模块 mypy、compile、diff --check 均 PASS。
- 依赖兼容检查 **32 packages compatible**，未安装或升级依赖。

只读引用 09-08 09:11:27 已生成的 morning acceptance：live 仍 `25073bb`；
总体、runtime_integrity、strategy_decision 均 FAIL。核心错误仍是
`DecisionRevisionConflict: same-date decision revision budget exhausted for 2026-09-04: r2`。
scheduled receipt 为 FAILED、当日 scheduled audit 为 0、事务项为 `audit persistence evidence missing`；
不能据缺少本次成功证据推断历史产物损坏。watchdog 虽 PASS/lag=0，不能否定评分失败。

市场准入连续 OK 为 2/3 最低门槛，目标仍为五日；这不是新代码的自然运行样本。
报告未单列 Dollar/IBKR 的当前分项，本次不借用旧日 WARN/INFO 断言今天状态。
本轮没有运行 acceptance 脚本、daily 或刷新操作，只读取已生成报告。

**集成及 CI 是本轮完成目标；部署和 A1 闭合不是。**
沙箱新日期及跨 release 演练只证明机制；真实新 decision_as_of 过渡、用户部署批准、
部署后自然运行和完整周末/周一观察仍各自待完成，不能以测试通过替代。
