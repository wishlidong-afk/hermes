# A · M4 上线迁移计划 + Parity 差距分析

> **日期：2026-06-02** ｜ 决策 A = "以 canonical 包为唯一真相"。经核查,这等于
> **把生产从 v25 单体切到 `hermes_escape_top` 包**——即项目的 **M4 上线切换**,
> 受红线"所有 live 开关由人翻"约束。本文是切换前的**计划 + 差距分析**(不碰生产)。

## 0. 两套系统的真实关系

| | 生产(当前在跑) | 目标(canonical) |
|---|---|---|
| 入口 | `run_daily.py → escape_top_system.main`(单体,3037 行) | `hermes_escape_top.pipeline.score_pipeline` |
| 支撑 | `escape-top/core/`(单体私有,9 文件) | `hermes_escape_top/core/*`(完整) |
| 数据 | 单体 `collect`(下载/CBOE/IBKR)→ `daily_raw_data` | `MarketData`/`store`/`adapters`(消费 store) |
| 评分 | 单体 `score_symbol`/`score_item_points`/`calibrated_score` | `core/scoring/module_a..d` + `scorer` |
| 硬阀门 | 单体 `hard_triggers` | `core/scoring/hard_valves` |
| 资金路由 | 单体 `capital_route` | `core/routing/capital_routing` |
| 仓位 | `portfolio_target_weights_after_v25`(**v25 规则**) | `sizing_optimizer.optimize_targets`(凸优化) |
| 新风险/优化 | **shadow-only**(`use_portfolio_risk_budget=false`,仅记录不施加) | **决策主路径**(RiskEngine + 脊柱 + optimizer) |
| 关系 | 单体**完全不 import 包**,两套独立 | — |

**关键事实**:单体把新风险/优化器**以 shadow 方式**并行计算、只记录不施加;
包则把它们作为决策主路径。M4 = 把决策权从 v25 规则交给包的整合链。

## 1. Parity 差距分析(按功能域)

| 域 | 差距 | 严重度 | 说明 |
|---|---|---|---|
| 数据采集 | 低 | 🟢 | 单体 `collect` 写 store/`daily_raw_data`;包消费同一 store。可共用采集层,差距小。 |
| **评分** | **高** | 🔴 | 二者评分实现不同(golden 已显示 module B reason:单体 `daily=/weekly=` vs 包 `RSI14 overheat`)。points/校准可能有数值差。**必须逐因子对齐或显式接受差异**。 |
| 硬阀门 | 中 | 🟡 | 规则集相近(H-M/F/S 系列),但实现分立;阈值单体内联、包亦内联。需逐条比对触发条件。 |
| 资金路由 | 中 | 🟡 | DEFCON/destination 逻辑两套;需对齐 protocol_step、destination、sell_proceeds_pct。 |
| **仓位** | **高(设计差异)** | 🔴 | 单体 = v25 规则权重;包 = 凸优化(已验证 CAGR21.5%/MaxDD−25.6%/PBO0.077)。**这正是 M4 的核心收益,但也是最大行为变化**——需人审接受新仓位画像。 |
| 置信/风险 | 中 | 🟡 | 单体仅 shadow 记录;包作主决策(脊柱+RiskEngine)。切换=把 shadow 转正。 |
| 输出/审计 | 低 | 🟢 | 两套 schema 不同但都可序列化;需统一 WebUI/audit 读取键。 |

## 2. Parity 验收标准(翻 run_daily 前必须全绿)

构建 **parity harness**:对同一组冻结输入(`daily_raw_data` fixtures)同时跑单体 `score` 与包 `score_pipeline`,逐日逐标的比对:

1. [ ] **硬阀门**:`hard_valve_hits` 集合逐日逐标的完全一致(安全关键,必须 100%)。
2. [ ] **状态/减仓**:`status` 与 `sell_pct` 一致,或差异有书面归因且人审接受。
3. [ ] **资金路由**:`destination` / `protocol_step` 一致或归因接受。
4. [ ] **评分**:`total_score`/`calibrated_score` 差异 ≤ 阈值(如 ≤2 分)且不翻转任何决策。
5. [ ] **仓位**:接受新优化器画像(已过全窗口+PBO);记录与 v25 权重的差异分布。
6. [ ] **不变式**:R3 OOS 100%;只读红线;缺数据→低 confidence。
7. [ ] 全窗口回测 + 全网格 PBO 在**包主路径**下重跑通过(已具备,见 B 重验证)。

## 3. 迁移工单(依赖序)

- **T1 数据层统一**:确认包 `MarketData/store` 读的就是单体 `collect` 写的产物;消除任何二次采集。
- **T2 评分对齐**:逐因子比对单体 vs 包(A/B/C/D),产出差异表;对齐或书面接受。**(最大工作量)**
- **T3 硬阀门比对**:逐条 H-* 触发条件等价性证明 + 测试。
- **T4 路由比对**:DEFCON/destination 等价性。
- **T5 parity harness**:固定 fixtures 上跑双系统 diff,纳入 CI,达成 §2 标准。
- **T6 影子并行期**:用包主路径在 shadow 跑 N 个交易日,与单体决策逐日比对,人工复核。
- **T7 人工翻闸**:满足全部 §2 后,由**人**把 `run_daily` 从单体改为包;保留单体一键回滚。

## 4. 风险与回滚

- **最大风险**:仓位从 v25 规则 → 凸优化是实质行为变化(虽已回测/PBO 验证);需人审接受新画像。
- **回滚**:`run_daily` 改回 `from escape_top_system import main` 即可秒级回退;迁移期单体代码保留不动。
- **红线**:T7 翻闸是**唯一**改变生产行为的步骤,必须人工执行;此前所有工作均不碰生产。

## 5. 本轮已就绪的前置条件

- ✅ 包主路径已修复并三重验证(单元 322/0 + 真实数据 smoke + 全窗口回测 R3=0/errors=0)。
- ✅ 候选 110/0.90 过 PBO 门(train-greedy 0.077)。
- ✅ B 数值稳健已落地且重验证(画像不变)。
- ✅ 回归守门测试到位(`test_review_invariants.py`)。
- ⏳ 待办:T1–T6(本计划),然后 T7 人工翻闸。

> **结论**:M4 切换的"地基"已稳(包已验证)。剩下是 **parity 对齐(T1–T6)** 的工程活,
> 完成并人审后,T7 由你翻闸。我不会替你翻。下一步可从 **T5 parity harness** 入手——
> 它能立刻量化"今天两套系统差多远",为 T2–T4 的对齐提供清单。要我先建 T5 吗?
