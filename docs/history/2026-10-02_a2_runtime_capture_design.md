# A2 第三切片预备：自动绑定接线设计与状态边界验证

日期：2026-10-02。基线：`68e6b7fb5a4b36bd1a5638b8153df0b2d978fb2e`。

## 1. 本轮判定

**完成接线调查、设计和现有机制的隔离边界测试；没有实现生产自动归档。不得据此部署或关闭 A2。**

本轮只新增：

- `src/hermes_escape_top/tests/test_a2_capture_boundaries.py`：14 个边界用例。
- 本文：下一批实现契约、顺序、验证和发布门槛。

工作区仍包含尚未提交的第一、第二切片，不伪装成干净 HEAD。三份九月计划文档保持原样。本轮未改生产模块、配置、flag、依赖、比较器、指纹排除集或前两份等价性 JSON。

## 2. 为什么不能在 score 返回后补存

代码取证的顺序如下。行号针对当前工作区，复核应同时按函数名定位。

| 位置 | 实际行为 | 对自动绑定的要求 |
|---|---|---|
| `pipeline.py:_score_pipeline_locked`，192 起 | 验证 lease，恢复未完成事务，随后读行情、soft、上一轮状态并计算 | 捕获必须在恢复之后、相关状态首次读取之前 |
| `pipeline.py`，224 / 258 / 275 / 276 | 读取前状态、上次路由 payload、再入场状态、执行确认 | 只保留最终 payload 无法代替完整运行前状态 |
| `pipeline.py:_optimize_sizing` / `_drift_state` / `trading_days_since_last_sell` | sizing 的 PSI 与再入场冷却依赖 signal journal | 保存读取时的完整 journal，不只保存今日新增行 |
| `state_store.py:latest_decision_statuses/latest_execution_confirmations/latest_score_payload_before` | 对存在的 DB 调用 `_ensure_schema` | “读取”可能补建表，不能到读取之后才启动回滚保护 |
| `core/reentry/store.py:read_reentry_states` | 调用 `_ensure_tables` | 同上；运行前状态与补表后的状态要区分 |
| `pipeline.py`，291 起 | 现有评分事务在上述状态读取和部分计算之后才开始 | 未来接线需要提前事务边界，不是只加末尾 hook |
| `pipeline.py:_execution_sync` / `_execution_snapshot_summary` | 消费 execution records，最终只留下摘要和推断结果 | 要在实际读取点保存原始 records；摘要不是完整执行输入 |
| `core/data/run_transaction.py:_prepare_transaction` | 入口冻结文件清单，仅支持数据根内的普通文件 | 新增证据文件必须预先登记，不能登记一个目录或事后偷偷写 |
| `run_transaction.py:_remove_backups` | 成功提交后删除临时备份 | 临时事务备份不能被宣称为永久历史档案 |
| `ops/morning_acceptance.py:_collect_transaction` | 严格核对七业务产物的路径集合和数量 | 必须显式升级证据协议；不得把 exact-set 校验改成“至少七个” |
| `decision_identity.py:scoring_logic_hash` | pipeline 和事务模块参与字节指纹；reporting 排除 | 接线会改变 A1 指纹，即使没有改变数学评分公式 |

当前 `score_run_transaction` 克隆 SQLite 主文件，恢复会移除 sidecars。WAL 中的已提交记录未必已经进入主文件。新增用例用真实 SQLite 验证了：主文件复制漏掉一条已提交记录，而 SQLite backup 保存两条。这是新捕获设计必须处理的能力边界，**不是已经证实 live 正在使用 WAL 或已经丢数据**。

## 3. 推荐的最小结构

继续扩展现有 `core/reporting/decision_inputs.py` 的离线契约，不另造一套归档框架。下面的接口名称仅为设计，当前没有实现或生产调用方。

### 3.1 两阶段捕获

1. `begin_decision_capture(...)`：在正确 lease 内、恢复完成后、读取可变状态前，创建运行级捕获计划并冻结输入。返回只供该次运行使用的捕获对象，验证 lease 的路径与持有状态，不接受 `lock_held=True` 旁路。
2. `finalize_decision_capture(...)`：接收该次实际使用的 snapshots、histories、soft records、配置、决策证据和已保存的外部读取结果，核对后生成绑定清单。必要输入先核验；最终清单在原业务写入完成、返回 payload 全部组装后、COMMITTED 之前封存，避免遗漏后加的 state/audit 路径信息。不能为了核对再请求数据，也不能用当前 CSV 代替无法证明的旧输入。

捕获目录以新的 `capture_id` 区分运行；同一 decision_id 重复认证可以对应多次捕获，不覆盖旧档案。capture_id、事务 run_id 与 manifest SHA 都是证据引用，不加入语义身份、不消耗额外修订。

历史文件清单以实际 snapshot universe 为准，包含未参与本次 backfill 的符号及明确缺失项。用冻结 CSV 重新解析后核对该次内存中实际使用的 as_of 行、列、精度和缺失值。缓存与原文件不一致时拒绝绑定，不能只因文件“目前存在”就宣称捕获成功。

离线第二切片的 `RETROSPECTIVE_AS_OF_MATCH` 保留，不改名为实时捕获。只有未来接线完整证明读取与冻结字节一致时，才能使用新的 `IN_RUN_CAPTURE` 模式。

### 3.2 需要保留什么

| 类型 | 必须保存的内容 | 缺失规则 / 不代表什么 |
|---|---|---|
| 行情 | 实际符号全集的完整 CSV、primary/legacy 来源、字节 SHA 与 as_of 投影 SHA | 不新增来源请求；必要文件丢失拒绝，不补成 None |
| 已消费数据 | snapshots、soft records、有效配置和实际传入的 market_admission_status | 冻结实际返回值，不重抓；这不等于提供方原始 HTTP 已归档 |
| 前状态 | hermes_state.sqlite、reentry_state.sqlite、signal_journal.jsonl、audit_log.jsonl | 在首次读取之前冻结；首次安装可明确记 ABSENT，不制造空 DB；损坏/不可读不能当 ABSENT |
| 七业务产物前像 | 其余 mirror/flow DB、dated soft snapshot 的存在性和前像 | 用于整个事务恢复和落盘对照，不冒称所有文件都参与评分 |
| 认证材料 | 消费时的 data_manifest_latest、approved_live_config、VERSION、实际认证时间/参数 | 原样保留其证据角色，不转成新评分因子 |
| IBKR | 当次实际消费的 PositionSnapshot、ExecutionSnapshot 原始 records、source、stale、读取时间；禁用/失败分支显式保存 | 不允许恢复工具连接 IBKR；陈旧 snapshot 不能标成实时 |
| 代码 | 来源提交/release、lock SHA、可核验的源文件集合或源码归档及其 SHA | 只有代码指纹不等于保存了可运行代码；本轮尚未实现 |

legacy daily `state.json`、日报、SIP 后处理和 receipt 属于更外层 daily 的状态。本切片先定义评分事务重放范围，不假装已实现整个日任务重放。若后续需要日任务级恢复，必须另列其消费输入和写入清单。

### 3.3 SQLite 和文件的具体做法

- JSONL/JSON/CSV 冻结字节，并记录存在性、来源路径和 SHA；文件损坏不能改作缺失。捕获 audit 时保存读取所需的完整当前链，仍由原认证器核验其格式与自洽性。
- SQLite 捕获采用只读 URI 连接及 `Connection.backup()`，对隔离输出执行 integrity_check，核对 schema、列和业务行。标记 `SQLITE_BACKUP`：输出 SHA 绑定备份文件，不能宣称输出与源主文件字节相同。
- 新捕获实现不得设置源 DB 的 journal_mode 或删除其 WAL。多 DB 一致性依赖同一把 pipeline lease，SQLite backup 本身不提供跨 DB 原子性。
- 持久化回滚也要单独处理 WAL：不能把逻辑备份用于证据后，仍让现有主文件克隆作为未经证明的回滚方案。事务升级应对 SQLite 使用完整可恢复快照，或在写入前明确拒绝不支持的 sidecar 状态；按真实 WAL 故障测试决定，不静默 checkpoint。
- 私有档案根 0700、文件 0400；账户、持仓、执行和完整配置不得提交 GitHub。文件权限与 SHA 不是加密、签名或同用户恶意代码的安全边界。

## 4. 事务接线顺序

建议另批实现显式的 v2 事务协议，继续支持读取/恢复 v1，不绕过既有 journal：

```text
acquire 同一 pipeline lease
  -> recover 未完成的旧事务
  -> 解析本次配置 / as_of / 符号全集 / capture_id
  -> 枚举七业务文件 + 本次所有新增证据文件
  -> PREPARED（完整前像）并建立 active journal
  -> 冻结 pre-state / 行情 / 认证材料
  -> 原有读取和计算（IBKR 仅原读取点，捕获其返回值）
  -> 原认证器分配/复用 decision_id，预算仍为 2
  -> 核验该次消费输入与 pre-state 绑定
  -> 原七业务写入并完成返回 payload
  -> finalize 输入绑定，写最终清单
  -> COMMITTED（绑定 manifest SHA / decision_id / input_hash / run_id）
  -> 清 active 与临时备份，释放 lease
```

事务文件使用显式 `BUSINESS` / `DECISION_INPUT_EVIDENCE` 角色。晨验先按精确集合核对七业务产物，再按 v2 清单逐个验证新增证据路径、摘要、存在性和绑定。未知角色/重复/越界/缺摘要/多文件都拒绝，不能因为总数较多就放行。旧 v1 继续按现有 exact-set 规则验证，不用旧记录的“无档案”伪装成 v2 已归档。

不要在绑定清单内写它自己的 SHA 制造循环。COMMITTED journal 是外部摘要锚点；通过已存 audit 的 persistence.run_id 找到该事务，再核对 decision_id/input_hash 和档案摘要。COMMITTED 前的目录、完整文件或清单都不代表成功。消费者不得只看目录存在或挑“最新”清单。

新证据仍放在稳定 shared 数据根内、canonical history 之外，避免被市场 manifest 的 rglob 扫入。登记的是每个文件而非目录；失败可以残留空目录，但不能残留可被解释为成功的清单/对象。kill-9 后恢复要按同一登记清单删除新增文件、恢复旧文件。

首轮自动认证档案仅覆盖 `scheduled and not shadow`。manual preview、shadow 不得制造官方绑定；它们的状态读取/回滚边界仍要验证，不能因未生成档案就绕过共同 lease 或写入保护。新协议下何种模式使用何种角色清单必须明确，不能用 preview 的成功记录替代 scheduled 的档案证明。

## 5. 为什么需要单独的 A1 发布证明

修改 pipeline/事务源码会改变保守的评分指纹，feature OFF 也不能抹掉这项变化。本轮新增测试用同值赋值加一条注释，实测指纹仍发生变化。

后续实现不得：

- 扩大指纹排除集，或直接把新 release 塞进既有 v1 等价映射；
- 扩修订预算、重置 audit/state、沿用旧 UUID 或手动补跑官方日报消红；
- 修改比较器忽略项，然后宣称完整 payload 和七产物 byte-identical。

接线批次应分别给出：原评分/路由/动作输出的完整对照、七业务落盘对照、明确列出的认证/事务元数据差异、新档案正反例和迁移/回滚证明。指纹、protocol、证据引用若确实变化，就如实列出，不能把旧 strict 四日期 all_equal 直接复用成新接线的证明。

旧同日 r2 链不因安装代码自动解阻。优先在经验证的自然新决策日期过渡；证据不足继续拒绝。同日迁移若必要，另做证明并外审，不扩大本批范围。

## 6. 本轮实际验证

新增测试是**现有机制的边界刻画和方案可行性探针**，不是已实现功能的 TDD 红转绿，不声称将完整自动绑定缺陷修好了。

| 用例组 | 数量 | 实际覆盖 / 限制 |
|---|---:|---|
| 四个 state readers | 4 | 存在的旧 DB 在读取时补建 schema，证明捕获不能晚于读取 |
| 注册文件的回滚 | 2 | 普通异常 / 留下 PENDING 后调用真实恢复；业务旧字节还原、新清单和前态文件删除；后一项不是 OS kill-9 |
| 注册文件的提交 | 1 | 永久前态文件保留、临时备份删除、COMMITTED；业务文件使用测试字节，不冒称此例覆盖 SQLite 逻辑恢复 |
| 目标边界 | 2 | 已存在目录、数据根外文件均拒绝，未进入事务 |
| lease 边界 | 2 | 无 lease、错误数据根 lease 拒绝 |
| WAL | 1 | 真实 SQLite：主文件复制遗漏已提交 WAL 行，逻辑 backup 完整；检查源 main/WAL 字节不变，不声明 shm 全无副作用 |
| 运行前后状态区别 | 1 | 真实 execution confirmation：前态 T1、后态 T2；离线备份仍 T1 |
| A1 指纹 | 1 | reporting 新文件不变指纹，pipeline 字节变化则改变 |
| 合计 | 14 | 全部 tmp_path，零 live 读取/写入、零网络/IBKR |

初次定点实跑：`14 passed in 0.44s`。新测试完整 Ruff：PASS。

设计/旧事务/第一/第二切片组合：**72 passed，4.35s**（14 + 5 + 24 + 29）。全仓 Ruff E9/F63/F7/F82：PASS。已跟踪 diff 的空白检查通过；新增两文件另行检查。核心 pipeline、identity/revision、事务核心、config 和部署脚本仍零 diff。

本轮重新运行完整套件：**1548 passed，151.04s**，合成 FRED key、现有 conftest 隔离数据；计数为此前 1534 + 新增 14。Governance **8/8 OK**、ibkr_readonly=true。本轮只增加测试/文档，未变更运行时依赖。

评分指纹独立重算仍为 `42d207d6b6c84001bf85324ea6af84b5947c7748b7217d72f0d715b21232ad8a`。逐个重算前两切片模块、backfill 接线、两个测试及两个 equivalence.json 的 SHA，与各自交接记录完全相同。

本轮未重跑四日期比较器：沿用未变化生产实现的已有证据，不把两个冻结 JSON 的候选源码清单宣称为新增测试后的全工作区快照。新边界测试 SHA256：`e150741fb9969c276df1e4d46b2c4bcb75b3a149a2f08dfbb95c3cff143f1202`。

## 7. 下一批执行顺序

1. **3A：离线 pre-state 捕获/恢复原语。** 在现有 reporting 契约上实现，仍不进生产入口。先做必要文件缺失、ABSENT、腐坏 DB、WAL、源根切换、错误 lease、错绑定、restore 失败无输出的红转绿。恢复只写新隔离目录，绝不写回官方 audit/state。
2. **3B：评分事务与验收协议升级。** 完整登记证据文件与角色、外部摘要锚点；测试准备/晋升/绑定/提交失败、独立子进程 kill-9、下一进程恢复，以及 COMMITTED 后清理失败不得反向回滚。保留 v1 兼容与 exact-set 拒收面。
3. **3C：真实入口自动绑定。** 事务提前到 schema 补建前；捕获真实内存输入与 IBKR 返回值；在隔离根完成含非空旧状态的全路径重放，禁止网络，逐行/逐字段对照，而非只重跑三标的 score_symbol。
4. **外审与发布证明。** 核对 A1 指纹、迁移和旧 writer 回滚边界、全部测试/治理/依赖门禁；人工批准后单次 R6，保留 live config，禁止补跑 official；等待自然观察后再评估 A2 闭合。

3C 是否增加默认 OFF 的接线开关，留给该批代码所有者和用户在实现前定案；本轮没有增加 config 键。若使用 OFF 开关，仍须处理第 5 节的指纹变化，不能许诺开关关闭就所有认证字节都相同。

## 8. 外审指引

本轮审计对象仅为新增测试和设计，不是一个新的生产自动归档版本。请先直接复核当前源码，再运行隔离测试；不要运行 morning_acceptance.py、daily 或 live 刷新来验证本文。

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests/test_a2_capture_boundaries.py \
  src/hermes_escape_top/tests/test_score_run_transaction.py \
  src/hermes_escape_top/tests/test_history_versions.py \
  src/hermes_escape_top/tests/test_decision_input_archive.py -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:src/hermes_escape_top/tests \
  FRED_API_KEY=hermes-review-synthetic-key <PY> -m pytest \
  src/hermes_escape_top/tests -q -p no:cacheprovider
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src <PY> scripts/check_governance_consistency.py
```

必答问题：

1. 是否准确识别所有已列出的 state 读取及 schema 写入，不把 score 之后的 DB 冒充 pre-state？
2. WAL 探针是否使用真实 WAL 和已提交记录，而非 mock；是否诚实区分探针与生产已修复？
3. 是否预先登记每个证据文件、失败与恢复共用真实 journal、COMMITTED 前没有成功凭证？
4. 是否保留七业务产物 exact-set 校验，不把额外文件混成业务成功？
5. 是否承认将来的 pipeline 接线改变 A1 指纹，不暗改排除集/预算/迁移规则？
6. 是否明确 IBKR 原始执行输入、代码内容和 daily 外层状态尚未捕获，未宣称完整 A2？
7. 前两切片源码/证据是否本轮保持不变；三份九月文档是否未混入本轮？
8. 是否区分测试失败注入、同进程恢复、独立进程 kill-9 和自然线上样本？

## 9. 尚未完成

没有新的生产 hook、自动 pre-state、v2 journal、WAL 回滚修复、完整代码归档、全路径重放或自然线上证据；这些是下一批工作，不用“方案已写”抵作实现完成。没有提交、推送、部署、翻闸、连接 IBKR、运行官方日任务或修改 live。A2 保持 OPEN，Phase B 不启动。
