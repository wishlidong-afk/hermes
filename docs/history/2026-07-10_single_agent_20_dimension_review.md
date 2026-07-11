# Hermes 逃顶系统：单 Agent 20 维审查

> 审查日期：2026-07-10
> 审查对象：`hermes-docs @ 4a0c20c`，live release `4a0c20c_20260707_171720`
> 方法：1 个独立审查 Agent 全量阅读；主线程只核验高风险证据与测试结果
> 边界：只读审查，不运行 daily、不刷新 IBKR、不运行全窗口回测、不做破坏性回滚

## 1. 结论

- **P0：0 项。** 当前没有“系统正在错误下单、官方运行停摆、live 版本漂移”这类立即事故。
- **P1：4 项。** 核心集中在 gate 统计口径、baseline 新鲜度、跨存储崩溃恢复，以及陈旧 IBKR 对执行金额的误导风险。
- **综合分：6.2 / 10，置信度 0.86。**
- **工程运行面约 7.6 / 10；策略研究证据面约 4.8 / 10。** 系统已经是较成熟的只读决策与运维系统，但“策略统计上已被当前证据可信证明”仍缺三道硬门：正式 PBO、当前 baseline、可成交时点敏感性。

## 2. 过去几轮已经完成的成果

以下不是纸面规划，代码、live 或测试中已有证据：

1. IBKR 始终只读，系统没有下单路径，`NO_ADVICE` 与安全不变量有专项测试。
2. official scheduled run 与盘中 preview 分离，preview 不覆盖当天官方头条。
3. 日跑回执使用 `RUNNING -> OK/FAILED` 状态机，顶层异常能留下失败证据。
4. 评分写入口已有跨进程 `fcntl` 锁、能力 lease 和确定性 409 BUSY 行为。
5. CSV/JSON 使用原子替换并保留权限，避免半文件读取和历史权限继续漂移。
6. R6 已实现 versioned release、相对 `current/previous` symlink、锁内原子切换和自动回滚。
7. IBKR 轻量刷新已改为 hash-gated overlay，不重抓行情、不生成第二份 official run。
8. Health 已拆分策略数据、持仓对账、辅助资金流；陈旧 IBKR 不再阻断策略评分。
9. 外部源具备 adapter、ledger、raw/normalized/validation 证据、pre-daily check 与陈旧数据拒绝 promote。
10. SIP 金额已诚实标注为量价/turnover 估算，不再冒充真实净流入。
11. 系统健康报告绑定 `input_hash`，Web 不再把旧报告挂到当前 payload 上。
12. 8766 已形成统一决策工作台，策略、持仓、穿透资金、阀门、再入场和数据信任可追溯。

## 3. 20 维评分

| # | 维度 | 分数 | 主要依据 |
|---:|---|---:|---|
| 1 | 策略正确性与逃顶价值 | 6.0 | 硬阀门、路由、再入场完整；当前绩效仍引用旧 baseline。 |
| 2 | 因子设计与语义去重 | 5.5 | A/C/D、硬阀门与 regime 有较强相关性，继续叠加因子的边际价值有限。 |
| 3 | WF/PBO/DSR 统计严谨性 | 2.5 | WF 有 purge；当前所谓 PBO 不是 IS 选择后 OOS 退化概率。 |
| 4 | PIT 与前视防护 | 7.0 | 历史按 as-of 截断；FRED PIT 实现与文档不一致，且不是真 ALFRED vintage。 |
| 5 | 外部数据自动化与来源证明 | 6.5 | 五源 runner/ledger 已成形；AAII 等网页/会员型来源仍有外部脆弱性。 |
| 6 | 数据质量、SLO 与降级 | 7.0 | manifest、SLO、stale-to-missing 较扎实；部分组件仍依赖 proxy。 |
| 7 | DEFCON 路由与 action intents | 7.5 | 动作、理由、路由腿和失效条件可追溯。 |
| 8 | 仓位与 IBKR 对账真实性 | 4.0 | stale 被诚实标为 INFO，但陈旧 NetLiq 仍可生成美元/股数建议。 |
| 9 | 硬阀门、再入场与安全不变量 | 7.5 | 防守状态机和专项测试完整。 |
| 10 | 状态连续性、幂等与回执 | 5.5 | receipt/dedupe 已有；多个持久化存储没有统一 commit/recovery。 |
| 11 | 锁、原子写与崩溃一致性 | 5.5 | 单 writer 和单文件原子性强；跨 SQLite/JSONL 事务仍可能部分提交。 |
| 12 | R6 部署、回滚与 runtime drift | 7.0 | 原子 symlink/rollback 有测试；release/backup 未设 retention。 |
| 13 | 可观测性、health 与告警 | 7.0 | 官方回执、外部源、20 维 health 可见；执行就绪与策略健康仍需更清楚分层。 |
| 14 | WebUI 真实性与可读性 | 7.5 | source/proxy/evidence 已展示；本次未做浏览器视觉回归。 |
| 15 | 本机安全、鉴权与 secret | 7.5 | loopback、Host/Origin、关键 token 已有；遗留 demo 写入口仍暴露。 |
| 16 | 测试质量与故障注入 | 6.5 | 全套 697 绿；缺正式 PBO、跨存储 crash、next-open 时序测试。 |
| 17 | 架构深度与接口局部性 | 6.5 | 领域模块已拆分；pipeline/render/server 仍承担过多编排责任。 |
| 18 | Config、flag 与 baseline 治理 | 4.0 | config 有翻闸元数据；FLAG_REGISTRY 与 baseline 都已漂移。 |
| 19 | 性能、资源与 OOM 控制 | 6.5 | 缓存和回测互斥已考虑；release、backup、`.hermes/.git` 持续增长。 |
| 20 | 文档、runbook 与自动运维 | 5.5 | runbook 可操作；flag/PIT/baseline 文档未持续与代码对齐。 |

## 4. 高优先级发现

### P1-1 Gate 中的“PBO”口径不成立

[`scripts/flag_gate.py`](../../scripts/flag_gate.py) 在每折仅计算固定 variants 的 OOS objective 和相对排名，没有使用 `train_idx` 选择 IS 最优配置；随后调用的 `pbo_from_rank_percentiles` 只是统计某个固定变体有多少折排在候选集后半。

正式 PBO 实现在 [`core/backtest/harness.py`](../../src/hermes_escape_top/core/backtest/harness.py)，定义是“每折选择 IS 最优配置，再看该配置 OOS 是否低于中位数”，但 gate 没有调用它。

直接证据：同一个 baseline 在不同候选集合的报告中 PBO 会从 `0.08`、`0.31` 变成 `0.54`。因此现有数字可称为 **OOS 相对排名失败率**，不能继续称正式 PBO，也不能作为已控制研究选择偏差的证据。DSR 的 `n_trials` 同样取当前命令加载的 variants 数量，会随候选列表变化。

### P1-2 Baseline 已过期

[`baseline.json`](../../building/reports/flag_sweep/baseline.json) 绑定 commit `1567b566`、数据截止 `2026-05-29`；当前 HEAD/live 是 `4a0c20c`，live 输入已到 `2026-07-09`。缓存 key 本身包含 code/config/manifest/soft-history，这是优点，但没有 freshness gate 阻止旧报告继续被文档和 gate 当作“当前基线”。

结论不是“旧收益率一定错”，而是 **旧收益率已经不能证明当前部署态**。在修正 PBO 和成交时点前，不建议只机械重跑并重新盖章。

### P1-3 Pipeline 只有互斥，没有跨存储原子提交

[`pipeline.py`](../../src/hermes_escape_top/pipeline.py) 顺序写 reentry、mirror、flow SQLite，随后写 state SQLite、audit JSONL 和 signal journal。若进程在中间崩溃，部分存储已推进、官方 audit 尚未推进，或反过来；当前没有统一 run-id commit marker、恢复对账或补偿事务。

现有锁解决“两个 writer 同时写”，原子文件解决“单个文件撕裂”，但两者都没有解决“六个业务存储是否一起成功”。

### P1-4 IBKR 不应阻断策略，但应阻断陈旧金额被当成可执行事实

把 stale IBKR 从 strategy health 中拆成 INFO 是正确设计，符合“外部持仓不阻断策略”的要求。剩余问题是 [`action_intents.py`](../../src/hermes_escape_top/core/decision/action_intents.py) 仍可使用陈旧 NetLiq 生成目标美元、股数和差额，同时将单一 `confidence` 降到 70。

建议保持策略状态/目标权重权威，同时分成：

- `strategy_confidence`：只由策略数据决定；
- `execution_amount_confidence`：由 IBKR 快照年龄、持仓覆盖和 NetLiq 决定；
- IBKR stale 时，美元/股数明确标“估算/陈旧”，严重失配时不展示为下单清单。

## 5. 次优先级债务

1. **成交时点偏乐观。** 当前 close-to-close 模拟在收盘信号后立即换仓，未计 next-open、隔夜跳空和成交延迟；需要独立敏感性报告。
2. **Release/backup 无保留策略。** live 已有 48 个 releases、56 个 deploy backups；磁盘未紧张，但增长无上限。
3. **遗留生产端点。** M4 migration 入口仍能改当前 release 内文件；IBKR demo endpoint 可传 `force` 覆盖真实快照。应删除，或仅在显式 dev mode + token 下启用。
4. **配置验证偏浅。** 当前主要校验顶层键、sleeve cap 和 A/B/C/D 权重；阈值排序、route weights、tranches、readonly 等应形成统一 schema/invariants。
5. **Audit JSONL 尾记录耐久性。** 直接 append 遇到中断可留下半行；reader 会跳过坏行，但下一次 append 可能与坏尾连接，应增加尾部修复或 framed journal。
6. **大编排模块。** `web/render.py`、`run_daily_package.py`、`web/server.py`、`pipeline.py` 过大；仅应围绕上述事务、路由、health 证据边界做定向下沉，不做纯美化重构。

## 6. 文档与治理漂移

- [`docs/FLAG_REGISTRY.md`](../FLAG_REGISTRY.md) 仍把 `use_soft_data_max_age`、`use_full_confidence_spine` 标成 OFF/candidate；当前 config 两者均为 true。
- [`context.md`](../../context.md) 声称 FRED 单系列使用 `realtime_start`，而 [`risk_signals.py`](../../src/hermes_escape_top/core/data/risk_signals.py) 明确采用 `date+1`，并说明标准 observations API 的 `realtime_start` 不代表每行历史发布时间。
- context 中 module cap 与当前 config 也存在漂移，应由自动检查而非人工记忆维持。
- 当前 20 维日常 health 更接近“运行证据存在性检查”，不等于本报告这种策略/架构审查；两者不应共用“20 维全绿”的表述。

## 7. 建议执行顺序

### 第一阶段：先恢复研究证据可信度

1. 将现有 `PBO (OOS)` 重命名，冻结其 gate 翻闸资格。
2. 预注册完整候选集合与真实 trials，接入 IS-selection/OOS-evaluation 的正式 PBO/CPCV。
3. 加 baseline freshness gate：HEAD、code hash、config hash、manifest、soft-history、窗口任一不匹配即 `STALE`。
4. 增加 next-open、+1 日、跳空与滑点敏感性；之后才重建当前部署态 baseline。

### 第二阶段：补齐崩溃恢复与执行真实性

5. 为 score run 引入 run-id 和 `PENDING -> COMMITTED` journal；启动时 reconcile 未完成 run。
6. 在每个持久化写点做故障注入，证明要么全部可见，要么可确定恢复。
7. 分离策略置信度与执行金额置信度；stale IBKR 不影响策略，但限制美元/股数的权威展示。

### 第三阶段：治理和容量收口

8. 删除/禁用 M4 与 demo 生产写端点。
9. 为 releases、backups、audit/state artifacts 增加保留数量、容量阈值和 dry-run prune。
10. 自动校验 config、FLAG_REGISTRY、context 和 baseline 元数据一致性。

## 8. 验证记录

- 针对性测试：`66 passed in 7.91s`。
- 全套测试：`697 passed in 87.21s`。
- repo HEAD 与 `origin/hermes-docs`：均为 `4a0c20c`。
- live VERSION：`4a0c20c_20260707_171720`，8766 可访问。
- 审查期间未执行 daily、IBKR refresh、全窗口 backtest 或破坏性 rollback。
- 工作区已有 watchdog/deploy 相关未提交改动，本次未改、未覆盖、未提交。

## 9. 最终判断

Hermes 当前最强的是 **运行纪律、可解释性、只读安全和部署工程**；最弱的是 **研究结论的统计治理**。下一轮不应继续加新因子或继续优化页面，而应优先把 gate、baseline 和成交时点三件事做成可信证据，再补跨存储恢复。完成这三项后，综合分才有机会从 6.2 提升到 7.5 以上。
