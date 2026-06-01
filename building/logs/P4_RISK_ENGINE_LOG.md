# P4 RiskEngine 骨架执行日志

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` §3 (引擎1 · RiskEngine) 的要求，构建全系统唯一的协方差源。吸收 E4/E5/E11/E13/E14，使所有下游 vol/CVaR/风险贡献/因子暴露派生量共享同一个 cov 矩阵。

## 已完成实现

### 1. 核心模块 `core/portfolio/risk_engine.py`

**E5 HAR-RV 波动预测**
- `har_rv_forecast(returns, cfg) -> float`
- 实现 HAR-RV: `RV_{t+1} = b0 + b_d*RV_d + b_w*mean(RV,5) + b_m*mean(RV,22)`
- OLS 拟合 (`np.linalg.lstsq`)
- 样本不足（< har_min_obs=66）自动回退 EWMA

**E11 动态相关预测 + 收缩**
- `ewma_corr_forecast(returns_df, lam=0.94) -> np.ndarray`
- `ledoit_wolf_shrink(corr, n_obs) -> np.ndarray`
- sklearn LedoitWolf 优先；import 失败时使用手写 off-diagonal shrinkage fallback
- 确保对角线恒为 1.0

**E4 尾部相关 + CVaR**
- `downside_corr(returns_df, q=0.10) -> np.ndarray`：左尾 exceedance 相关
- `portfolio_cvar(weights, returns_df, alpha=0.95, method="historical") -> float`：历史 CVaR + Cornish-Fisher fallback

**E13 边际风险贡献**
- `risk_contribution(weights, cov) -> dict`
- `MCR = cov @ w / portfolio_vol`；`RC_i = w_i * MCR_i`
- 验证：`sum(RC) == portfolio_vol`

**E14 因子暴露**
- `book_factor_beta(leg_returns, factor_returns, weights) -> (leg_betas, book_exposure)`
- 每腿对因子 OLS 回归求 β；book_exposure = Σ w_i * β_{i,f}

**主装配函数**
- `build_risk_state(leg_returns, target_weights, factor_returns, cfg) -> RiskState`
- 单入口：legs_reported/legs_used 筛选 → HAR-RV vol → EWMA+LW corr → D R D cov → downside corr → corr regime → portfolio vol → CVaR → scalers → risk contribution → factor betas → binding constraint
- Insufficient data fallback: gross=1, binding=INSUFFICIENT_DATA
- EXTREME corr regime: 额外 penalty
- Concentration cap 检测

### 2. 测试 `tests/test_risk_engine.py`

| 测试 | 覆盖 |
|---|---|
| HAR-RV 返回正 vol | 正常 |
| 短序列回退 EWMA | 缺数据 |
| 无相关→近单位阵 | 正常 |
| 高相关被检测 | 边界 |
| LW 收缩向 identity | 正常 |
| 下行相关 ≥ 线性相关 | 边界 |
| CVaR < 0 | 正常 |
| RC 之和 = portfolio_vol | 一致性/不变式 |
| 因子 β 聚合正确 | 一致性 |
| 正常返回合理 state | 正常 |
| 高波动 → gross < 1 | 边界 |
| 数据不足 → fallback | 缺数据 |
| 零权重腿排除 used 但保留 reported | 硬阀门腿 |
| 所有派生量共享同一 cov | 一致性 |
| 确定性：同输入两次相同 | 不变式 |

## 设计决策

1. **无 scipy 依赖**：cov/corr 全用 numpy；CVaR 的 Cornish-Fisher 用 math.erfinv；LW 收缩有手写 fallback。scipy 仅作可选加速。
2. **corr_regime 判定**：用下行相关 / 线性相关的比值百分位，而非绝对值，更鲁棒。
3. **gross_scaler 从不超过 1**：只减不增，保守原则。
4. **fallback 策略**：数据不足时 gross=1（不做激进缩放），binding 标 INSUFFICIENT_DATA，交由上层处理。

## 当前状态

P4 进入 `IN-PROGRESS / PHASE-I-RISK-ENGINE-DONE`。

ConfidenceSpine + RiskEngine 两个核心引擎已完成骨架。下一步：SizingOptimizer（唯一处置入口，取代 scaler 乘法链）。
