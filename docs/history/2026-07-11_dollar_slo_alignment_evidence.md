# Dollar SLO 对齐：行为证据与外审交接

> 日期：2026-07-11
> Baseline：`8a2709e`
> Candidate：`e92ad5c`
> Live：`4a0c20c_20260707_171720`
> 部署状态：未部署

## 1. 结论

代码层修复成立，但**暂不允许部署**。

- `dollar` 的三层 SLO 已从 14/6/10 对齐为 14/14/14。
- 4 个正常日期的 score payload 和六份业务持久化产物严格全等。
- `2026-07-10` 的 7 天延迟数据按设计恢复：A11 从 missing/0 分变为 78th percentile/3 分。
- 三标的状态和 DEFCON 路由不变，但 FNGU 目标权重从 `13.7348%` 变为 `12.9787%`。
- 因目标仓位发生变化，本批已触发 `FORMAL_GATE_REQUIRED`；正式 gate 未运行，current baseline 也因 config hash 变化而标记 `STALE_CONFIG`。

## 2. 根因和最小修复

旧状态：

| 层 | 阈值 |
|---|---:|
| `risk_signals.py` intrinsic guard | 14 天 |
| `config.soft_data_slo` effective guard | 6 天 |
| ExternalSourceProfile 运维状态 | 10 天 |

通用 soft SLO 在最后一步覆盖风险源 intrinsic guard，使正常上游发布延迟被误判为数据失效。

Candidate 只做以下变更：

1. `config.soft_data_slo.max_age_days.dollar = 14`；
2. external profile `max_age_days=14`、`warn_age_days=12`；
3. governance checker 强制 config/profile/risk source 三者都等于 14；
4. context 机器快照记录三层值；
5. 测试钉死 7 天可用、15 天 missing。

未改 A11 公式、模块 cap、因子权重、状态阈值或路由规则。

## 3. 上游真实性

FRED 官方端点：

`https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS`

取证时最后一条为：

```text
2026-07-02,120.6902
```

本地 ExternalSourceRunner raw/normalized/target 与官方端点一致，最近抓取状态为 OK。问题不是 fetch 失败，而是本地 SLO 口径冲突。

## 4. TDD 证据

RED：

```text
5 failed, 24 passed
```

失败分别命中：config 仍为 6、profile 仍为 10、12 天被旧 profile 判 stale、治理 check 缺失、治理 helper 缺失。

自审时追加的 flag-off 治理边界先得到 `1 failed`，证明旧 helper 会在 `data_dollar=false` 时误报 `risk_source=-1`；改为检查完整 source registry 后转绿。

GREEN：

```text
30 passed in 0.24s
772 passed in 95.81s
```

## 5. 正常日期严格等价

使用 `scripts/compare_pipeline_persistence.py`，baseline/candidate 分别运行在独立数据副本中；比较归一化 payload 和以下六份业务产物：

- `reentry_state.sqlite`
- `mirror_reference.sqlite`
- `flow_reference.sqlite`
- `hermes_state.sqlite`
- `audit_log.jsonl`
- `signal_journal.jsonl`

| 日期 | 结果 | 状态 |
|---|---|---|
| 2022-06-30 | strict equal | FNGU/MSTR/SOXL = EXIT/EXIT/EXIT |
| 2024-06-28 | strict equal | REDUCE/REDUCE/REDUCE |
| 2026-05-29 | strict equal | REDUCE/EXIT/REDUCE |
| 2026-07-09 | strict equal | REDUCE/EXIT/EXIT |

四日期连 `input_hash` 都一致，证明正常发布期没有旁路变化。

## 6. 2026-07-10 定向回放

### Dollar/A11

| 项 | Baseline | Candidate |
|---|---:|---:|
| latency | 7 天 | 7 天 |
| available | false | true |
| broad dollar | missing | 120.6902 |
| percentile | missing | 77.7778 |
| A11 score | 0 | 3 |
| strategy confidence | 88.6 | 92.6 |

### 决策影响

| 标的 | 状态 | A 模块 | 风险分数 | 目标权重 | DEFCON |
|---|---|---:|---:|---:|---|
| FNGU | REDUCE → REDUCE | 13 → 16 | 31.2707 → 33.1892 | **13.7348% → 12.9787%** | DEFCON1 → DEFCON1 |
| MSTR | EXIT → EXIT | 13 → 16 | 69.2992 → 69.0801 | 15% → 15% | DEFCON1 → DEFCON1 |
| SOXL | EXIT → EXIT | 13 → 16 | 48.1305 → 48.6745 | 30% → 30% | DEFCON1 → DEFCON1 |

MSTR 风险总分在 A 增加后略降，是模块 cap/有效满分归一化的既有行为，不是取证错误。这也说明不能只看 A11 边际分数判断系统影响。

## 7. Baseline 与 gate

现有 baseline 记录：

```text
config_sha256 = a7770b049c4b90bf88cd74fb1eab66841258921d40235f4cbce6f278828e90ea
```

Candidate config：

```text
config_sha256 = b1eada03fe56348cc93a67c13d9585c1b8d0120378e78ad5e2e4b27476c04f72
```

因此现有 current baseline 对 candidate 是 `STALE_CONFIG`。不得只更新文档 hash；需要用 candidate config 重建 full-window/next-open baseline，并按正式 IS-selection/OOS gate 评价该阈值变更。

本批停止状态：

```text
FORMAL_GATE_REQUIRED
formal_gate_run = false
deploy_allowed = false
```

## 8. 外审问题

1. 14 天是否在 config、profile、risk source 三层完全一致？
2. 7 天是否保留 dollar，15 天是否降为 missing？
3. governance checker 能否在任一层回退 6/10 时失败？
4. 四个正常日期是否 payload 和六产物严格全等？
5. 7 月 10 日是否只有 dollar/A11/下游评分与仓位证据发生变化？
6. FNGU 目标权重变化是否足以触发正式 gate？
7. 旧 baseline config hash 是否被明确标为 stale，而非伪装 current？
8. live config、daily、IBKR 和 8766 是否保持未写状态？

## 9. 下一步

在人工授权一个回测窗口后：

1. 用 `e92ad5c`、隔离 data root、next-open 口径重建 full-window baseline；
2. 运行一次正式 gate，不做二次调参；
3. FAIL 则回退该阈值变更，保留现有 6 天 missing 行为并登记；
4. PASS 才进入外审、合并 `hermes-docs`、显式应用 live config 和 R6 原子部署。
