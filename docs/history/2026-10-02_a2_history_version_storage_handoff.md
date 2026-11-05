# A2 第一切片：完整 canonical 版本保存与恢复

日期：2026-10-02，北京时间。基线：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。本文证据的候选：第一切片外审收尾时冻结的 343 文件集合，不是后续含第二切片的全部工作区。

## 结论与范围

**完成通用 backfill 晋升路径的完整新旧 canonical 字节留存、去重、事务恢复和离线恢复函数。A2 整体尚未闭合，不提交或部署。**

本批文件：

- `src/hermes_escape_top/core/reporting/history_versions.py`：新模块，136 行。
- `src/hermes_escape_top/scripts/backfill_history.py`：接线，保留原准入/合并/写入格式。
- `src/hermes_escape_top/tests/test_history_versions.py`：24 个测试用例（外审收尾新增 seal 失败回滚）。
- `building/reports/history_versions/2026-10-02/equivalence.json`：既有比较器生成证据。
- 本文。

三份九月未跟踪计划与本批无关。没有修改 pipeline、history_transaction、market_admission、witness、manifest、decision_identity/revision、config、flags、依赖、比较器或部署脚本。没有扩大指纹排除集。

这是证据维护，不是新因子或策略开关：执行 backfill 时默认随实际 canonical 写入记录版本。独立 CBOE/ExternalSourceRunner writer 尚未接入。不能将本切片描述为所有 canonical writer 已版本化。

## 已实现契约

1. `_write_history` 仍用同一 DataFrame、同一 CSV 序列化结果 stage canonical；版本记录器保存写入前完整文件与这份实际待晋升字节，不只保存重叠下载窗口。
2. SHA256 内容寻址，同字节只存一份；已有对象必须字节相等，否则拒绝晋升，不能静默覆盖。
3. 每次有文件写入的 backfill 保存唯一 batch 索引，绑定 transaction operation_id、symbol、filename、source_symbol、before/after SHA。
4. `CREATED/UNCHANGED/CHANGED` 仅描述完整文件字节是否变化；CHANGED 不宣称是历史日期修订，追加日期也可能改变完整文件。
5. blob 和索引都由原 HistoryPromotionTransaction stage/prepare/promote/commit；失败恢复同一边界，新对象删除，已被旧批次引用的对象保留。
6. 提交前新 blob 与索引置 0444，复用旧对象不改其字节；普通只读权限不是对同用户恶意操作的安全边界，恢复仍校验 SHA。
7. 恢复遇到仍 PREPARED/PROMOTING 的 journal 会拒绝；COMMITTED 或成功清理后的索引可读。缺对象、摘要损坏、角色/schema 不符、未知版本不回退到当前 CSV。
8. 恢复只写调用者明确指定的新文件，拒绝覆盖已有文件、符号链接以及当前 canonical/版本根内目标。调用者必须选择隔离目录；不是全机生产路径权限系统，也没有自动改 live 的入口。

## 目录与 manifest 边界

目录从解析后的 history 根推导：

```text
<history_parent>/.history_versions/<history_name>/
  blobs/<sha256>.csv
  batches/<batch_uuid>.json
```

live 标准布局若后续获准发布，将对应共享 data 根下的 `.history_versions/history`；本轮没有在那里创建文件。

初版试验将目录放在 history 内，真实 manifest 测试失败，证明会把非行情档案纳入输入。随后移到独立同级目录，保留原 manifest 行为；链接回指 history 的用例也先失败、修复后拒绝。没有通过添加 manifest/身份忽略项掩盖该问题。

索引角色是 `CANONICAL_FILE_VERSIONS_NOT_DECISION_BINDING`。`captured_at` 是档案捕获时间，`published_at=null`，不冒充提供方发布时间或决策可见时间。没有保存完整 HTTP 响应，也没有推断某个旧 bar 的经济修订原因。

## TDD 与验证

关键先失败后修复：

- 成功 backfill 后没有持久档案：原代码测试 1 failed，随后新旧完整字节恢复通过。
- blob 普通可写：0444 断言先失败，提交前封存后通过。
- 档案进入 manifest：先失败，移到同级目录后通过。
- 档案 symlink 回指 canonical：先失败，显式拒绝后通过。
- 错误 evidence_role 仍可恢复：先失败，角色校验后通过。

新增 24 用例另覆盖：完整旧/新字节、无变化去重、OHLC/adj_close/volume 分别变化、下载窗口以外日期、BTC、缺见证拒收、prepare/promote/seal/commit 故障、未提交恢复拒绝与启动回滚、缺对象/坏摘要/不存在的 before、目标覆盖拒绝。

| 检查 | 结果 |
|---|---|
| 新增版本测试 | 24 项通过（纳入外审收尾组合与全套） |
| test_history_versions.py + test_history_transaction.py + test_backfill_guard.py + test_market_recovery_evidence.py | 外审收尾 81 passed，1.75s；原批次为 80 passed，1.73s |
| 最终全套（外审收尾） | 1505 passed，149.43s；合成 FRED key、隔离 seed；原批次为 1504 passed，153.13s |
| Governance | 8/8 OK，ibkr_readonly=true |
| Ruff 新模块/新测试完整检查 | PASS |
| 全仓 Ruff E9/F63/F7/F82 | PASS |
| mypy 新模块 | PASS，无新增 ignore |
| git diff --check | PASS |
| 评分代码指纹 | 基线=候选，42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a |
| 既有四日期 strict 比较器 | all_equal=true，4/4 equal，strict_differences=[] |

曾为修正链接边界主动中断一次全套；中断结果不计为通过，上表是最终冻结源码的完整重跑。没有网络抓取、IBKR、官方 daily、全窗口 backtest/gate、提交或部署。

比较日期：2022-01-03、2022-01-25、2026-05-29、2026-06-04。基线用 `git archive HEAD` 导出到新临时目录，双方使用同一解释器及相同 seed 的独立副本。

**严格比较证明的是既有 manual 历史评分 payload 和七业务产物不变，不证明新增版本档案正确或 scheduled 连续认证。** 新档案用专属真实 backfill/事务测试核对；A1 scheduled 自然序列背景不冒充本批重新观测。

## 证据绑定

| 文件 | SHA256 |
|---|---|
| history_versions.py | 360e9647b18ffab64173e5c395e2d3b8470b8a681c40a8c383f4a381aa57ae78 |
| backfill_history.py | d07f3b05fc0754e52589b0f046949ad7a769a64b0cb3355a9301246c552f07d3 |
| test_history_versions.py | 10e98bf5d51978b584fc465fea92bcdd2c01892d031a3d7ff1b98f68e7a26aff |
| equivalence.json | d3517494fe573565043ebaf652fdbbb7e985fbdaa8533755192196a4a4f9b9d1 |

比较器 JSON 另外绑定 source/seed/python/comparator 证据。临时目录不是长期归档；外审应独立生成基线和隔离测试环境，不以作者 /tmp 文件存在为前提。

### 证据时点对账

1. 初版第一切片为 23 项，测试文件 SHA 为 `e1d7487d6f2484eafc176c8b28609ddcaf86352f8ece3bac50bbfbe24c9862a3`。此值仅说明初版，不是当前冻结源码哈希。
2. 第一切片外审收尾时修正错误提示、追加 seal 失败回滚用例，变成 24 项，测试 SHA 为上表 `10e98bf5…`。当时已更新本文、重跑全套 1505 项及四日期比较，并将归档 JSON 更新为上表 `d3517494…`；旧 JSON 未保留，不能宣称初版证据还可在该路径取得。
3. 第二切片之后工作区有 345 个比较器范围内文件。第一份 JSON 仍绑定收尾后的 343 文件，第二份 JSON 绑定 345 文件；它们的共同文件逐项相等，包括 seal 用例，差集仅是 `decision_inputs.py` 和 `test_decision_input_archive.py`。
4. 本次对账独立读取两份 JSON，并对当前文件逐个重算其记录的 SHA：343/345 集合均无哈希不匹配。343 集合证据不是整个后续工作区的证明，也未因两个新增文件而丧失对自身冻结集合的绑定。
5. 第二切片成文时的全工作区四日期证据见 `building/reports/decision_inputs/2026-10-02/equivalence.json`，当时全套为第二切片交接中已记录的 1534 项。本文 1505 项结果只对应第一切片收尾时点，不冒充最新全套。
6. 2026-10-03 3A 外审反馈后的回核：本文件当前表格已登记 `d3517494…`、24 项及 `10e98bf5…`，与磁盘重算一致，未复现反馈所指的旧 SHA/23 项登记。此前阅读版本的登记不应再作为当前核验表；也不据此断言旧 JSON 为什么或何时变化。第一切片 JSON 本次未重生成。当前累积工作区已含 3A 扩展，最新证据请见 `building/reports/pre_run_state/2026-10-03/equivalence.json` 及 `docs/history/2026-10-03_a2_pre_run_state_capture_handoff.md`（1606 全套、347 文件候选）；此回注不改变第一切片的历史判定。

## 外审收尾与提交边界

- F1：原 80 项数值有效，但 recovery 标签不明确。实际第四个文件是 `test_market_recovery_evidence.py`（11 项）；前三个文件原合计 69 项。现已列全文件名，增加 seal 用例后合计 81 项。
- F2：拒绝信息改为 `version archive cannot be the canonical history root or inside it`，精确覆盖相等和内部两种情况；判定逻辑未改。
- F3：实际调用顺序是 `promote → seal → mark_committed`，并不存在先提交再 seal 的路径。新增用例在真实 seal 完成之后抛错，验证 canonical 与版本档案字节全部恢复。promote 与 seal 之间崩溃时 journal 仍为 PROMOTING，启动恢复回滚。
- journal 的持久化 COMMITTED 是崩溃恢复的提交判据，不是索引文件存在与否。mark_committed 写入 COMMITTED 后再清理 journal；若此窗口崩溃，启动恢复保留已提交产物并清理 journal。清理异常进入现有异常处理可能尝试回滚；本切片没有修改该事务层，也未将“提交后异常”泛称为一定恢复。新增 seal 用例不证明清理失败或真实断电路径。
- 本次更新后的源码重新跑四日期 strict 比较，all_equal=true，七业务产物无差异；未修改比较器或忽略项。上表哈希与归档 JSON 已更新，不把外审原批次旧哈希证据冒充新源码绑定。

## 未完成与残余限制

- 尚无 decision_id → 全部实际输入版本的绑定。无写入/未抓取的符号不会生成本批 file 条目；不能只凭 batch_id 或 operation_id 猜测完整决策输入。
- 没有旧版本的历史日期不补造；没有按“最新目录”假装恢复当时输入。
- soft/config/代码与提供方原始 HTTP、精确发布/可见时间尚未进入该恢复契约；因此不能称完整决策重放完成或历史 PIT 已修。
- 股票删除日期/拆股等准入政策未改。adj_close 字节修订测试不等于真实企业行动事件验证。
- 新档案 I/O 失败会让本次 backfill 回滚，沿用 fail-closed 的可用性取舍。没有真实断电、磁盘满或并发恶意改链接演练；串行依赖现有调用方的锁纪律。
- 无自动 GC，内容变化可能长期占空间。恢复索引依赖对象存在；不能在未建立引用/保留政策前清理。
- 新 journal 增加版本根目标；旧 writer 的 allowed_roots 不认识该根，遇到未完成新 journal 会 fail-closed，不能宣称任意回滚都能自动恢复。未来部署/回滚前必须先确认 history journal 已恢复且为空，并单独演练。
- 只读文件与 SHA 是防误写/完整性工具，不是签名、全机权限边界或抗同用户篡改证明。
- 没有上线样本。本切片不是提交、发布或 Phase B 授权。

## 独立外审问题与命令

请审当前 working tree，不把本报告本身当正确性证据。重点逐条回答：

1. 原 CSV 字节、准入结果、payload、评分指纹是否未改？是否偷改排除集或 comparator？
2. 是否保存完整 canonical 文件，而非只有近期 bar？BTC 与旧窗口日期是否确实保留？
3. 新对象、共享对象、索引和 canonical 的失败/恢复是否一致？未提交索引是否被当作成功？
4. 版本根是否进入 manifest，symlink 回指是否可绕过？
5. 损坏/缺对象/错误 role/schema/before 不存在是否拒绝且无输出？
6. 恢复是否拒绝覆盖 canonical 与已有文件？是否诚实披露它不是全机安全隔离？
7. 四日期和七产物是否独立重跑？新档案是否有单独真实事务测试？
8. 是否把本切片、scheduled 自然观察、完整决策绑定、全部 writer 版本化混称完成？

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <PY> \
  scripts/check_governance_consistency.py
```

下一项：在此存储契约外审后，明确每次决策实际消费的全符号版本清单，并提供从 decision 到隔离输入、SHA 与 as_of 投影的核验；未写入符号、其他 canonical writer 和缺历史证据必须明确处理。不要先部署本切片再把它当完整 A2 结案。
