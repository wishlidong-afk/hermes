# Hermes Steps 1-7 最终审计与部署前交接

> 审计日期：2026-07-11
> Repo 候选：`hermes-docs @ 2d1606e`
> 当前 live：`4a0c20c_20260707_171720`
> 边界：只读核验 live；未运行 daily、未刷新 IBKR、未改 live config、未部署

## 1. 结论

- Steps 1-7 的 repo 候选实现已经完成，综合评分由上轮 `6.2/10` 提升到 **`7.7/10`**。
- 研究证据、跨存储崩溃恢复、执行金额真实性和运行治理均有实质提升；全套测试新鲜结果为 **`771 passed in 98.62s`**。
- **不能把 repo 完成等同于 live 完成。** live 仍在 `4a0c20c`，尚未包含 `d05f7b3`、`66f4a82`、`2d1606e`。
- 本轮最终取证发现 1 个新的 P1：`dollar` 在评分源、通用 soft SLO、外部源运维层分别使用 14/6/10 天阈值。当前官方 payload 因 7 天延迟把它降为 missing，而 FRED 官方数据和自动刷新链路本身都正常。
- 该 P1 的修复会改变 A11 的实际评分输入，必须单独审批和验证，不能混在治理提交里静默上线。

## 2. Steps 1-7 状态

| Step | 结果 | 主要证据 |
|---:|---|---|
| 1 | PASS | 旧 pseudo-PBO 不再冒充正式 PBO；正式 IS 选择/OOS 评价接口落地 |
| 2 | PASS | baseline 绑定 source commit、config/code/data fingerprints 和 freshness 状态 |
| 3 | PASS | next-open 成为 headline；legacy close 独立保留；成本敏感性单列 |
| 4 | PASS | 2020-03-12 BTC `4970.79` 真值保留，非正值仍拒绝 |
| 5 | PASS | 六业务产物具备 run-id、PENDING/COMMITTED、异常回滚和 kill 后恢复 |
| 6 | PASS | `strategy_confidence` 与 `execution_amount_confidence` 分离；陈旧 IBKR 不伪装可下单金额 |
| 7 | PASS | M4/demo 写端点 410、JSONL 尾修复、retention dry-run、config/flag/baseline 治理检查 |

关键提交：

1. `e2b6dab research: harden gate and execution baseline evidence`
2. `98c4c79 fix: preserve the real 2020 btc crash bar`
3. `517043c research: gate on next-open equity`
4. `d05f7b3 fix: recover cross-store score transactions`
5. `66f4a82 fix: separate strategy and execution confidence`
6. `2d1606e chore: close runtime governance gaps`

## 3. 20 维复评分

| # | 维度 | 上轮 | 当前 | 当前判断 |
|---:|---|---:|---:|---|
| 1 | 策略正确性与逃顶价值 | 6.0 | 7.5 | 当前部署态 baseline 已重建，headline 改为 next-open |
| 2 | 因子设计与语义去重 | 5.5 | 6.5 | 未继续堆因子；相关性和模块 cap 仍需长期复核 |
| 3 | WF/PBO/DSR 统计严谨性 | 2.5 | 7.0 | 正式 gate 已有；历史 live flag 尚未全部按新口径重审 |
| 4 | PIT 与前视防护 | 7.0 | 7.5 | 评分按 as-of；FRED 仍是 date+1 近似，不是 ALFRED vintage |
| 5 | 外部数据自动化与来源证明 | 6.5 | 7.0 | 五源 raw/normalized/validation/ledger 完整；AAII 主路径仍会被站点阻断 |
| 6 | 数据质量、SLO 与降级 | 7.0 | 6.5 | stale-to-missing 正确，但 `dollar` 三层阈值漂移造成当前假降级 |
| 7 | DEFCON 路由与 action intents | 7.5 | 8.0 | 路由腿、失效条件和目标权重可追溯 |
| 8 | 仓位与 IBKR 对账真实性 | 4.0 | 8.5 | 策略结论与金额可执行性已分开；陈旧金额不再伪装下单清单 |
| 9 | 硬阀门、再入场与安全不变量 | 7.5 | 8.0 | 只读和 no-advice 边界稳定，未发现下单路径 |
| 10 | 状态连续性、幂等与回执 | 5.5 | 8.5 | 六产物统一恢复协议补齐跨存储失败窗口 |
| 11 | 锁、原子写与崩溃一致性 | 5.5 | 8.5 | lease、七点故障注入、kill 后恢复和 pending audit 隐藏均有测试 |
| 12 | R6 部署、回滚与 runtime drift | 7.0 | 7.5 | 原子发布稳定；retention 已有 dry-run，但本批尚未部署 |
| 13 | 可观测性、health 与告警 | 7.0 | 8.0 | 三层 health 清楚；SLO SSOT 仍是监控盲点 |
| 14 | WebUI 真实性与可读性 | 7.5 | 8.0 | 估算金额与策略权威性分层；本批未做全页视觉回归 |
| 15 | 本机安全、鉴权与 secret | 7.5 | 8.5 | 遗留生产写端点永久 410，loopback/token 规则未放宽 |
| 16 | 测试质量与故障注入 | 6.5 | 8.5 | 771 绿，新增 formal gate、next-open、事务故障注入、JSONL 修复测试 |
| 17 | 架构深度与接口局部性 | 6.5 | 7.0 | recovery/jsonl/governance 已下沉；pipeline/server/render 仍偏大 |
| 18 | Config、flag 与 baseline 治理 | 4.0 | 7.5 | 自动检查已落地，但尚未覆盖跨层 SLO 一致性 |
| 19 | 性能、资源与 OOM 控制 | 6.5 | 7.5 | 回测缓存与互斥保持；runtime prune 仍只 dry-run |
| 20 | 文档、runbook 与自动运维 | 5.5 | 8.0 | context/flag/baseline 已闭环；live 与 repo 版本差异需部署后再核 |

当前总分：`154 / 200 = 7.7 / 10`。

## 4. 新发现：dollar SLO 三套口径漂移（P1）

### 4.1 事实链

1. FRED 官方 CSV `DTWEXBGS` 当前最后一条为 `2026-07-02,120.6902`。
2. live ExternalSourceRunner 的 raw、normalized、target 和官方 CSV 一致；最近刷新 `status=OK`，input/output hash 连续稳定。
3. repo/live 风险源 `FredPercentileSource("dollar", ...)` 允许 `max_age_days=14`。
4. 外部源 profile 使用 `max_age_days=10`、`warn_age_days=8`，2026-07-11 正确显示 `DUE_SOON`。
5. `config.soft_data_slo.max_age_days.dollar` 却是 `6`。官方 2026-07-10 payload 因发布时间距 as-of 7 天，记录为：

   `stale: latency 7d > max_age 6d`

6. 因此 8766 的策略层显示“软数据源过期 1 — dollar”，并非抓取失败，而是通用 SLO 在最后一步覆盖了风险源原本的 14 天容忍度。

### 4.2 根因

同一业务事实被复制到三处，且治理 checker 只核 config/flag/context/baseline，没有核“采集 profile、评分 source、soft-data SLO”之间的一致性。`dollar=6` 在 T9 config 中晚于 `risk_signals=14` 加入，形成了长期隐藏的有效阈值覆盖。

### 4.3 推荐修复（需人工审批）

推荐把 `dollar` 三层统一到 **14 个日历日**，并新增治理断言：

- `config.soft_data_slo.max_age_days.dollar == 14`；
- `ExternalSourceProfile("dollar").max_age_days == 14`；
- 风险源 intrinsic max-age 与 config 一致；
- 7 天延迟仍 available，15 天延迟才 missing；
- external status、soft snapshot、health 对同一日期给出一致结论。

这不是 byte-identical 修复：在当前 `2026-07-10` 输入上，A11 会从 missing 恢复为可评分数据，`input_hash` 可能变化。上线前至少需要：

1. 针对 6/7/14/15 天边界的 RED/GREEN 测试；
2. 四历史日期对比，证明正常时期不变；
3. 2026-07-10 定向回放，记录 A11、总分、状态和路由是否变化；
4. 若动作或仓位变化，按正式 gate/人工翻闸流程处理；
5. 部署时显式应用 live config，不能沿用惯例 `N` 后误以为 repo 阈值已生效。

## 5. 其他残余风险

### P2

1. **历史 live flags 未全部按新 formal gate 复审。** 新工具可信，不代表旧 pseudo-PBO 数字自动升级为正式证据。
2. **AAII 自动抓取仍依赖站点行为。** 当前缓存数据新鲜，但最近 primary attempt 是 `FETCH_ERROR`；status 以最近成功记录为主，health 不会在缓存仍新鲜时突出“自动恢复路径已坏”。
3. **完整 baseline JSON 为 165 MB 本地证据。** 小型摘要和 equity 已提交；重建需要 source commit + 四个 fingerprint，而不是依赖工作区大文件。
4. **repo 与 live 相差三笔核心提交。** live 仍没有跨存储恢复、置信度分离和 Step 7 治理收口。

### P3

1. `pipeline.py`、`server.py`、`render.py` 仍是大编排模块；后续只围绕明确事务边界拆分。
2. runtime prune 目前只做 dry-run。真实 live 取证显示可候选清理约 36 个 releases、46 个 backups，合计约 277 MB；执行删除仍需单独受控窗口。
3. 当前工作区有部署/watchdog 轨未提交文件，不能使用 `git add -A`，也不能把它们归入本批证据。

## 6. 验证证据

### 静态与治理

```text
scripts/check_governance_consistency.py: ok=true
  baseline_metadata=OK
  config_invariants=OK
  context_snapshot=OK
  flag_registry=OK

python -m compileall: exit 0
```

### 测试

```text
771 passed in 98.62s
```

### 持久化等价

`building/reports/pipeline_persistence_equivalence_2026_07_11.json`：

- 四日期：2022-06-30、2024-06-28、2026-05-29、2026-07-10；
- 六业务产物逐行/逐表比较；
- 仅归一化随机 `persistence` 运行信封；
- `all_equal=true`。

### Live 只读取证

```text
VERSION: 4a0c20c 20260707_171720
8766: HTTP 200
as_of: 2026-07-10
scheduled receipt: OK
strategy health: DEGRADED (dollar only)
position reconciliation: INFO (IBKR stale, non-blocking)
auxiliary flows: OK
```

## 7. 工作区隔离

本批不得提交、覆盖或回滚以下其它轨文件：

- `scripts/deploy_to_live.sh`
- `src/hermes_escape_top/tests/test_deploy_to_live.py`
- `src/hermes_escape_top/tests/test_ops_entrypoints.py`
- `ops/hermes_watchdog.py`

以下大文件/本地产物也不进入证据提交：

- `building/reports/current_baseline/CURRENT_BASELINE_FULL.json`
- `building/reports/execution_timing/`

## 8. 部署判断

**Steps 1-7 repo 候选本身达到外审条件，但当前不建议直接部署。** 推荐顺序：

1. 外部 Agent 按两份 handoff 和本文件复核六笔提交；
2. 人工决定 `dollar` SLO 是统一到 14 天，还是保留 6 天并接受频繁 missing；
3. 若选 14 天，单独提交阈值修复和行为证据；
4. 合并/隔离现有部署轨脏文件，使部署 diff 可审；
5. push 后使用 R6 原子部署；config 变化时必须显式确认是否应用；
6. 部署后核 VERSION、8766、official receipt、事务恢复状态、置信度文案和 dollar 健康口径。

在上述决策前，最诚实的状态是：**代码候选通过，live 尚未升级，当前 dollar 降级是 SLO 漂移而不是数据抓取失败。**
