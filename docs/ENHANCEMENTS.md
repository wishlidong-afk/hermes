# ENHANCEMENTS — 进阶提升点 E1–E30（函数级工单）

> 30 轮复盘得到的 Tier-2/Tier-3 增强点。假设基线 NEXT-0~6 已完成（系统达 M3/M4）。
> 这些是"搭建完毕后"的提升项；整合方式见 `INTEGRATION_ARCHITECTURE.md`（30 条坍缩为 1 脊柱+4 引擎+1 优化器+治理）。
> 通用铁律：不下单 / 缺数据不补 0 / R3 不更激进 / 确定性 / offline 0 外呼 / 每单单测覆盖 ≥85%。

---

## Tier-2：E1–E10（安全·信号·风险建模·执行）

### E1 数据净化层（防假硬阀门）
- 文件：`core/data/sanitize.py::sanitize_ohlcv(df, cfg) -> (clean_df, anomalies)`；`hard_valves.py` 增 `data_confidence` 入参。
- 逻辑：拆股/复权一致性、坏 tick(无量+跨源不一致)、winsorize 标记、stale 检测、跨源校验；触发硬阀门的 K 线被标 suspect → 硬阀门降为"待确认"。
- 验收：历史所有硬阀门触发日无一来自 suspect K 线；真实暴跌(有量+跨源一致)不被抹掉。
- 提升：消除"数据 bug → 误砍仓"的尾部事故。

### E2 评分概率校准
- 文件：`core/backtest/score_calibration.py::fit_score_to_prob(...) -> IsotonicMap`；verdict 阈值改概率反解。
- 逻辑：(final_score, 未来H日最大回撤) 保序回归 `P(回撤≥阈值|score)`；用 purged 数据；输出可靠性图。
- 验收：保序性；ECE<阈值；阈值改概率驱动后达标门不退化。
- 提升：阈值从"玄学"变"统计"。

### E3 因子去相关 + IC 监控 + 剪枝
- 文件：`core/backtest/factor_health.py::factor_ic(...)`、`cluster_factors(...)`；scorer 加 `redundancy_weights`。
- 逻辑：因子 IC(Spearman)+t；层次聚类；同簇保留最高 IC、其余降权；|IC|<ε 标 dead。
- 验收：`Factor_Health.md`；高相关合计权重被压；死因子标记。
- 提升：去掉伪自信和死因子，减少假阳性。

### E4 尾部相关 + CVaR 组合预算
- 文件：`core/portfolio/tail_risk.py::downside_corr(...)`、`portfolio_cvar(...)`；risk_budget `gross=min(vol,cvar)`。
- 逻辑：下行(exceedance)相关；历史/Cornish-Fisher CVaR；相关性体制用下行相关分位。
- 验收：合成左尾共振→下行相关≫线性；崩盘段回撤更小。
- 提升：直击"三腿同向崩盘"的核心风险。

### E5 HAR-RV 波动预测
- 文件：`core/features/volatility.py::har_rv_forecast(returns, horizon)`；`features.vol_model: ewma|har_rv`。
- 逻辑：`RV_{t+1}=β0+β_d RV_d+β_w RV_w+β_m RV_m`，OLS(`np.linalg.lstsq`)；样本不足回退 EWMA。
- 验收：样本外 MSE<EWMA；vol 目标接入后 Calmar 不低于 EWMA。
- 提升：更准的前瞻波动 → 更早更平滑去杠杆。

### E6 杠杆衰减感知仓位
- 文件：`core/portfolio/leverage_decay.py::expected_decay_drag(L, daily_vol, holding_days)`；sizing 加 `decay_scaler`。
- 逻辑：`drag ≈ -0.5·L(L-1)·σ_daily²·days`；CHOP/HIGH_VOL 无趋势时对杠杆腿额外减仓。
- 验收：高波动无趋势→decay_scaler<1；2022 震荡段杠杆暴露下降、回撤改善。
- 提升：把杠杆 ETF 的慢性失血变成前瞻减仓依据。

### E7 体制集成 + 转换概率预警
- 文件：`core/features/regime_ensemble.py::bocpd_transition_prob(...)`、`regime_ensemble(...)`。
- 逻辑：确定性桶 + 可选 HMM + 变点(BOCPD)转换概率 + 跨资产(OAS/MOVE/期限)投票；P_transition 高→提前微调 A/C 权重(受上限约束)。
- 验收：历史拐点前 P_transition 抬升；崩盘前一周防守提前量 + 回撤改善。
- 提升：从反应式升级到预判式防守。

### E8 跳空风险 + 分批执行
- 文件：`core/features/gap_risk.py::gap_risk_score(...)`；`core/routing/execution_plan.py::build_execution_plan(...)`。
- 逻辑：隔夜收益分布 + 事件窗(财报/FOMC/BTC 到期)抬升风险；非硬阀门分批 TWAP，硬阀门 execute-now。
- 验收：财报前 gap_risk 抬升；硬阀门不分批；提前减仓标的跳空日损失更小。
- 提升：把"理想成交"修正为"现实成交"，堵隔夜跳空漏洞。

### E9 在线漂移监控 + 告警
- 文件：`core/monitor/drift.py`(psi/live_precision/ic_decay/quality_trend)、`alert.py::evaluate_alerts(...)`。
- 逻辑：PSI>0.25 告警；live 防守精度 vs 回测；因子 IC 衰减；越阈写审计+UI 红条+建议重校准。
- 验收：注入漂移→PSI 告警；注入精度下滑→触发重校准建议；WebUI"模型健康"面板。
- 提升：把"一次性校准"变成"持续可信"。

### E10 归因 + 分歧检测 + 治理熔断
- 文件：`core/explain/attribution.py::attribute(...)`、`disagreement.py::detect(...)`、`governance/circuit_breaker.py::evaluate(...)`。
- 逻辑：分数留一法归因；规则/元模型/镜像三源分歧>阈→REVIEW_REQUIRED；低质量/漂移/强分歧→DEGRADED 保守模式。
- 验收：每决策可归因；强分歧→REVIEW；低质量→DEGRADED。
- 提升：让系统会解释、会示弱、会喊停。

---

## Tier-3：E11–E30（五大方向）

### 方向 A 风险结构
- **E11 动态相关预测** `core/portfolio/dcc.py::ewma_corr_forecast(...)`：EWMA/DCC 前瞻相关；崩盘共振提前量↑。
- **E12 流动性调整仓位** `liquidity.py::days_to_liquidate(...)`、`liquidity_cap(...)`：`days=shares/(participation·ADV20)≤max_days` 反推上限；ETN issuer 容量。保证砍得掉。
- **E13 边际风险贡献** `risk_attrib.py::risk_contribution(...)`：`MCR=Σw/σ_p`，`RC_i=w_i MCR_i`；风险可定位。
- **E14 隐含因子暴露** `factor_exposure.py::book_factor_beta(...)`：账本对 BTC/半导体/巨头的聚合 β；揭穿伪分散。
- **E15 CPPI 地板** `cppi.py::cppi_exposure_cap(equity,floor,m)`：敞口≤m·(equity−floor)，floor 棘轮上移；绝对回撤保护。

### 方向 B 信号深化
- **E16 多周期确认** `multiframe.py::weekly_alignment(...)`：升级需日线+周线同向；减打脸。
- **E17 领先-滞后预警** `leadlag.py::lead_lag_signal(...)`：BTC→MSTR/SOX→SOXL/巨头→FNGU；早期预警。
- **E18 横截面 RS 轮动** `cross_section.py::rs_rank(...)`：减仓优先砸最弱腿；减谁更聪明。
- **E19 系统化背离检测** `divergence.py::divergence_score(...)`：价格新高但确认篮子未跟随；抓派发顶。
- **E20 VRP + 跳跃检测** `vol_premium.py::vrp(...)`、`jump.py::jump_component(...)`：隐含-已实现 + 连续-跳跃维度。

### 方向 C 验证严谨
- **E21 CPCV + PBO** `cpcv.py`、`pbo.py::prob_backtest_overfitting(...)`：量化过拟合，PBO>0.5 判过拟合。
- **E22 块自助 CI** `bootstrap.py::stationary_block_bootstrap(...)`：指标 95% CI；区分 edge 与运气。
- **E23 对抗验证 + SHAP 稳定性** `adversarial.py::adversarial_auc(...)`：证明 train≈now。
- **E24 稀有崩盘样本增强** `augment.py::block_bootstrap_crashes(...)`：扩充正样本(带 is_synthetic，不入 OOS)。

### 方向 D 仓位理论
- **E25 回撤厌恶效用目标** `utility.py::expected_utility(...)`、`optimize_weight(...)`：减仓有理论。
- **E26 分数 Kelly** `kelly.py::fractional_kelly(p_act, payoff, frac, ci_width)`：下注挂钩置信。
- **E27 税务/洗售感知** `tax.py::wash_sale_check(...)`、`tax_lot_optimize(...)`：税后真实收益(advisory)。

### 方向 E 稳健与运维
- **E28 决策脆弱度** `fragility.py::decision_fragility(snapshot, scorer, eps, n)`：扰动翻转频率；分辨刀尖决策。
- **E29 配置集成 + 冠军挑战者** `config_ensemble.py`、`champion_challenger.py`：不赌单参数+安全演进(人 gate)。
- **E30 数据源故障转移** `failover.py::FailoverSource(primary, backups)`：有序源+健康检查+自动切换+降级标注。

---

## 优先级与落地次序

| 分组 | 工单 | 价值 | 优先级 |
|---|---|---|---|
| 安全/鲁棒 | E1, E9, E10, E30 | 防偷袭/会自检/数据韧性 | ★★★ |
| 风险建模 | E4, E11, E14 | 崩盘共振/可定位/揭伪分散 | ★★★ |
| 执行确定 | E12 | 保证砍得掉 | ★★★ |
| 信号 | E7, E17 | 提前量 | ★★★ |
| 验证 | E21 | 量化过拟合 | ★★★ |
| 其余 | E2/E3/E5/E6/E8/E13/E15/E16/E18/E19/E20/E22/E23/E24/E25/E26/E27/E28/E29 | 质量/严谨/理论 | ★★ |

**建议次序**（在 NEXT-0~6 之后）：先安全三件套(E1/E30/E9) → 风险结构(E4/E11/E14/E12) → 预警与严谨(E17/E7/E21) → 其余按方向增强。整合落地走 `INTEGRATION_ARCHITECTURE.md` 的 Phase 0–IV。
