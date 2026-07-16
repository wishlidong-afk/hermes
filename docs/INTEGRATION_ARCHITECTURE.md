# INTEGRATION ARCHITECTURE — 函数级施工规格

> 把 30 轮复盘成果（E1–E30）系统化整合为：**1 条置信脊柱 + 4 个共享引擎 + 1 个统一仓位优化器 + 治理层**。
> 本文件是交给 Codex 的施工蓝图。命名约定：散文中文，标识符英文。所有引擎默认 `offline_replay_mode` 兼容、确定性、无前视。
> 配套：`SYSTEM_OVERVIEW.md`（全景）、`ENHANCEMENTS.md`（E1–E30 明细）、`BUILD_TICKETS.md`（NEXT-0~6 基线工单）。

---

## 0. 执行总则

- 顺序：**先建地基（脊柱+4引擎+优化器骨架），再把 E1–E30 作为插件接入**。严禁先堆功能。
- 每个组件：先定 `dataclass` 契约 → 再写纯函数 → 再写单测 → 再接 pipeline。
- 全局不变式：①不下单；②缺数据→missing 不补 0；③`v3_target ≤ rule_verdict_target`(R3)；④同输入逐位一致。
- 依赖底线：numpy/pandas 必有；scipy/sklearn 可选，缺失要有手写回退（下文每处标注）。

### 整合的核心洞察（为什么必须先建地基）

若把 E1–E30 当 30 个独立模块各自搭，会得到：
1. 一条 `目标 = 基准 × scaler1 × … × scaler10` 的乘法链（顺序敏感、重复计数、无可行性保证）；
2. 多套互相打架的协方差估计（E4 一个、E11 一个、E13 一个）；
3. 散落各处、无人仲裁的"置信"信号（E1/E9/E10/E28）。

整合的目的就是消灭这三种混乱：**单一风险源、单一处置入口、单一置信仲裁**。

---

## 1. 公共数据契约（`core/contracts.py`，所有引擎共享）

```python
@dataclass(frozen=True)
class Field:
    name: str; value: float | None; source: str; as_of: date | None
    is_proxy: bool = False; latency_days: int = 0; quality_penalty: float = 0.0

@dataclass
class Verdict:                      # 来自 decision/verdict.py（既有）
    symbol: str; status: str        # HOLD..EXIT
    rule_target_weight: float       # 规则裁决后的目标袖珍权重（R3 上界）
    sell_fraction: float; hard_valve_hits: list[str]

@dataclass
class ConfidenceState:
    decision_confidence: float      # [0,1]，1=最可信
    mode: str                       # NORMAL/CAUTION/DEGRADED
    components: dict[str, float]; weakest_link: str; notes: list[str]

@dataclass
class RiskState:
    cov: "np.ndarray"; corr: "np.ndarray"; downside_corr: "np.ndarray"
    leg_vol: dict[str, float]; legs_used: list[str]; legs_reported: list[str]
    portfolio_vol: float; cvar: float
    vol_budget: float; cvar_budget: float
    vol_scaler: float; cvar_scaler: float; gross_scaler: float
    risk_contributions: dict[str, float]
    factor_betas: dict[str, dict[str, float]]; book_factor_exposure: dict[str, float]
    corr_regime: str; binding: str; explain: list[str]; estimator_meta: dict

@dataclass
class SizingDecision:
    target_weights: dict[str, float]; binding_constraint: dict[str, str]
    execution_plan: list[dict]; expected_utility: float
    confidence_applied: float; notes: list[str]
```

---

## 2. 脊柱 · ConfidenceSpine（`core/confidence/spine.py`）

吸收 E1/E9/E10/E28/E30。**全系统唯一的"可信度仲裁者"。**

### 2.1 函数
```python
def compute_confidence(
    data_conf: float,          # E1 净化置信 [0,1]
    failover_state: dict,      # E30: {is_degraded, active_source_rank}
    staleness_days: int,       # 最新数据距 as_of 天数
    drift_state: dict,         # E9: {psi, live_precision, ic_decay, alert:bool}
    fragility: float,          # E28 决策脆弱度 [0,1]，1=极脆
    disagreement: float,       # E10 多源分歧 [0,1]，1=强分歧
    cfg: dict,
) -> ConfidenceState
```

### 2.2 逻辑（逐步）
1. 各子项归一到健康度∈[0,1]（1=好）：
   - `c_data = data_conf`；`c_src = 0.7 if failover_state.is_degraded else 1.0`
   - `c_stale = exp(-staleness_days / cfg.tau_stale)`（默认 τ=3）
   - `c_drift = 0.0 if drift_state.alert else 1 - clip(drift_state.psi/0.25,0,1)`
   - `c_frag = 1 - fragility`；`c_agree = 1 - disagreement`
2. `components = {data,src,stale,drift,frag,agree}`；`weakest_link = argmin`。
3. 木桶加权：`confidence = w_min*min(components) + (1-w_min)*geomean(components)`，`w_min=cfg.weakest_weight`(默认0.6)。
4. mode：`>=normal(0.8)→NORMAL`；`>=caution(0.55)→CAUTION`；否则 `DEGRADED`。
5. DEGRADED → notes 追加"需人确认"。

### 2.3 边界 / 测试 / 验收
- 边界：任一子项缺失→该项记 0.5 并 note，不抛异常。
- 测试：四类注入（坏数据/漂移/强分歧/高脆弱）各自压到对应 mode；全健康→NORMAL≈1。
- 验收：每条决策携带 ConfidenceState；硬阀门触发 K 线被 E1 标 suspect 时 `c_data` 低且硬阀门转"待确认"。

---

## 3. 引擎1 · RiskEngine（`core/portfolio/risk_engine.py`）

吸收 E4/E5/E11/E13/E14。**全系统唯一协方差源。**

### 3.1 子函数
```python
def har_rv_forecast(returns, cfg) -> float
def ewma_corr_forecast(returns_df, lam=0.94) -> "np.ndarray"
def ledoit_wolf_shrink(corr, n_obs) -> "np.ndarray"          # sklearn 优先，缺则手写
def downside_corr(returns_df, q=0.10) -> "np.ndarray"
def portfolio_cvar(weights, returns_df, alpha=0.95, method="historical") -> float
def risk_contribution(weights, cov) -> dict[str, float]
def book_factor_beta(leg_returns, factor_returns, weights) -> tuple[dict, dict]
def build_risk_state(leg_returns, target_weights, factor_returns, cfg) -> RiskState
```

### 3.2 逻辑（逐步）
1. `legs_reported` = 历史≥`min_periods(40)` 的腿；`legs_used` = 其中 `target_weight>0`（硬阀门腿排除 gross，仍 reported）。
2. 边际波动：每腿 `σ_i = har_rv_forecast(各自最长历史)`（E5）；样本不足回退 EWMA。
   - HAR-RV：`RV_{t+1}=β0+β_d·RV_d+β_w·mean(RV,5)+β_m·mean(RV,22)`，`np.linalg.lstsq` 拟合；年化 `σ=sqrt(252·RV̂)`。
3. 相关：`R = ledoit_wolf_shrink(ewma_corr_forecast(公共窗口), n)`（E11+收缩）；公共样本<40→`corr_regime=UNKNOWN`、R 退化保守。
4. `cov = D R D`（`D=diag(σ)`）。
5. 下行相关（E4）：`downside_corr(returns, q=0.10)`；`corr_regime` 用下行相关的滚动分位（ELEVATED≥80 / EXTREME≥92）。
6. `portfolio_vol = sqrt(wᵀ cov w)`（w=legs_used 绝对袖珍权重）。
7. CVaR（E4）：历史法 `mean(组合收益 | ≤VaR_α)`；样本不足用 Cornish-Fisher（含偏度峰度）。
8. `vol_scaler = clip(vol_budget/portfolio_vol,0,1)`；`cvar_scaler = clip(cvar_budget/|cvar|,0,1)`；
   `gross_scaler = min(vol_scaler, cvar_scaler) × (extreme_corr_penalty if EXTREME else 1)`。
9. 风险贡献（E13）：`MCR=cov·w/portfolio_vol`，`RC_i=w_i·MCR_i`（Σ=portfolio_vol）。
10. 因子暴露（E14）：每腿对 `factor_returns`(BTC/半导体/巨头篮子) 回归求 β；`book_factor_exposure_f=Σ w_i β_{i,f}`；超阈标 `binding`。
11. 装配 RiskState，`binding` 标主约束（VOL/CVAR/EXTREME_CORR/CONCENTRATION/NONE）。

### 3.3 边界 / 测试 / 验收
- 边界：某腿无历史→reported 排除并 note；`portfolio_vol` 算不出→gross=1、`binding=INSUFFICIENT_DATA`，缺关键腿按盲区升级。
- 测试：高相关高波动→gross<1；零相关低波动→≈1；硬阀门腿排除 gross；下行相关>线性相关；RC 之和=portfolio_vol；book BTC 暴露聚合正确；HAR-RV 样本外 MSE<EWMA。
- 验收：**所有派生量引用同一 cov**（改一处全联动的一致性测试）。

---

## 4. 引擎2 · FactorLab（`core/factors/lab.py`）

吸收 E2/E3/E23。

### 4.1 函数
```python
def build_panel(replay_results) -> FactorPanel                  # date×factor_id 分数面板
def factor_ic(panel, fwd_outcome, method="spearman") -> dict
def cluster_and_prune(panel, ic, corr_threshold=0.8) -> dict     # factor→weight_multiplier
def calibrate_score(scores, fwd_dd, dd_threshold) -> "IsotonicMap"
def reliability_diagram(calib, scores, outcomes) -> dict          # 含 ECE
def feature_importance_stability(model, folds) -> dict            # SHAP；缺则 permutation 回退
```

### 4.2 逻辑
1. `build_panel`：从回测回放(NEXT-2)取每日每因子分数 → DataFrame。
2. `factor_ic`：因子分数 vs 未来回撤的 Spearman IC + t 统计；|IC|<ε 标 `dead`。
3. `cluster_and_prune`：相关距离层次聚类（scipy 优先，缺则相关阈值贪心分簇）；同簇保留 IC 最高者，其余 `multiplier<1`。
4. `calibrate_score`：保序回归(sklearn IsotonicRegression，缺则单调分桶平滑) 拟合 `P(回撤≥阈值|score)`；写 `config/artifacts/score_calib_vX.json`。
5. `feature_importance_stability`：元模型特征重要性跨 purged 折方差。

### 4.3 测试 / 验收
- 测试：两高相关因子→合计权重被压；零 IC→dead；保序性；ECE<阈值。
- 验收：产出 `Factor_Health.md`（IC/t/簇/建议）；verdict 阈值改概率驱动后达标门不退化。

---

## 5. 引擎3 · MarketContext（`core/features/context.py`）

吸收 E7/E16/E17/E18/E19/E20。**多标的×多周期共享访问层。**

### 5.1 类与插件
```python
class MarketContext:
    def __init__(self, as_of, store, cfg): ...
    def daily(self, sym) -> "pd.DataFrame"          # ≤as_of
    def weekly(self, sym) -> "pd.DataFrame"          # resample 'W-FRI'
    def leader_of(self, sym) -> str                  # BTC-USD→MSTR 等映射

def regime_with_transition(ctx, cfg) -> dict          # E7: label + P_transition(BOCPD)
def weekly_alignment(ctx, sym) -> dict                # E16
def lead_lag_signal(ctx, leader, target, max_lag=5) -> Field   # E17
def cross_sectional_rs(ctx, sleeves) -> dict          # E18
def divergence_score(ctx, sym, confirmers) -> Field   # E19
def vrp_and_jump(ctx, sym) -> dict                    # E20
```

### 5.2 逻辑要点
- `regime_with_transition`：确定性桶 + BOCPD"近 k 日转换概率" + 跨资产(HY OAS/MOVE/VIX 期限)投票。
- `weekly_alignment`：周线 EMA/RSI/MACD；升级需日线+周线同向。
- `lead_lag_signal`：领先资产滞后互相关；领先先破 EMA/MA → target 提前加分。
- `cross_sectional_rs`：三腿 RS 排名 → 供优化器"先砸最弱腿"。
- `divergence_score`：价格新高但确认篮子(宽度/CMF/龙头/AVWAP)未跟随 → 背离强度。
- `vrp_and_jump`：`VRP=IV−RV`；跳跃 `jump=max(RV−BV,0)`(bipower variation)。

### 5.3 测试 / 验收
- 每插件独立单测；转换概率在历史拐点前抬升。
- 验收：换手/打脸次数下降而 Calmar 不退化；领先腿先破时 target 提前响应。

---

## 6. 引擎4 · ValidationHarness（`core/backtest/harness.py`）

吸收 E21/E22/E23/E24。

### 6.1 函数
```python
def run_validation(strategy_fn, data, validators, cfg) -> "ValidationReport"
def cpcv_splits(t_events, n_groups=6, n_test=2, embargo_pct=0.02, label_horizon=20) -> list
def prob_backtest_overfitting(is_perf, oos_perf) -> float        # PBO
def stationary_block_bootstrap(returns, expected_block=20, n=2000) -> dict
def adversarial_auc(train_X, live_X) -> float
def augment_crashes(history, crash_windows, n, block_len=10) -> "SyntheticSet"
```

### 6.2 逻辑要点
- `cpcv_splits`：组合式 purged CV，清洗标签窗口重叠 + embargo。
- `prob_backtest_overfitting`：IS 最优配置在 OOS 跑输中位数的频率（logit 法）。
- `stationary_block_bootstrap`：平稳块重采样 → Calmar/MaxDD/Sortino 95% CI。
- `adversarial_auc`：分类器区分 train vs live，AUC≈0.5 健康、→1 漂移。
- `augment_crashes`：崩盘片段块自助合成，带 `is_synthetic`，不入 OOS。

### 6.3 验收
- 入档参数 PBO<0.5；关键指标带自助 CI（跨0判不显著）；对抗 AUC 越阈阻断元模型；合成不泄漏 OOS。

---

## 7. 核心 · SizingOptimizer（`core/portfolio/sizing_optimizer.py`）

吸收 E6/E8/E12/E15/E25/E26/E27。**唯一处置入口，取代所有 scaler 乘法链。**

### 7.1 函数
```python
def expected_leg_return(sym, ctx, risk_state, cfg) -> float       # 含 E6 衰减折减、E26 Kelly 倾斜
def liquidity_cap(sym, adv20, price, netliq, cfg) -> float         # E12
def cppi_exposure_cap(equity, floor, multiplier) -> float          # E15
def dd_averse_utility(w, mu, cov, dd_aversion) -> float            # E25
def optimize_targets(verdicts, risk_state, confidence, ctx, cfg) -> SizingDecision
```

### 7.2 逻辑（核心，逐步）
1. 决策变量 `w_i ≥ 0`（每腿袖珍权重）。
2. 目标：`maximize U(w)=Σ w_i·mu_i − λ_dd·downside_risk(w)`，
   - `mu_i = expected_leg_return`（净化掉杠杆衰减 E6：`mu_i -= 0.5·L(L-1)·σ_i²·hold_days`；按 E26 分数 Kelly `× kelly_frac(p_act, ci)`）。
   - `downside_risk(w)=sqrt(wᵀ cov w)` 或 CVaR。
3. 约束（可行域）：
   - R3 硬约束：`w_i ≤ verdicts[i].rule_target_weight`
   - 波动：`sqrt(wᵀcov w) ≤ vol_budget`；CVaR：`portfolio_cvar(w) ≤ cvar_budget`
   - 流动性：`w_i ≤ liquidity_cap_i`
   - CPPI：`Σ w_i·netliq ≤ cppi_exposure_cap`
   - 置信收缩：`w_i ≤ rule_target_i × confidence.decision_confidence`
   - 横截面(E18)：减仓优先压 RS 最弱腿（目标偏好项或后处理）
4. 求解：3 腿低维 → scipy.optimize(SLSQP) 优先；**无 scipy 回退**：可行域细网格 + 投影（确定性）。
5. 不可行 → 取最保守可行解（趋向现金/floor）；`binding_constraint` 标每腿绑定约束。
6. 执行计划(E8)：非硬阀门→分 N 日/TWAP 切片；硬阀门→`execute_now`；税务(E27)做批次/时点 tie-break；输出只读 `execution_plan`。
7. 返回 SizingDecision。

### 7.3 边界 / 测试 / 验收
- 边界：confidence 极低→w 大幅收缩；某腿数据缺→不增仓。
- 测试：①R3 不变式 `w_i ≤ rule_target_i` 100%；②高波动→更低 w；③不可行→最保守解；④binding 正确；⑤无 scipy 网格解与 SLSQP 解一致(容差内)。
- 验收：系统中不再出现手工 scaler 连乘；每个目标仓位报告绑定约束；回测风险调整收益不低于旧乘法链且更稳。

---

## 8. Governance（`core/governance/`）

吸收 E10/E28/E29（接脊柱）。

```python
def detect_disagreement(rule_status, meta_p_act, mirror_cycle, cfg) -> float   # E10 [0,1]
def decision_fragility(snapshot, scorer, eps=0.02, n_perturb=20) -> float        # E28 [0,1]
def attribute(score_result) -> list[tuple[str, float, float]]                    # 因子贡献+留一反事实
class ChampionChallenger:                                                        # E29
    def ensemble_decision(self, configs, snapshot) -> dict
    def evaluate_promotion(self, oos_window) -> dict                             # 晋升建议(人 gate)
```
- `decision_fragility`：输入±ε、阈值±δ 扰动 n 次，统计翻转频率。
- `detect_disagreement`：三源映射同一风险刻度，差异>阈值→REVIEW_REQUIRED。
- 这两者+drift → 喂 ConfidenceSpine；脊柱 DEGRADED → 保守模式 + 要求人确认。
- 验收：每决策可归因；强分歧/低置信进熔断；集成版跨折方差优于单配置；晋升需人 gate。

---

## 9. 集成接线（改造每日 pipeline）

> 生产评分入口唯一属于 `hermes_escape_top/pipeline.py`。下列整合架构的组件级 harness 已隔离到 `core/research/integration_pipeline.py`；`core/pipeline.py` 仅为退役兼容 shim，不得作为 daily/Web/CLI 生产入口。

```python
# core/research/integration_pipeline.py::score_pipeline(as_of)  # research only
ctx   = MarketContext(as_of, store, cfg)                       # 引擎3
snaps = build_snapshots(as_of, store, cfg)                     # 含 E1 净化 + E30 故障转移 → data_conf
scores= score_all(snaps, ctx, factorlab_calib)                # 评分(FactorLab 校准+去冗余权重)
verds = verdict_all(scores)                                    # 初步裁决(硬阀门优先)
risk  = build_risk_state(leg_returns,
            {s:v.rule_target_weight for s,v in verds}, factors, cfg)   # 引擎1
frag  = {s: decision_fragility(snaps[s], scorer) for s in syms}        # E28
disg  = {s: detect_disagreement(verds[s].status, meta_p_act[s],
            mirror_cycle[s], cfg) for s in syms}                       # E10
conf  = compute_confidence(data_conf, failover, staleness, drift_state,
            max(frag.values()), max(disg.values()), cfg)               # 脊柱
sizing= optimize_targets(verds, risk, conf, ctx, cfg)                  # 优化器(R3)
route = capital_routing(verds, risk, ctx, cfg)
audit_log(as_of, snaps, scores, verds, risk, conf, sizing, route, attribute(scores))
```

数据流一句话：**净化/故障转移 → 评分(校准/去冗余) → 裁决(硬阀门) → 单一风险引擎 → 脆弱/分歧 → 置信脊柱 → 统一优化器(R3) → 路由 → 审计**。

---

## 10. 配置增量（config.json）

```json
"confidence": {"tau_stale":3,"weakest_weight":0.6,"normal":0.8,"caution":0.55},
"risk_engine": {"vol_model":"har_rv","corr_model":"ewma","ewma_lambda":0.94,
                "min_periods":40,"cvar_alpha":0.95,"vol_budget_annual":0.35,
                "cvar_budget":0.08,"extreme_corr_penalty":0.7,
                "downside_q":0.10,"concentration_cap":{"BTC":0.5}},
"sizing": {"dd_aversion":3.0,"kelly_fraction":0.3,
           "leverage_L":{"FNGU":3,"SOXL":3,"MSTR":1},
           "solver":"slsqp_or_grid","exec_slices":3},
"governance": {"disagreement_threshold":0.4,"fragility_eps":0.02,
               "fragility_perturb":20,"degraded_requires_human":true},
"validation": {"cpcv":{"n_groups":6,"n_test":2,"embargo_pct":0.02},
               "pbo_max":0.5,"bootstrap_n":2000,"adversarial_auc_max":0.65}
```

---

## 11. Phase 0–IV 实施次序（含交付物）

| 阶段 | 内容 | 交付物 |
|---|---|---|
| **0 输入护栏** | E1 净化 + E30 故障转移 → data_conf | `sanitize.py/failover.py` + 净化/降级测试 |
| **I 地基** | ConfidenceSpine / RiskEngine / FactorLab / MarketContext / ValidationHarness 骨架 + 公共契约 | 各引擎空跑 + 契约测试 |
| **II 风险与信号** | E4/E5/E11/E13/E14→RiskEngine；E2/E3/E23→FactorLab；E7/E16/E17/E18/E19/E20→MarketContext | `Factor_Health.md` + 风险一致性测试 |
| **III 统一处置** | 建 SizingOptimizer，吸收 E6/E8/E12/E15/E25/E26/E27；删除所有旧 scaler 链 | R3 100% 测试 + 旧/新对照回测 |
| **IV 验证与治理** | E21/E22/E23/E24→Harness；E9/E10/E28/E29→脊柱/Governance | PBO/CI/对抗报告 + 熔断测试 |

---

## 12. 系统级验收标准（整合成功的 7 道总闸）

1. **单一风险源**：仅一个 `cov`；vol/CVaR/贡献/暴露皆派生且一致（改一处全联动）。
2. **单一处置入口**：无任何手工 scaler 连乘；目标仓位全来自 `optimize_targets` 且报 `binding_constraint`。
3. **R3 不变式**：任一 OOS 日 `w_i ≤ rule_target_i`，100%。
4. **置信脊柱贯通**：每决策带 `decision_confidence+mode`；四类异常正确降级 DEGRADED。
5. **防过拟合闸门**：入档参数 PBO<0.5；指标带自助 CI；对抗 AUC≤阈。
6. **因子健康**：有 `Factor_Health.md`；冗余降权+死因子剪枝生效；分数已概率校准(ECE 达标)。
7. **可解释可治理**：每决策可归因；强分歧/低置信进熔断；冠军-挑战者晋升需人 gate。

---

## 13. 测试矩阵（每组件四类必测）

| 组件 | 正常 | 缺数据 | 边界/极端 | 一致性/不变式 |
|---|---|---|---|---|
| ConfidenceSpine | NORMAL≈1 | 子项缺→0.5+note | 四类异常→DEGRADED | 木桶单调 |
| RiskEngine | 合理 cov | 腿缺→排除 | 高相关→gross<1 | 派生量同源一致 |
| FactorLab | IC 合理 | 样本少→标注 | 高相关→降权 | 保序性 |
| MarketContext | 提前量 | 周线缺→降级 | 拐点→转换概率↑ | 无前视 |
| Harness | 指标+CI | — | 注入过拟合→PBO高 | 合成不入OOS |
| SizingOptimizer | 最优可行 | 腿缺→不增 | 不可行→最保守 | R3 100% |
| Governance | 一致 | — | 强分歧→REVIEW | 熔断触发正确 |

---

*维护：每完成一个 Phase，更新对应组件状态与系统级 7 道闸的通过情况，与 `SYSTEM_OVERVIEW.md`、`STATUS.md` 对账。*
