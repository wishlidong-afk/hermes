# A2 第二切片：离线决策输入绑定与恢复

日期：2026-10-02。基线 HEAD：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 判定与范围

完成显式调用的离线工具，绑定已有 v2 scheduled 决策与可核验的行情、已消费快照/soft records、完整配置及代码指纹。**没有接入生产 pipeline，没有完成自动归档、全状态重放或整个 A2；不得据本批部署。**

本轮新增：

- `src/hermes_escape_top/core/reporting/decision_inputs.py`：213 行，两个公共 API。
- `src/hermes_escape_top/tests/test_decision_input_archive.py`：29 个用例。
- `building/reports/decision_inputs/2026-10-02/equivalence.json`：未修改的比较器生成证据。
- 本文。

工作区另有尚未提交的第一切片（history_versions、backfill 接线、测试、文档和证据），不将它们隐瞒为干净 HEAD。第一切片初审后、第二切片开始前，已经追加 seal 用例（23→24），修正错误提示，并刷新第一份文档与证据；详见第一切片交接的“证据时点对账”。第二切片实现期间未再修改这些源码或测试。本次二次外审对账补充两份文档，不修改实现。三份九月计划文档仍与本批无关；pipeline、identity/revision、scoring、routing、config/flag、事务核心、部署脚本、依赖或比较器均未改。

## 实现契约

### 归档

`archive_decision_inputs(payload, config, store=..., package_root=..., destination=...)` 返回 manifest 路径、SHA256 与 decision_id。

1. 只接受有 v2 身份的 scheduled payload。验证原 snapshot/input_hash、完整 config_hash、soft_input_evidence_hash，以及现有 revision 分配器的身份/迁移/预算一致性约束；不分配新修订，不写 audit/state。
2. 以证据中的 history_hashes 为清单，从显式传入的 LocalStore 获取每个符号的完整原始 CSV，包括未更新标的、primary 和 legacy。重复或不安全文件名拒绝。
3. 将冻结字节交回既有 LocalStore 解析，再用未修改的 semantic_identity 核对完整身份。某个必要历史文件已缺失/已实质修订时拒绝，不拿当前文件冒充原输入。
4. 显式 `history_hash=None` 的既有证据可保留缺失；必要文件消失不能被转换成 None。普通 pipeline 对缺失文件返回空 RangeIndex DataFrame，现有身份层不能认证该形态；本工具不修改身份层去放宽它，也不宣称覆盖该生产路径。
5. 保存完整 payload（包含已消费快照与 soft records）及原始配置。提供方原始 HTTP/文件、精确 vintage、全部运行前状态、代码本体没有进入此契约；代码只保存指纹。
6. 使用独立临时目录写完后 rename 到调用者指定的新目录。普通写入/发布异常清理临时目录，无部分最终 bundle。拒绝已有目标、符号链接目标及 history/legacy/package 源根内目标。

### 恢复

`restore_decision_inputs(manifest_path, expected_manifest_sha256=..., decision_id=..., destination=..., package_root=...)` 返回新隔离目录。

1. manifest SHA 必须由调用者从可信外部收据取得，不能从 bundle 自己提取一个新 SHA 就宣称真实性。SHA 是绑定和完整性证据，不是签名。
2. 验证 schema/role/capture_mode、decision_id/as_of/semantic_hash、payload/config 摘要、v2 证据自洽、完整符号集合以及可用代码指纹。缺匹配源码不能假装可重放。
3. 只读取 bundle 中的精确白名单相对路径。文件缺失、摘要错误、越界路径，以及 manifest 本身、直接 bundle 根、blob 及其直接父目录的 symlink 均拒绝，不回退到当前 CSV。不逐层检查 bundle 根以上的祖先目录；经祖先目录链接访问相同且外部摘要匹配的 bundle 可以通过。这不是全机链接安全边界，真实性依赖可信外部摘要，而非路径字面形式。
4. 恢复字节经既有 LocalStore 解析，逐符号重算 as_of 历史投影。None 只按既有显式缺失证据保留。
5. 除当前解析出的源根，额外保护归档时记录的两个绝对数据根，避免 HERMES_DATA_DIR 切换后写入旧 canonical。
6. 输出 `history/*.csv`、`payload.json`、`config.evidence.json`、`original_manifest.json`。**config.evidence.json 保留原路径，只是证据，不是可直接交给 pipeline 的运行配置。** 本函数不评分、不抓行情、不连接 IBKR、不提交官方记录。

## 观察、身份与重放的区别

- 每个 bundle 标注 `capture_mode=RETROSPECTIVE_AS_OF_MATCH`，保存捕获时间与当时 source locations。它证明保存的输入投影与该证据匹配，不证明整份原始文件在官方评分时就是这些字节。
- 例如 BTC 的未来尾部改变，但 as_of 内行没有改变，现有身份仍一致。允许保存新的完整文件，不能将该观察称为“找到了评分当时的原始完整 CSV”。测试明确锁定这个边界。
- 可以从第一切片的不可变版本先恢复旧文件到隔离 seed，再用本工具核验并绑定旧决策；无需写回当前 canonical。此链路有真实事务测试。
- 校验已有 snapshot/soft 输入与恢复行情，不代表重新请求提供方可得到同一数据，不代表 PIT 政策已迁移。
- 真实集成用例在全新测试数据根调用现有 scheduled score（禁网络、include_ibkr=False），归档/恢复后用已消费 snapshots、恢复行情和既有 score_symbol 重算三标的完整评分，结果相等。它**不是**恢复运行前 reentry/signal journal/previous statuses 后的全 pipeline、路由与七产物重放。

## 测试过程与结果

明确观察到的红转绿：

- 首个完整符号归档用例：最初没有 manifest，随后实现并通过。
- 原始 CSV 被改坏后的恢复：最初没有恢复文件，随后实现并通过。
- 切换数据根后恢复到原 canonical：最初没有拒绝，新增捕获根保护后拒绝。

其余拒绝面和组合用例检验已实现契约，不宣称每个负向用例都单独红转绿。

| 检查 | 结果 |
|---|---|
| 第一+第二切片组合 | 53 passed，4.33s（24 + 29） |
| 全套 | 1534 passed，154.27s；合成 FRED key、隔离 seed |
| Governance | 8/8 OK，ibkr_readonly=true |
| Ruff 新模块/测试完整检查 | PASS |
| 全仓 E9/F63/F7/F82 | PASS |
| mypy 新模块 | PASS，无 ignore |
| 四日期 strict | all_equal=true，既有七业务产物与评分相等 |
| 评分指纹 | 42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a，与基线一致 |

严格比较的日期为 2022-01-03、2022-01-25、2026-05-29、2026-06-04；基线从 HEAD 导出，候选含当前两切片。比较器未改、无新增忽略项。它证明原评分路径不变，不证明新增 bundle 正确；新增 bundle 用独立真实事务/恢复测试检验。

| 文件 | SHA256 |
|---|---|
| decision_inputs.py | e73a3f9a5f772bf50a4af235ac243161f51a9a659adb3ec1bf4b80415829cd05 |
| test_decision_input_archive.py | baad0738126b6df1b526f7c993bd26bbf0c4b17a807d63c9d56a49b7eda6ed96 |
| equivalence.json | 5da62a094665d31741729ed1de11932ac59332d1d89e96117a5c0ccf1f9e571e |

### 2026-10-03 后续切片回注

上表与“213 行、两个公共 API”描述只对应第二切片冻结时点。3A 后续扩展了同一模块：当前为 430 行，SHA `f98010bbd68e2f53f184ecd933cc7aa6f0895fdbfdab5b4883b0734fcbbd0bb5`，另增两个显式离线 pre-state API，仍无生产调用方。第二切片测试及归档 JSON 未改；不能用上表旧模块 SHA 验证当前源文件，也不能把旧 345 文件集合说成当前全部工作区。最新 347 文件集合、1606 全套和四日期 strict 证据见 `docs/history/2026-10-03_a2_pre_run_state_capture_handoff.md`。本次只回注文档，不覆盖两份旧 JSON 或改写原外审结论。

## 二次外审对账

- 第一份交接当前已是 24 项、`10e98bf5…` 测试哈希，不再是初版 23 项/`e1d7487d…`。为避免混用时点，第一份交接已明确记录初版→首审收尾→第二切片的时间线。两个 JSON 的基线集合相同；候选 343/345 共有文件完全一致，新增两文件恰为本轮模块与测试；逐个当前文件 SHA 重算均匹配。保留原证据，不为更新两个文档伪造或覆盖跑批 JSON。
- 用例计数重新通过 pytest collect 和实际运行核验：`test_history_versions.py` 为 24，`test_decision_input_archive.py` 为 29，合计 **53**；本次组合实跑 `53 passed，5.39s`。24+29=53，不采用外审中的 54 建议。上表 4.33s 是第二切片原跑批耗时，不是本次耗时。
- 单独临时探针验证：直接 bundle 根 symlink 被拒绝且无输出；仅更上级祖先目录为 symlink、各文件及外部 SHA 均一致时可以恢复。文档按该实际边界精确描述，不宣称对祖先链接或同用户恶意替换提供额外防护。
- 本次仅补充文档；未改生产代码、测试或归档 JSON。沿用未变实现的 1534 全套、治理、静态和 strict 证据；没有声称本次重新运行全套，也没有提交、推送或部署。

## 外审必答

请审当前工作区，区分第一切片已外审的实现与本轮新增模块，不把文档或比较器 JSON 自身当独立证明。

1. 是否确实没有生产调用方、没有修改身份/指纹排除集或评分路径？
2. 清单是否覆盖所有已认证 snapshot 符号，而不只覆盖本次 backfill 写入者？必要文件缺失能否变成“正常缺失”绕过？
3. 有实质历史改动、config/soft/code/as_of 变化时能否错误绑定旧决策？未来尾部观察是否诚实标注？
4. 外部 manifest anchor、所有摘要、精确相对路径、symlink、完整符号集合是否均有拒绝验证？
5. HERMES_DATA_DIR 切换后是否仍保护归档时原 canonical？目标已有或悬空 symlink 是否拒绝？
6. 发布失败是否无部分 bundle、无 source/audit/state 改动？是否未夸大为断电耐久事务？
7. 两切片串联测试是否恢复旧输入而不覆写当前 CSV？真实三标的评分是否只使用恢复行情与存档输入？
8. 是否清楚区分字节绑定、语义核验、全状态重放、生产接线、自然观察和完整 A2？

复核命令（选择独立同依赖环境）：

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests/test_decision_input_archive.py \
  src/hermes_escape_top/tests/test_history_versions.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <PY> \
  scripts/check_governance_consistency.py
```

## 尚未完成与安全边界

- 无生产评分事务自动绑定；没有新增生产 hook、CLI/Web 按钮或 flag。仅有两个可显式调用的离线 API，不能称已有 live 决策自动获得恢复档案。
- payload 的 v2 证据自洽不等于来源真实；调用者仍须选取可信审计记录并保留外部 manifest SHA 收据。未自动绑定 live audit/COMMITTED journal 的真实性。
- 不自动遍历所有第一切片批次为旧 decision 猜文件。证据缺失不能补造历史；未证明确切旧输入时继续拒绝。
- 没有代码内容归档、完整运行前 state/IBKR 输入、提供方原始文件归档或精确发布日期补齐，因此尚不能保证整个策略路径可历史重放。
- config/payload 可能含凭证、账户或持仓信息，完整保留不能当公开报告上传 GitHub。bundle 临时根及发布根 0700、文件 0400；这些不是加密、签名或同用户恶意代码的安全边界。
- 捕获/发布依赖调用者在隔离环境串行操作；rename 发布处理普通异常，不是现有 score/history journal 的一部分。未做 kill-9、断电、磁盘满、并发符号链接攻击演练，未增加父目录 fsync 的耐久保证。
- 当前目录 API 没有跨 bundle 去重与 GC，内容寻址去重仍只在第一切片。未扩展所有 canonical writer。
- 未提交/推送/部署、未运行 live daily/外部刷新/IBKR。没有自然线上样本；A2 未闭合，Phase B 不启动。

下一项先独立外审本轮离线契约，再设计评分事务内的自动绑定与运行前状态捕获；该接线会影响评分指纹/A1 发布证明，必须单独处理，不能悄悄加进本切片。
