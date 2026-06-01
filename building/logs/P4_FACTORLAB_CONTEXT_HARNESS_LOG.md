# P4 FactorLab + MarketContext + ValidationHarness 执行日志

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` Phase I 要求，完成剩余三个共享引擎的骨架：FactorLab（引擎2）、MarketContext（引擎3）、ValidationHarness（引擎4）。

---

## 引擎2：FactorLab（`core/factors/lab.py`）

吸收 E2/E3/E23。因子健康监控 + 去冗余 + 概率校准。

### 已完成函数

| 函数 | 来源 | 功能 |
|---|---|---|
| `build_panel(replay_results)` | E3 | 回放结果 → date×factor_id 分数面板 |
| `factor_ic(panel, fwd_outcome, method)` | E3 | Spearman IC + t-stat；\|IC\|<0.02 标 dead |
| `cluster_and_prune(panel, ic_results, corr_threshold)` | E3 | 层次聚类去冗余；同簇保留最高 IC，余降权 0.3 |
| `calibrate_score(scores, fwd_dd, dd_threshold)` | E2 | 保序回归 P(回撤≥阈值\|score)；sklearn 优先，单调分桶 fallback |
| `reliability_diagram(calib, scores, outcomes)` | E2 | 可靠性图 + ECE |

### 测试（7 个）

- 面板构建正常 / 空输入
- 相关因子有正 IC / 死因子检测 / 数据不足
- 高相关因子权重被压 / 单因子
- 保序单调性 / 数据不足 fallback
- ECE 有界

---

## 引擎3：MarketContext（`core/features/context.py`）

吸收 E7/E16/E17/E18/E19/E20。多标的×多周期共享上下文层。

### 已完成函数

| 函数 | 来源 | 功能 |
|---|---|---|
| `MarketContext` 类 | - | daily(sym)、weekly(sym)、leader_of(sym)；无前视 |
| `regime_with_transition(ctx, sym, cfg)` | E7 | 确定性体制桶 + 转换概率 |
| `weekly_alignment(ctx, sym)` | E16 | 日线+周线趋势对齐检查 |
| `lead_lag_signal(ctx, leader, target, max_lag)` | E17 | 领先-滞后互相关 |
| `cross_sectional_rs(ctx, sleeves, window)` | E18 | 三腿 RS 排名 |
| `divergence_score(ctx, sym, confirmers, window)` | E19 | 价格新高但确认篮子未跟随 |
| `vrp_and_jump(ctx, sym, vix_sym, window)` | E20 | VRP=IV-RV；Jump=max(RV-BV,0) |

### 测试（10 个）

- daily 无前视 / weekly 重采样 / 缺失标的
- 体制返回有效标签 / 高波动检测
- 周线对齐返回 / 领先滞后 Field
- RS 排名 / 背离得分
- VRP/jump 组件

---

## 引擎4：ValidationHarness（`core/backtest/harness.py`）

吸收 E21/E22/E23/E24。防过拟合和鲁棒性验证。

### 已完成函数

| 函数 | 来源 | 功能 |
|---|---|---|
| `cpcv_splits(n_obs, n_groups, n_test, embargo_pct, label_horizon)` | E21 | 组合式 purged CV，清洗+embargo |
| `prob_backtest_overfitting(is_perf, oos_perf)` | E21 | PBO：IS 最优在 OOS 跑输中位数的频率 |
| `stationary_block_bootstrap(returns, expected_block, n, seed)` | E22 | 平稳块重采样 → Calmar/MaxDD/Sortino 95% CI |
| `adversarial_auc(train_X, live_X, seed)` | E23 | 分类器区分 train vs live；AUC≈0.5 健康 |
| `augment_crashes(history, crash_windows, n, block_len, seed)` | E24 | 崩盘块自助合成；标 is_synthetic |
| `run_validation(strategy_fn, data, cfg)` | - | 端到端验证 runner |

### 测试（11 个）

- CPCV 分割生成 / 训练测试无重叠 / purge 清洗相邻
- 随机 PBO 合理 / 完美 IS=OOS 则 PBO=0
- Bootstrap CI 有界 / 确定性 / 短序列
- 相同分布 AUC≈0.5 / 不同分布 AUC 高
- 崩盘增强生成 / 无窗口
- 端到端验证

---

## 当前状态

P4 Phase I 地基全部 6 个核心组件骨架完成：

| 组件 | 状态 |
|---|---|
| 公共契约 `contracts.py` | ✅ DONE |
| ConfidenceSpine `confidence/spine.py` | ✅ DONE |
| RiskEngine `portfolio/risk_engine.py` | ✅ DONE |
| SizingOptimizer `portfolio/sizing_optimizer.py` | ✅ DONE |
| FactorLab `factors/lab.py` | ✅ DONE |
| MarketContext `features/context.py` | ✅ DONE |
| ValidationHarness `backtest/harness.py` | ✅ DONE |

下一步：Phase 0 输入护栏（E1 净化 + E30 故障转移）或 Phase II 风险与信号接入。
