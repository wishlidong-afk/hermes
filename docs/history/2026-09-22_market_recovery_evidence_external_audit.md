# 行情隔离后恢复证据：实施交接与独立外审指南

日期：2026-09-22。基线：`388de1654c7677984a4e5b9d539bf4ed45d6d837`。
候选：主工作区未提交变更；不是其他 worktree，也不是已部署版本。
状态：本地验证完成，等待独立外审；未 commit、push 或部署。

## 1. 本批解决什么

09-21 只读取证发现，DBMF 09-10 成交量、SMH 09-18 最高价曾导致双源隔离；两者次日同交易日恢复一致，但旧 MATCH 记录没有双方标准化原始 bar，无法从恢复归档逐项重建供应商修正。

本批保存已发生的比较，不增加行情请求、不重新比较、不修改准入规则。新文件位于：

`<archive_dir>/market_comparisons/<operation_id>/<comparison_id>.json`

operation 内每次 backfill 批次使用独立 comparison UUID，兼容同一个 session 的自愈分批抓取，旧批次不被后批次覆盖。该文件是诊断证据，不是 market_admission_latest，也不是新的评分输入。

## 2. 精确改动范围

| 文件（仓库根下） | 修改 |
|---|---|
| src/hermes_escape_top/core/reporting/market_comparisons.py | 新增独立记录器，采集标准化 raw OHLCV、前后证据绑定 |
| src/hermes_escape_top/scripts/backfill_history.py | 传递记录器，比较后采集，纳入既有 HistoryPromotionTransaction |
| src/hermes_escape_top/tests/test_market_recovery_evidence.py | 11 项定点用例，走真实 backfill，网络输入用本地 fixture |
| src/hermes_escape_top/tests/test_audit_rotation.py | 固定测试日期，新增过期记录仍完整归档的断言；生产 audit.py 未改 |
| 本文 | 交接与外审要求 |
| building/reports/market_comparisons/2026-09-22/ | 等价、治理、全套测试生成证据；不是独立审计结论 |

原有三份未跟踪的 2026-09-05 计划文档与本批无关，未改动，禁止一并提交。

以下全部未改：market_admission.py、market_witness.py、decision_identity.py、decision_revision.py、pipeline.py、config.json、flag、准入阈值、路由、评分、部署脚本、依赖 pin、IBKR 和下单路径。

## 3. 契约与边界

### 3.1 采集

- 仅在已有 admission session 启用且存在 archive 路径时创建记录器；关闭 admission 不创建诊断文件。
- 在 `session.admit()` 完成后，使用同一候选 DataFrame、同一 session 的 witness bars 和返回 rows 记录。不修改它们，不新增网络调用。
- 使用已有 Yahoo/Alpaca 标准化函数，保留 open/high/low/close/volume、交易日、见证 bar timestamp、来源与 raw/SIP/1Day 口径及独立 SHA256。
- 每次 capture 记录 `captured_at`；它是本地捕获时刻，不冒充 Yahoo HTTP 抓取时刻。session 的请求窗口、generated_at、completed_through 及已有 equity_witness provenance 一并保留。
- 只记录实际走过 Yahoo/Alpaca 比较、带 candidate_sha256 的行；BTC、禁用/不适用、未进入比较的越界行不在本批覆盖内。
- 对 witness 列表中的非 Mapping 条目，与现有 admission 一样跳过。

### 3.2 前后绑定和恢复标签

- 读取写入前的 `market_admission_latest.json`，嵌入其 payload，记录原文件字节 SHA 与规范化 payload SHA。
- 新记录绑定本次 admission payload 的规范化 SHA；当前准入文件自身不增加字段。
- 只对照**紧邻上一份准入快照**中同 symbol/date、admitted=false、非显式 nonblocking 的行。
- 上一快照必须有可解析且带时区的时间、不晚于当前 session，且无 run_error，否则不赋恢复标签。
- 只有本次比较 status=MATCH 时标 `MATCH_AFTER_REJECTION`。这表示该行比较恢复，不表示全局 admission=OK、整个系统健康或策略可用。
- 不读取第三源 shadow，不因第三源支持某一家而改变 MATCH/拒绝结果。
- 同日重复采集保留独立批次，不伪装成新的自然交易日，不修改晨验连续性计数。

### 3.3 事务与失败

新路径在 prepare/promote 前通过 `HistoryPromotionTransaction.track_path` 注册；准入文件写入后、mark_committed 前原子写诊断文件。失败走原有 rollback；不在异常恢复分支写新的成功诊断。

故障注入已验证：诊断文件已经写入、但 mark_committed 抛异常时，新文件被删除，旧诊断字节及历史 CSV 恢复，准入错误证据保留 ERROR。

**可用性取舍需外审明确接受：**诊断文件写失败会使该次 backfill 回滚；不是 best-effort 静默忽略。损坏的上一准入文件也可能使诊断读取失败。本批不宣称所有 I/O 故障下行为和旧版完全相同。

### 3.4 身份与评分

记录器位于已有指纹排除的 core/reporting，接线位于 scripts；没有扩大指纹排除集。独立实算基线和候选 scoring_logic_hash 均为：

`42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`

新诊断文件不进入 canonical market admission payload、manifest 或 score_pipeline 的业务产物。四日期 strict 比较未改 comparator、未加忽略项，payload、input_hash 及既有七业务产物均等。

该严格比较验证的是既有评分/持久化路径；它不等于新诊断文件也应与旧版字节相同。admission 开启时的新写入路径由定点 backfill/事务测试覆盖。

## 4. TDD 与验证结果

先看到“恢复文件缺失”的失败，再实现记录器。随后用失败测试补未来快照保护、非 Mapping 见证兼容。最初拟按 operation 单文件保存，但既有 self-heal 测试暴露 operation 被分批复用，因此改成批次独立文件，既有测试保留并通过。

| 检查 | 结果 |
|---|---|
| recovery + admission + backfill + history transaction + audit rotation | 95 passed |
| 全套，导出合成 FRED_API_KEY | **1481 passed，140.79 秒** |
| governance | **8/8 OK** |
| 新记录器与新测试完整 Ruff 0.15.22 | PASS |
| 全仓 Ruff E9/F63/F7/F82 | PASS |
| 四个变更 Python 文件内存编译 | PASS |
| git diff --check | PASS |
| 四日期 strict payload + 七产物等价 | all_equal=true，4/4；strict_differences=[] |
| scoring_logic_hash | 基线/候选完全相同 |

历史日期为 2022-01-03、2022-01-25、2026-05-29、2026-06-04。种子来自基线 git archive 内数据，而不是 live。基线解包到 `/tmp/hermes-recovery-baseline.Es9fEF`，比较器为每个日期/版本再创建隔离数据根并逐个独立进程执行。没有全窗口回测或 gate，没有 live 写入或 IBKR 连接。

### 额外测试修复的来由

最初全套结果为 1477 passed / 2 failed；两项旧 audit_rotation 测试的六月样本在真实九月时钟下已经超过 90 天。对未修改基线单独运行该文件，复现相同两项失败（另两项通过）。

仅测试把日期固定为 2026-08-29，维持原始样本与断言，并增加一个一月样本确实过期但仍完整存入 gzip 的断言。未修改生产时钟、保留期或审计归档逻辑，没有跳过失败测试。

## 5. 独立外审操作

在 `/Users/liweishi/Documents/github/hermes` 审当前工作区，包括 untracked 新模块和测试。先核实际 diff 范围，不把本文或生成报告当正确性的证明。

禁止跑 daily、刷新行情/外部源、连接 IBKR、改 live、清审计/状态、修改配置或部署。复现仅用临时目录、基线归档与 fixture。

```sh
git status --short
git diff --check
git diff HEAD -- src/hermes_escape_top/scripts/backfill_history.py src/hermes_escape_top/tests/test_audit_rotation.py

env PYTHONPATH=src:src/hermes_escape_top/tests PYTHONDONTWRITEBYTECODE=1 \
  FRED_API_KEY=external-audit-synthetic-key \
  /Users/liweishi/.hermes-v3/.venv/bin/python -m pytest src/hermes_escape_top/tests -q

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  /Users/liweishi/.hermes-v3/.venv/bin/python scripts/check_governance_consistency.py

uvx --from ruff==0.15.22 ruff check src/hermes_escape_top/core/reporting/market_comparisons.py src/hermes_escape_top/tests/test_market_recovery_evidence.py
uvx --from ruff==0.15.22 ruff check src/hermes_escape_top scripts ops --select E9,F63,F7,F82
```

等价性应先审 comparator，再自行从基线提交 git archive 创建独立目录，不需要相信作者的 /tmp：

```sh
BASE=$(mktemp -d /tmp/hermes-recovery-audit.XXXXXX)
git archive 388de1654c7677984a4e5b9d539bf4ed45d6d837 | tar -x -C "$BASE"
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  /Users/liweishi/.hermes-v3/.venv/bin/python scripts/compare_pipeline_persistence.py \
  --baseline-source "$BASE" --candidate-source "$PWD" \
  --seed-data "$BASE/src/hermes_escape_top/data" \
  --as-of 2022-01-03 --as-of 2022-01-25 --as-of 2026-05-29 --as-of 2026-06-04 \
  --python /Users/liweishi/.hermes-v3/.venv/bin/python --contract strict \
  --output "$BASE/equivalence.json"
```

### 必答问题

1. 本次是否只有 reporting 与 backfill 采集接线的生产变更？任何 config、阈值、身份排除集、评分或路由改动？
2. capture 是否使用已经比较过的同一候选与见证，且没有二次网络请求或二次准入判定？
3. 前后 raw bar、原失败引用、操作/批次身份、时间和 hash 是否可独立重算并对应同 symbol/date？
4. 跨日期、未来/无时区快照、持续拒绝、缺见证、旧第三源能否制造“恢复”或放行？
5. 同 operation 多批次是否保留原记录，既有 self-heal 路径是否继续通过？
6. 诊断写入是否在既有行情事务内？commit 失败后有无残留成功文件或被改坏的 CSV？
7. admission OFF 是否不生成新诊断？原 admission payload 是否没有新字段？
8. scoring_logic_hash 是否与基线相同？四日期 strict 与七产物能否独立复现？
9. 固定测试时钟是否只消除墙钟依赖，未掩盖真实到期行为？
10. 本文是否诚实区分行比较恢复、全局准入、A1 观察和 Phase B 放行？

请分别给出：代码正确性、允许 commit/push、是否具备部署条件三项判定。独立外审通过前不宣称已经可部署。

## 6. 残余限制和发布后观察

- 恢复标签只追紧邻上一快照；若中间一批没有包含原失败行，后续仍保存 raw 比较，但不自动关联更早失败。没有实现全历史恢复状态机。
- 保存的是标准化 bar，不是供应商完整 HTTP 响应；不能从中断言分歧的逐笔交易成因，也不将第三源相关性当独立真相。
- raw diagnostics 不防同用户恶意篡改；SHA 用于绑定和复核，不是第三方签名。沿用现有串行写入纪律。
- 本批增加磁盘写入和存储量，不新增自动清理规则。需上线后观察真实批次数/文件大小，再决定保留期，不擅自删除运行证据。
- 既有 A1 的 scoring_logic_hash 没有变化，不等于授权扩大修订预算或自动跳过发布观察。
- 本批没有自然线上样本。若之后明确批准部署，走既有单次 R6、保留 live config；等待自然运行产生诊断文件，不补跑官方日报。
- 本次没有重新获取今日 live 健康，也没有运行 morning_acceptance。09-21 状态属于上一份只读报告，不冒充 09-22 晨验结果。

## 7. 外审反馈处置（2026-09-22）

用户提供的独立外审结论为代码 PASS、允许 commit/push、部署 HOLD；复现 1481 tests、8/8 governance、四日期 strict 等价及相同评分指纹。该外部结论与作者自测区分记录，不冒充另一轮作者执行。

唯一 P3 是 capture 的 `zip(..., strict=True)` 依赖 admit 对每个候选按原顺序返回恰一行 evidence；当前实现满足，不满足时抛错并回滚，禁止静默截断。先在此登记契约，不改 market_admission.py 的 docstring，因为它位于评分代码指纹范围内，纯注释改动也会打破本批指纹不变的边界。

术语澄清：诊断文件进入 HistoryPromotionTransaction 的事务清单以支持回滚，但不进入 canonical 行情 manifest 或评分 payload。

交付次序：仅提交本批文件、push、验证 CI、只读发布预检。部署仍需用户另行批准；自然线上样本是首次受控部署后的验收条件，不将其误列为部署前必须已存在的证据，不补跑 official daily。
