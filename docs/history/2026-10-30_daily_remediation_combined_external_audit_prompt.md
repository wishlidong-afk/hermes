# Hermes 近期故障补丁：统一独立外审入口

日期：2026-10-30（Asia/Shanghai）。

**状态：作者本地验证完成，当前组合待独立外审；未提交、未推送、未部署。DEPLOY HOLD；A2 OPEN；Phase B 未启动。本文不是外审报告或发布授权。**

## 1. 给外审 Agent 的任务与边界

请审查下述独立候选的当前组合，逐行阅读实现及新增测试，独立复算证据绑定，并针对契约做必要的反证。不要仅采信本文或作者的 PASS 标签。分别给出代码正确性、提交/推送技术许可、部署条件三个判定。

- 候选目录：`/Users/liweishi/Documents/New project/hermes-daily-failure-remediation-2026-10-23`。
- 分支：`codex/daily-failure-evidence`。
- 基线/当前 HEAD：`2db0cdc562309b6222a69aaee8dbdaf51c763b93`，与本轮观察到的 live release `2db0cdc` 对应；实现仍在未提交工作区中。
- 这是独立 clone，不是主目录的 linked worktree。origin 指向本机 `/Users/liweishi/Documents/github/hermes`，不是 GitHub；不要向它推送作为发布捷径。
- 审查范围是基线到候选的四个已跟踪文件变化，加两个新测试文件；不是主目录 `8d16ad8...` 之上的累积 A2 变更。
- 不编辑候选或 live，不 stage/commit/push/deploy；不得运行 official daily、morning_acceptance.py、行情/外部源刷新或真实 IBKR 操作。允许在独立临时环境运行测试、治理和比较器。
- 依赖元数据/漏洞库复核如需网络，只访问公开发行与安全资料；不要调用金融数据或 broker 接口。行为探针和业务测试保持禁止网络。

## 2. 精确实现范围与字节绑定

| 路径 | 职责 | 当前 SHA256 |
|---|---|---|
| `requirements.txt` | certifi 直接 pin 更新 | `037be4f24a13220684ec36939d37a7f11659a8711b281f2004d5148454f77931` |
| `requirements.lock` | certifi、urllib3 及相应发行物摘要更新 | `71fc586a3909e80ae3c3fcc600e17d1082f39bae7ececed59a1c32038ba73e62` |
| `src/hermes_escape_top/scripts/run_daily_package.py` | 失败步骤标签与当前调用失败健康报告 | `abb69acb5778c20159844863d6fb94499794bde31f85f4de124b43d59191315b` |
| `src/hermes_escape_top/web/health.py` | 仅展示独立拒收身份数与比较次数 | `211e9ffd327060221c7dd95555a1a662732b8b79577d4f02e839cff7718f57d7` |
| `src/hermes_escape_top/tests/test_daily_failure_evidence.py` | 新增 9 项失败证据回归用例 | `362b877b028a14a0da2d3baa75ec9e94e645141b4146fa4ec23b14af52976a26` |
| `src/hermes_escape_top/tests/test_market_conflict_counts.py` | 新增 23 项冲突计数用例 | `5473f758d086d1668706181bf91a0c36f407d0df526ed48a31722fe955be9375` |

四个已跟踪文件当前 diff 为 49 additions / 9 deletions；此统计不包含两个未跟踪测试文件，不能当作全部代码量。附带材料是三份原交接文档、下述三处证据和本文。

本文整理时，候选的 config、market_admission、market_witness、market_third_source、decision_identity、decision_revision、pipeline 七文件均与基线字节相同。准入阈值、canonical 晋升、评分、路由、revision 预算、feature flags 不在修改范围内。请外审自行复核，而非只检查 config diff。

## 3. 三项契约与反证重点

### A. 失败运行证据不能错绑旧成功结果

在最终 receipt 自检前将步骤标为 `run_receipt`，不再把成功的辅助资金流步骤误记为失败位置。仅在本调用已返回 scoring payload 且写出 FAILED receipt 后，尝试用这两者生成健康报告；保留失败及原异常，次级健康写入异常不能将失败改成成功。

请检查：显式/隐式日期、当前 input/decision 绑定、旧 OK 报告被当前 FAILED/CRITICAL 取代、次级报告写失败、首次健康写失败、缺失 FAILED receipt、评分尚未返回、shadow/manual 路径。没有当前 payload 时不得拿旧 payload 或合成 hash 补造报告。

边界：不是所有早期失败都能形成完整绑定健康报告；没有新增报告多文件原子事务、outbox 或断电保证。四日期评分比较不覆盖本段失败收尾，须看实际 receipt/health writer 的回归测试。

### B. 依赖安全更新必须与实际安装一致

仅 `urllib3 2.7.0 -> 2.8.0`、`certifi 2026.4.22 -> 2026.10.19` 更新；32 个生产依赖中其余 30 个版本/摘要记录保持。不要借机升级整个依赖图。

已有证据记录旧 lock 四项 advisory、候选 lock 零已知 advisory；这是 10-23 扫描时点结论，不是 10-30 新扫描或 live 已安装版本证明。若当前公开数据库出现新结果，请报告真实差异，不修改旧 JSON。来源与精确公告见原依赖交接。

旧/新离线行为探针分别验证超长 chunk line 接受/拒绝及受影响 certifi 根证书存在/移除；始终开启证书与主机名验证、network_attempts=0。urllib3 官方代理 TLS 行为变更不能省略；生产源码扫描未见自定义代理 TLS，但未核实部署环境代理配置，也未审计 OS/JVM 全部信任库。

核验 lock 时比较冻结 before 文件、完整发行哈希与结构化记录；不要用不加约束的今天重新解析结果要求逐字复现。原 header 是历史通用生成注释。原交接记录了 constrained regeneration 命令与实物，不能冒称任意日期自由解析可复现。

### C. 冲突去重仅用于展示

仅在当前 admission payload 内，以 `(symbol, date, status, candidate_sha256, witness_sha256)` 去重。完整字符串、规范小写 64 位 hex hash、blocking rejected 行数与原整数计数对账后，才显示 `unique_conflicts=1 attempts=3`。

身份不完整时 unique 为 UNKNOWN；行数仍能对账才显示 attempts。行集/计数不一致时两者 UNKNOWN。accepted 和 blocking=False 的延后 BTC 不计入。attempts 是拒收比较记录数，不是 HTTP 请求数或跨运行事件数；格式核验不认证摘要真实性。

请攻击不同 symbol/date/status/任一 hash、缺字段、错误类型、布尔计数、行数不符、畸形 rows，以及组件级和核心策略级拒收。原始 rejected/rows/canonical/策略分层不得改变。

## 4. 冻结证据与历史口径

所有下列路径相对候选根，旧文件不得覆盖重生成：

| 证据 | 已有结果与绑定 |
|---|---|
| `building/reports/daily_failure_remediation/2026-10-23/equivalence.json` | 原失败补丁 strict 四日期；SHA `7df7bfe8c45f024e0be2418af15f88a655e29b71f36a3229bfa77b70002c55fa` |
| `building/reports/dependency_security/2026-10-23/` | 19 文件；清单绑定另外 18 件，清单 SHA `fdf26f21c0e7370e056a291e370463370548ca1294855c69aa5e78b8549c9069` |
| `building/reports/market_conflict_reporting/2026-10-24/` | 9 文件；清单绑定另外 8 件，清单 SHA `cbf6118cbf1f1ff8f6edfe86d0c579ecb6328a086f384bd24db89e38511bbd99` |

当前组合：full-suite.log 为 **1513 passed / 152.21s**，governance 8/8 OK；新计数文件与 health truth 64 passed。依赖片先前组合为 1490 passed / 158.89s；最初失败片为 1490 passed / 152.02s，且当时旧 lock 安全扫描红。三者是不同增量/环境的真实时点，不能求和、互换或把旧红结果改成绿。

比较器 `scripts/compare_pipeline_persistence.py` SHA：`19540147b21004355d0f54eb14c0455301bddb870b47a370b0a753178d5bd76d`。当前四日期 strict 报告 all_equal=true；依赖片另有旧/新两个解释器报告及跨环境 full normalized payload + 七业务摘要核对。比较器未改，未加忽略项；相等不是原始 SQLite 文件字节相等，也不是 health 文案或所有日期相等。

评分逻辑指纹仍为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`，与本候选基线相同。不覆盖主目录 A2 的不同指纹及其迁移证明。

原始交接（按顺序阅读，后续状态由本文解释，不改写原时点正文）：

1. `docs/history/2026-10-23_daily_failure_evidence_remediation.md`
2. `docs/history/2026-10-23_dependency_security_remediation.md`
3. `docs/history/2026-10-24_forwarding_and_market_conflict_remediation.md`

## 5. 独立复现指引

先读源码与比较器，再运行。以下均从候选根执行；所有新输出放审计员自己的临时目录，不覆盖上述冻结文件。

作者候选解释器是 `/tmp/hermes-dependency-security.BQMAqq/candidate-venv/bin/python`，旧环境为同根 `baseline-venv/bin/python`。临时路径不保证永久存在；可重新建立 Python 3.11 隔离环境，按旧/新 lock 分别 `uv pip sync --require-hashes`，候选 editable dev 安装须 constrained by candidate lock。生产 32 pins 在 dev 安装后再次逐一核对，不能仅凭 pip check 声称版本完全相同。原环境/工具版本详见依赖包 environments.json。

```sh
export PY=/tmp/hermes-dependency-security.BQMAqq/candidate-venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
export FRED_API_KEY=external-audit-synthetic-key
"$PY" -m pytest src/hermes_escape_top/tests/test_daily_failure_evidence.py src/hermes_escape_top/tests/test_market_conflict_counts.py src/hermes_escape_top/tests/test_run_receipt_writer.py src/hermes_escape_top/tests/test_health_truth.py -q -p no:cacheprovider
"$PY" -m pytest src/hermes_escape_top/tests -q -p no:cacheprovider
"$PY" scripts/check_governance_consistency.py
"$PY" -m pip check
"$PY" -m ruff check src/hermes_escape_top/tests/test_daily_failure_evidence.py src/hermes_escape_top/tests/test_market_conflict_counts.py src/hermes_escape_top/web/health.py
"$PY" -m ruff check src/hermes_escape_top scripts ops --select E9,F63,F7,F82
"$PY" -m mypy --ignore-missing-imports --follow-imports=skip src/hermes_escape_top/core/data/market_witness.py src/hermes_escape_top/core/data/market_admission.py src/hermes_escape_top/core/backtest/formal_gate.py src/hermes_escape_top/web/health.py
"$PY" -m pip_audit -r requirements.lock --no-deps --disable-pip --progress-spinner off
git diff --check
```

以上是提供的复现命令，不是作者在 10-30 重新运行的记录。依赖审计需要公开安全数据库网络；不要与禁止业务探针网络混淆。编译如需执行，将 PYTHONPYCACHEPREFIX 指向临时目录。全文件 Ruff 的上述范围不包含整个历史 daily wrapper，不能宣称全部生产文件完整 Ruff 零债。

比较基线必须重新从 `git archive 2db0cdc562309b6222a69aaee8dbdaf51c763b93` 导出到新临时目录；seed 使用该基线的 `src/hermes_escape_top/data`，不是 live 数据。调用未改比较器，参数为 `--baseline-source`、`--candidate-source`、`--seed-data`、`--python`、`--contract strict`、临时 `--output`，并分别传四个 `--as-of`：2022-01-03、2022-01-25、2026-05-29、2026-06-04。旧/新 runtime 分别执行后，核对全部 normalized payload 与七业务摘要，而非仅 input_hash。不得写入 live、候选 seed 或复用先前已污染的比较数据根。

## 6. 自然运行观察：已恢复，不代表补丁已上线

本次只读核对的报告根：`/Users/liweishi/.hermes/logs/acceptance/`。10-30 JSON/Markdown 日期、总体状态和关键证据一致；live 仍为 `2db0cdc_20260922_233427`。runtime PASS、strategy WARN、CERTIFIED、官方 audit count=1、七产物 COMMITTED、active absent、watchdog lag=0。Dollar 为官方当日核验后的发布延迟 WARN；IBKR stale/unavailable 为非阻断 INFO，不是已恢复实时对账。

| 晨验日期 | 总体 | completed_through | consecutive_ok |
|---|---|---|---:|
| 10-25 | PASS | 2026-10-23 | 1 |
| 10-26 | PASS | 2026-10-23 | 1 |
| 10-27 | PASS | 2026-10-26 | 2 |
| 10-28 | PASS | 2026-10-27 | 3 |
| 10-29 | PASS | 2026-10-28 | 4 |
| 10-30 | PASS | 2026-10-29 | 5 |

10-26 重复完成日期不算新交易日。当前已满足五个完成日期的准入目标，但它发生在旧 live，**不是本候选部署后的观察，也不是 A2 capture ON 自然样本**。保留 10-22 SOXL high 和 10-24 FNGU volume 的失败记录，不将连续恢复解释成旧冲突已修复。

10-30 报告 JSON SHA：`2054b6f314af4532825ca815aaf32bd6ebbf36c54f455a7a7d95c26ddc9c40e0`；Markdown SHA：`fd040446cdf579aeaf19ea709b0df54d0369b3553fea9155ed45a05a433da9f6`。这是作者读取时的字节绑定，不是独立签名。报告不复制入 Git；审计员不可读取时标明未独立验证，不要求补跑生成。

转发器仅等待并转述已有报告，主 cron 独立生成。10-24 旧交接的“自然等待待观察”是当时状态；10-28 已在本对话观察到文件初缺、只读查看任务、等待约 30 秒、报告到达再转述的分支。此执行观察不证明调度偏移根因或全部超时/错误分支已消除，也不是本候选代码的一部分；本轮不修改两个自动任务。

## 7. 外审必须直接回答的问题

1. 基线、六个实现/测试文件、旧证据清单及比较器是否精确匹配？有没有混入主目录 A2 或其他实现？
2. 失败自检是否正确定位为 run_receipt，而非已成功 flow？当前失败报告是否与本调用日期、input、decision 和 FAILED receipt 相符？
3. 评分未返回、receipt 缺失、次级写入失败、shadow/manual 是否仍诚实失败或缺证据，不借旧 OK/旧 payload 背书？
4. 依赖变动是否只涉及两包、四发行哈希及直接 certifi pin？其余 30 记录、实际安装兼容性是否保留？
5. 安全探针是否真实 old/new 对照、零业务网络、TLS 验证开启？当前审计结果与历史扫描时点有无差异？
6. 三次相同比较是否只显示一身份；任一身份字段实质不同是否保持区分？缺失、畸形及不对账是否 UNKNOWN？
7. 原始 admission、canonical、核心/组件分层、阈值、评分/路由/预算/flags 是否未改？第三源是否仍 research-only？
8. 四日期 strict 是否能用新基线/数据根独立复现？比较器是否未新增忽略？是否区分完整业务比较与 input_hash、原始 SQLite 字节？
9. 是否诚实区分当前源码全套、旧片结果、fresh locked 安装与 hermetic、官方报告与离线诊断？
10. 五日恢复是否仅被解释为旧 live 准入观察？是否仍保留行情根因未知、实时 IBKR 未恢复及 A1/A2 门槛？
11. 是否存在凭证、真实持仓/账户、broker tape、DB/WAL、未声明业务数据或私有配置混入候选材料？本机绝对路径不等于凭证，但应披露。
12. 请按 P0/P1/P2/P3 给路径+行号、可复现步骤、影响和处置；无发现也需列实际检查范围、未覆盖边界及三个独立判定。

## 8. 审查后顺序，不自动执行

外审通过后才整理明确路径的提交与 GitHub 目标；避免 `git add -A`，不得混入主目录 A2、三份九月计划或私有 capture。云端 CI 和当前安全门禁须针对实际发布组合，现无云端 CI PASS 声明。任何源字节变化需重新绑定并按相关风险补验证，不用旧片批准覆盖新字节。

部署另需用户明确批准、无活跃 writer、避开北京时间 07:00-07:20、保留 live config、单次标准 R6。不得借部署补跑 official daily。部署后按既有自然调度核 VERSION、livez/readyz、官方 receipt/audit、七产物事务、默认页及晨验；新版本观察不能借本次旧版本五日结果代替。

主目录 A2 的 3C-5h A 外审、离线只读适配与晨验接线、完整自动 T1->T2、运行环境/耐久性边界、新指纹 A1 迁移/回滚、最终组合 CI 与自然 ON 样本仍各自未完成。本外审既不替代它们，也不要求为准备本文重复审查其未变原语。**DEPLOY HOLD；A2 OPEN；Phase B 未启动。**

## 9. 本轮作者核验记录

10-30 整理前，重新读取了三份原交接、两份源码 diff、当前 CI 静态命令、证据清单/日志和正式观察报告。两清单共 26 个被登记文件逐项摘要匹配；当前六实现/测试字节与上表一致；比较器与七个核心文件绑定无漂移。旧全套日志分别读到 1490/1513 的原结果。

本轮仅新增本文；不因纯文档整理重跑全套、重解析 lock、重生成证据或联网刷新 advisory。原证据与源码结果按未变字节复用，外审需独立决定复现范围。未运行 official daily、morning_acceptance.py、金融数据刷新、IBKR、Git 写操作或部署。

## 10. 同日外审接收追加

当前六个实现/测试文件及证据组合独立外审正确性 PASS，获得精确范围的提交/推送技术许可，不是用户 Git 写操作或部署授权。原文见 `2026-10-30_daily_remediation_combined_external_audit_report.md`，处置见 `2026-10-30_daily_remediation_combined_external_audit_followup.md`。旧正文与冻结材料保留，生产/测试字节未变。

P2/P3 按接收表逐项记录：代理 TLS 适用性作为部署前检查；展示截断、中断边界与非自含历史日志不扩大为本轮代码修改。原文两处叙述需按 followup 更正：SOXL 的价格差是 1.1024%，3.1067% 是成交量差；转发等待分支在 10-28 已有自然执行观察，不代表调度根因或全部分支验证完毕。当前组合 strict 以 343 文件绑定为准，不沿用旧 342 报告覆盖新字节。

本次仅接收归档和追加文档，未提交、推送、部署、补跑或修改 live/主 cron。**DEPLOY HOLD；A2 OPEN；Phase B 未启动。**
