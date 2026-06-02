# Round 3 — 完成剩余项（drift 接线 / 回测验证 / Gate ① 定论）

> **日期：2026-06-02** ｜ 承接 `FIX_LOG_ROUND2.md` + `RUN_LOG_TESTS_ROUND2.md`
> 用户指示「全都做、修改完善到可用状态」。本轮把剩余三项推进到位或给出有据的定论。

---

## 1. 真实 drift 信号接线 ✅（替换占位）

`pipeline.py` 新增 `_drift_state(signal_journal_path, config)`：从 **signal journal**
(3888 条历史 `final_score`) 取"近 `drift_live_days` 日分布 vs 历史基线分布",经
`DriftMonitor.evaluate` 算 **PSI**，产出真实 `drift_state` 喂给置信脊柱。
- 样本不足(任一侧 <10)→ 返回 `{"psi":0,"alert":False}`(诚实的"暂无法评估",非伪造)。
- 任何异常 → fail-safe 健康默认。
- **真实数据验证**:`_drift_state` 实算 `psi=0.0`(分数稳定,无漂移,符合预期);
  接线后 pipeline confidence 仍 0.696、仓位正常 → 无回归。

## 2. failover 信号 —— 诚实保留默认 + 说明（不伪造)

排查 `core/data/adapters.py` / `store.py`:**数据层根本没有接入多源 failover**
(`FailoverSource` 类存在但 `collect_soft_data` 不走它,全仓无 `is_degraded`)。
故 `failover_state={"is_degraded": False}` 是**事实**("无降级机制/未检测到降级"),
不是占位糊弄。代码注释已写明:待数据层真正经 `FailoverSource` 路由后再接。

## 3. Phase II 全窗口回测 ✅（用 exact optimizer 跑我的修复)

`phase2_full_backtest_sensitivity.py --exact-optimizer --thresholds 110 --penalties 0.90`
全 2113 日(2018–2026),走**真实 `optimize_targets`**(我修过的路径):

| 指标 | Baseline(旧 size_portfolio 链) | **候选 110/0.90(我的 optimizer)** | 旧 P9 参考 |
|---|---:|---:|---:|
| CAGR | 18.13% | **21.47%** | 20.37% |
| MaxDD | −27.60% | **−25.57%** | −24.32% |
| Sharpe | 0.8818 | **1.0137** | ~1.0 |
| DSR | — | **0.9196** | — |
| **R3 violations** | — | **0** | 0 |
| **errors** | — | **0** | 0 |

**结论:修复后的处置层在全窗口上重现了此前验证过的 P9 风险/收益画像
(CAGR ~21%、MaxDD ~−25%、Sharpe ~1.0),且 R3=0、errors=0。**
之前"sizing 数学已变 → 旧回测失效"的担忧,经此次重跑**已消解**:新数与旧 P9 一致。

⚠️ 注意:本次只跑单场景(110/0.90),故报告里 `PBO=1.0` 是**单场景退化伪值**
(只有 1 个场景时它必然"排第一/低于中位"),**非真实过拟合信号**。真实 PBO 需跑
全网格(7×3 场景,exact 约 5 小时)。其余指标不受影响。

## 4. Gate ①（单一风险源)—— 定论:活路径已达成,旧引擎按设计保留

排查 `compute_portfolio_risk` 的依赖面后定论:

- **活的决策路径已是单一风险源**:sizing 的 gross/cov/上报全部来自 `RiskEngine`
  (`build_risk_state`);confidence 来自脊柱;旧 `compute_portfolio_risk` 在活路径里
  **不再参与决策**,仅剩 payload 展示 + 异常兜底。Gate ① 在决策上**已满足**。
- **旧引擎不能删**,因为它是**设计上的 baseline**:`run_full.py` / `phase2` 敏感性
  正是用"旧 size_portfolio 链"作对照基准,来证明新 optimizer 的改进(见 §3 的
  Baseline 列)。删了就没有对照基准了。它还被 `web/render.py`(展示)和
  `test_phase6_portfolio_risk.py`(7 处断言)使用。
- 因此:**旧引擎在 migration 正式验收(全网格 PBO + 人审)前应保留**,作为 shadow
  对照;正式退役是一次独立的、需重新验证的迁移,不该在本轮强行拆除而动摇已验证状态。

## 5. 遗留 `core/` 重复树 —— 不删(有据)

它只被 v25 golden(`test_v25_parity`,测独立单体 `scripts/escape_top_system.py`)使用,
而该 golden 是预存漂移、属另一 owner 的评分单体(见 `RUN_LOG_TESTS_ROUND2.md` §8)。
删它会移除 owner 可能仍需要的测试,超出本次 review 范围。

---

## 当前可用状态（总）

| 维度 | 状态 |
|---|---|
| 单元测试 | **315 passed / 1 failed**(唯一红 = 预存、无关的 v25 monolith golden) |
| 真实数据 smoke | confidence=0.696(非永久 DEGRADED)、仓位正常、drift PSI 实算=0 ✅ |
| 全窗口回测 | CAGR 21.47% / MaxDD −25.57% / Sharpe 1.01 / **R3=0 / errors=0** ✅ |
| Gate ④ 脊柱 | 接回 + data_conf/staleness/**drift** 真实信号 ✅(failover 待数据层) |
| Gate ① 单一风险源 | 活路径已达成 ✅;旧引擎按设计留作 baseline |
| 同步 | 修复已同步 repo `src/`;`.hermes` 实盘已落地并跑通 |

**系统处于可用、且经单元+真实数据+全窗口回测三重验证的状态。**

## 仍需人工 / 后续（诚实声明)

1. **全网格 exact PBO**(7×3,~5h)——得到有意义的过拟合指标(本轮单场景 PBO 是伪值)。
2. **v25 golden** —— owner 查 module B 评分漂移 + 修生成器滑动窗口,再有意识重生成。
3. **failover 真信号** —— 待数据层经 `FailoverSource` 路由。
4. **E7 fragility / E22 disagreement** —— 仍占位 0.0。
5. **旧引擎正式退役** —— migration 验收后单独迁移并重验证。
