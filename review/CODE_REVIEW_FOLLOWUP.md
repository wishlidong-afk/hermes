# Code Review Follow-up（独立代码审查补充）

> **审查日期：2026-06-02**
> **审查范围：** `building/source_snapshots/` 下全部 81 个 Python 文件，重点精读
> `P12_gate2_optimizer/pipeline.py`、`P5_phase2_shadow/.../risk_engine.py`、
> `P5_phase2_shadow/.../sizing_optimizer.py`、`P4_confidence_spine/.../spine.py`
>
> 本文是对 `docs/PROJECT_REVIEW_2026_06_02.md` 的**独立补充**，聚焦在原复盘
> **未覆盖、但逐行读代码后发现的更深层问题**。

---

## 核心结论（一句话）

项目护栏意识、验证严谨度、安全红线达到机构级水准；但**三条最重要的"整合成功
判据"——①单一风险源、②单一处置入口、④置信脊柱贯通——在当前最新 P12 pipeline
里都只是部分成立**。这些不是参数调优问题，而是**接线（wiring）问题**，且大多被
"16 个快照、两套 pipeline 并存"的仓库结构所掩盖。

---

## 一、🔴 高优先级：架构不变式在生产路径里未落地

### 1.1 置信脊柱（ConfidenceSpine）在 P12 pipeline 被完全旁路

`spine.py` 的 `compute_confidence()` 实现了完整的 6 分量架构（数据净化/故障转移/
漂移/脆弱/分歧），但**最新的 `P12_gate2_optimizer/pipeline.py` 根本没有 import 它**。

取而代之的是 `_optimize_sizing` 里的手搓单标量（`pipeline.py:253-267`）：

```python
conf_val = min(1.0, max(0.0, float(portfolio_risk.effective_gross_scaler)))
confidence = ConfidenceState(
    decision_confidence=conf_val,
    components={"gross": conf_val},   # ← 只有一个分量
    ...
)
```

**后果：** 数据净化、故障转移、漂移、脆弱、分歧这 5 路信号在生产路径里全丢。
**Gate ④「置信脊柱贯通」实际未达成。**

**修法：**

```python
# pipeline.py _optimize_sizing 里替换手搓逻辑
from hermes_escape_top.core.confidence.spine import compute_confidence

confidence = compute_confidence(
    data_conf=portfolio_risk.data_quality_score,      # 已有
    failover_state=portfolio_risk.failover_state,      # 已有
    staleness_days=portfolio_risk.staleness_days,      # 已有
    drift_state=portfolio_risk.drift_state,            # 已有
    fragility=None,                                    # 待接
    disagreement=None,                                 # 待接
    cfg=config.get("confidence", {}),
)
```

---

### 1.2 两套风险引擎并行，gross 被乘两次

`P12 pipeline.py` 同时运行：

- **旧引擎** `compute_portfolio_risk`（`:126`）→ `portfolio_risk.effective_gross_scaler`
- **新引擎** `build_risk_state`（`:245`）→ `risk_state.gross_scaler`

`sizing_optimizer.py:163-166` 中，upper_bounds 是两个 gross 的**连乘**：

```python
conf_factor      = confidence.decision_confidence    # = 旧引擎 gross
risk_gross_factor = risk_state.gross_scaler          # = 新引擎 gross
upper_bounds = rule_targets * conf_factor * risk_gross_factor
```

两个 gross 都由 vol/CVaR 预算驱动，来自**两套不同的协方差计算**，结果被连乘。
若两者均为 0.7，实际仓位被压到 0.49——**系统性过度保守，且违反 Gate ①「单一风险源」**。

**修法：** 让 `confidence.decision_confidence` 从真实脊柱的 6 分量输出；
`risk_state.gross_scaler` 只做风险预算截断。长期删掉 `compute_portfolio_risk`，
只保留 `RiskEngine`。

---

### 1.3 SizingOptimizer 实质退化——优化器近乎空转

`sizing_optimizer.py:177` 的 mu 代理：

```python
base_mu = vol_i * max(2.0, dd_aversion + 1.0)  # dd=3 → base_mu = 4 × vol_i
```

效用函数是 `U = w'μ − dd·√(w'Σw)`。每条腿边际收益 `μ_i = 4·vol_i` 恒大于边际风险
`dd·vol_i·corr ≤ 3·vol_i`，所以优化器**永远把每条腿顶到上界**。

SLSQP / grid 只在 vol 预算真正 binding 时才起作用；其余时候 `optimize_targets`
等价于 `min(rule_target × conf × gross, vol 可行)`——和它要取代的 scaler 连乘
**没有本质区别**，只是形式更复杂了。

**修法（三选一）：**

| 方案 | 说明 |
|---|---|
| A. 历史均值 | `base_mu = historical_mean_return` 用滚动 252 日均值 |
| B. CAPM | `base_mu = risk_free + beta × equity_premium` |
| C. 如实承认 | 如果暂时不接 mu，坦诚注释"当前等效于上界裁剪"，移除 SLSQP 复杂度 |

---

### 1.4 `ledoit_wolf_shrink` 的 sklearn 分支是错的

`risk_engine.py:113-118`：

```python
lw = LedoitWolf(assume_centered=True)
lw.fit(np.eye(corr.shape[0]))   # ← 在单位矩阵上 fit，不是真实数据！
shrinkage = lw.shrinkage_
```

`fit(np.eye(k))` 得到的 `shrinkage_` 与实际数据毫无关系；加上
`except (ImportError, Exception)` 静默吞掉所有错误，
装了 sklearn 时收缩强度是无意义值。

这个 bug 还间接**结构性地放大了 EXTREME_CORR 比率**：收缩后的 corr 分母偏小，
使比值恒偏高。

**修法：**

```python
def ledoit_wolf_shrink(corr: np.ndarray, n_obs: int) -> np.ndarray:
    # 删掉 sklearn 分支，只保留（并修正）手写收缩
    shrinkage = _lw_shrinkage_manual(corr, n_obs)
    target = np.eye(corr.shape[0])
    shrunk = (1.0 - shrinkage) * corr + shrinkage * target
    np.fill_diagonal(shrunk, 1.0)
    return shrunk
```

---

## 二、🟡 中优先级：文档声称「已吸收」但生产路径未接线

### 2.1 E12/E15/E26 三个增强是死代码

`sizing_optimizer.py` 定义了：

- `liquidity_cap()`（E12 流动性上限）
- `cppi_exposure_cap()`（E15 CPPI 暴露上限）
- `kelly_fraction()`（E26 分数 Kelly）

文件头写着 `Absorbs E6/E8/E12/E15/E25/E26/E27`，但 `optimize_targets()` 函数体
**一次都没调用**这三个函数。grep 全仓只有测试文件在调用它们。

**修法：**

```python
# optimize_targets() 里补接
liq_cap = liquidity_cap(adv20=..., price=..., netliq=..., cfg=sizing_cfg)
upper_bounds = np.minimum(upper_bounds, liq_cap)

kf = kelly_fraction(p_act=confidence.decision_confidence, payoff_ratio=2.0, frac=0.3)
upper_bounds = upper_bounds * kf
```

或在 docstring 里如实标注 `# TODO: E12/E15/E26 not yet wired`。

### 2.2 CVaR 约束在优化器里是「画饼」

`optimize_targets` docstring 列出 CVaR 为约束之一，但 `_solve_slsqp` 里
只有 vol 约束进了可行域：

```python
constraints=[{"type": "ineq", "fun": vol_constraint}]
# ← 没有 cvar_constraint
```

CVaR 预算 (`cvar_budget`) 被读取、被传入 `RiskState`，却从未被优化器执行。

---

## 三、EXTREME_CORR 的真正根因（比原复盘更深一层）

原复盘把 78% 占比归因为「阈值定太低」，但根因是
**分子分母用了不一致的估计量**（`risk_engine.py:373-377`）：

| 量 | 估计方式 | 方向偏差 |
|---|---|---|
| 分母 `corr_mean` | EWMA + Ledoit-Wolf 收缩后的 corr | 收缩把非对角拉向 0 → **偏小** |
| 分子 `downside_corr_mean` | `downside_corr()` 被 `np.maximum(corr, full_corr)` 做了全样本地板（`:161-163`）| **偏大** |

比值 `downside/linear × 100` 因此**结构性地恒 > 100**，阈值被迫一路抬到 110。

此外 `corr_regime_extreme_pctl` 命名是「百分位」，实际当成「比值×100」在用——
**命名本身有误导性**。

**修法：**

```python
# 分子分母用同一基础估计量
linear_corr_mean = _off_diag_mean(raw_corr)          # 未收缩 EWMA corr
downside_corr_mean = _off_diag_mean(dc_raw)           # 未加地板的下行 corr
ratio = downside_corr_mean / max(linear_corr_mean, 1e-6)

# 变量改名
cfg 键: corr_regime_extreme_ratio  # 去掉 pctl 误导
```

---

## 四、低优先级（技术债）

### 4.1 `risk_contribution` 键名在 ≥10 腿时会错位

```python
# risk_engine.py:263
return {f"leg_{i}": float(rc[i]) for i in range(len(w))}
```

返回的字典排序后再映射回标的（`:405`）：

```python
rc_named = {legs_reported[i]: v for i, (_, v) in enumerate(sorted(rc.items()))}
```

字典序下 `leg_10` 排在 `leg_2` 前面，≥10 腿时错位。现在 3 腿没问题，
但 L5 扩展标的时会踩坑。

**修法：** 直接用标的名作键 `{legs_reported[i]: float(rc[i]) ...}`，
去掉多余的 `leg_i` 中间键。

### 4.2 SLSQP 和 grid 失败时的回退值未校验 vol 可行性

```python
return upper * 0.3   # sizing_optimizer.py:290, 339
```

`upper * 0.3` 没做 vol 可行性检验，R3 守住但可能超 vol 预算。
应回退到 `upper * 0.0`（最保守）或至少检查后再返回。

### 4.3 冗余 import 和未使用变量

```python
# P12 pipeline.py:204（_optimize_sizing 函数内）
import math   # ← 函数内未使用

# pipeline.py:205 + 顶层 :22 重复 import size_portfolio
from .core.portfolio.sizing import size_portfolio  # fallback reference
```

---

## 五、修复优先级汇总

| 优先级 | 问题 | Gate/不变式 | 工作量 |
|---|---|---|---|
| **P0** | P12 pipeline 接回 `compute_confidence` | Gate ④ | 0.5 天 |
| **P0** | 去掉双 gross 连乘 | Gate ① | 0.5 天 |
| **P1** | 修 `ledoit_wolf_shrink` sklearn 死分支 | 协方差正确性 | 0.5 天 |
| **P1** | 修 mu 代理或坦诚简化优化器 | Gate ② | 1 天 |
| **P1** | EXTREME_CORR 分子分母统一 + 改名 | 阈值合理性 | 0.5 天 |
| **P2** | E12/E15/E26 接线或标注 TODO | 文档=代码 | 1 天 |
| **P2** | CVaR 约束进可行域 | Gate ② | 0.5 天 |
| **P2** | 建 canonical `src/` 包，snapshots 降级归档 | 版本混淆 | 2-3 天 |
| **P3** | `risk_contribution` 用标的名作键 | ≥10 腿可扩展 | 0.5 天 |
| **P3** | SLSQP 回退加 vol 可行性检验 | 边界安全 | 0.5 天 |

**总估算：P0+P1 修复约 3 天工作量，可显著提升已验证的 Phase II/III 结论的可信度。**

---

> 本文档由独立代码审查生成，基于仓库快照（2026-06-02）。
> 如有疑问或发现遗漏，请在 GitHub Issue 或 Review 评论中反馈。
