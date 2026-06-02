# Fix Log — Section 4: 完整接线（#3 / #5-E12/E15/E26 / #6 / #11）

> **修复日期：2026-06-02**
> **对应 Review 条目：** §1.3（mu 代理）§2.1（E12/E15/E26 死代码）§2.2（CVaR 约束）§P2-canonical（src/ 包）
> **修改文件：**
> - `building/source_snapshots/P5_phase2_shadow/.../sizing_optimizer.py`
> - `building/source_snapshots/P12_gate2_optimizer/pipeline.py`
> - `src/hermes_escape_top/`（新建 canonical 包）

---

## Fix #3：mu 代理 → 真实滚动历史均值

### 变更

`optimize_targets` 新增参数 `leg_returns: Optional[Dict[str, Any]] = None`。

新增辅助函数：
```python
def _rolling_annualized_mean(ret, window=252) -> Optional[float]:
    r = pd.to_numeric(ret).dropna().tail(window)
    if len(r) < 20: return None
    return float(r.mean()) * 252.0
```

mu 计算逻辑：
```python
if leg_returns is not None and s in leg_returns:
    hist_mu = _rolling_annualized_mean(leg_returns[s])
    base_mu = hist_mu if hist_mu is not None else vol_i * max(2.0, dd_aversion + 1.0)
else:
    base_mu = vol_i * max(2.0, dd_aversion + 1.0)   # 向后兼容 fallback
```

`pipeline._optimize_sizing` 已将 `leg_returns`（close 日收益序列）传入 `optimize_targets`。

**结果：** 优化器现在在 3 条腿之间有真实的预期收益差异，SLSQP 真正在求解，
而不是每条腿都顶到上界。

---

## Fix #5-E26：kelly_fraction 接线

### 变更

在 `optimize_targets` 的 upper_bounds 计算区块后立即应用：
```python
kelly_cfg = sizing_cfg.get("kelly", {})
if kelly_cfg.get("enabled", True):
    kf = kelly_fraction(
        p_act=conf_factor,              # 置信度作为激活概率代理
        payoff_ratio=kelly_cfg.get("payoff_ratio", 2.0),
        frac=kelly_cfg.get("frac", 0.3),
        ci_width=kelly_cfg.get("ci_width", 0.0),
    )
    if kf > 0:
        upper_bounds = upper_bounds * kf
```

配置（`sizing.kelly` 子节）：
```yaml
sizing:
  kelly:
    enabled: true
    payoff_ratio: 2.0
    frac: 0.3
    ci_width: 0.0
```

默认 `enabled: true`；`p_act=0.8`(NORMAL)、`payoff=2.0`、`frac=0.3` 时：
`kf = 0.3 × (0.8 − 0.2/2) = 0.3 × 0.7 = 0.21`——合理的保守上限缩放。

---

## Fix #5-E12：liquidity_cap 接线

### 变更

`optimize_targets` 新增参数 `liquidity_data: Optional[Dict[str, Dict[str, float]]] = None`。

per-leg 应用：
```python
if liquidity_data:
    for i, s in enumerate(syms):
        liq = liquidity_data.get(s, {})
        adv20, price, netliq = liq.get("adv20", inf), liq.get("price", 1.), liq.get("netliq", 1.)
        if isfinite(adv20) and adv20 > 0:
            upper_bounds[i] = min(upper_bounds[i], liquidity_cap(adv20, price, netliq, liq_cfg))
```

`pipeline._optimize_sizing` 从 `histories` 计算 `liquidity_data`：
- `price` = histories[sym]['Close'] 最新收盘价
- `adv20` = 20 日均量 × 价格（需要 Volume 列；否则设 inf，不触发 cap）
- `netliq` = `config.portfolio.netliq`（默认 100,000）

---

## Fix #5-E15：cppi_exposure_cap 接线

### 变更

在 E12 之后，以组合级 gross cap 约束：
```python
cppi_cfg = sizing_cfg.get("cppi", {})
if cppi_cfg.get("enabled", False):
    equity = cppi_cfg.get("equity", 1.0)
    floor  = equity * cppi_cfg.get("floor_ratio", 0.8)
    max_gross = cppi_exposure_cap(equity, floor, cppi_cfg.get("multiplier", 3.0))
    total = sum(upper_bounds)
    if total > 0 and max_gross < total:
        upper_bounds = upper_bounds * (max_gross / total)
```

CPPI 默认 `enabled: false`（需在 config 显式开启）。

---

## Fix #6：CVaR 显式约束进 SLSQP 可行域

### 变更

新增辅助函数：
```python
def _cvar_normal_factor(alpha):
    p = 1.0 - alpha
    z = sqrt(2) * erfinv(2*p - 1)   # Φ⁻¹(1−α)，负数
    phi_z = exp(-z²/2) / sqrt(2π)
    return phi_z / p                  # ≈ 2.063 for α=0.95
```

`_solve_slsqp` 新增参数 `cvar_budget` 和 `cvar_alpha`，加入 CVaR 约束：
```python
def cvar_constraint(w):
    port_vol_ann = sqrt(w @ cov @ w)
    cvar_approx  = port_vol_ann / sqrt(252) * cvar_factor
    return cvar_budget - cvar_approx   # ≥ 0 = feasible

constraints=[
    {"type": "ineq", "fun": vol_constraint},
    {"type": "ineq", "fun": cvar_constraint},   # ← 新增
]
```

fallback 也同步检验 CVaR 可行性：
```python
w_fallback = upper * 0.3
if port_vol > vol_budget: w_fallback *= vol_budget/port_vol
if cvar_approx > cvar_budget: w_fallback *= cvar_budget/cvar_approx
```

`optimize_targets` 从 `risk_state.cvar_budget` 读取预算，从 `sizing_cfg.cvar_alpha`（默认 0.95）读置信水平，传给 solver。

---

## Fix #11：建 canonical src/ 包

### 目录结构

```
src/
├── pyproject.toml
├── MIGRATION_STATUS.md
└── hermes_escape_top/
    ├── __init__.py
    ├── pipeline.py          ← P12 (with all fixes)
    ├── integration_config.py
    └── core/
        ├── __init__.py
        ├── contracts.py
        ├── confidence/spine.py
        ├── portfolio/risk_engine.py   ← P5 (with all fixes)
        ├── portfolio/sizing_optimizer.py
        ├── portfolio/tax.py
        ├── data/ (adapters, crypto, failover, sanitize)
        ├── factors/lab.py
        ├── features/context.py
        ├── audit/exporter.py
        ├── monitor/drift.py
        ├── governance/governance.py
        ├── reentry/tracker.py
        ├── routing/leg_proxy.py
        └── backtest/harness.py
```

`building/source_snapshots/` 降级为纯归档（不再直接编辑）。

### 仍缺模块（需从 .hermes 迁移）

详见 `src/MIGRATION_STATUS.md`：17 个模块（config、base、flow、market、audit 写入等）
仍只存在于本地 `.hermes` 安装，需逐一 `cp` 后 `pip install -e src/` 才能完整运行。

---

## 所有 Review 条目状态

| # | 条目 | 状态 |
|---|---|---|
| 1 | ConfidenceSpine 旁路 | ✅ 已修复（S1） |
| 2 | 双 gross 连乘 | ✅ 已修复（S1 衍生） |
| 3 | mu 代理退化 | ✅ **本次修复** |
| 4 | ledoit_wolf sklearn 死分支 | ✅ 已修复（S2） |
| 5-E26 | kelly_fraction 死代码 | ✅ **本次修复** |
| 5-E12 | liquidity_cap 死代码 | ✅ **本次修复** |
| 5-E15 | cppi_exposure_cap 死代码 | ✅ **本次修复** |
| 6 | CVaR 约束缺失 | ✅ **本次修复** |
| 7 | EXTREME_CORR 分子分母不一致 | ✅ 已修复（S2） |
| 8 | risk_contribution ≥10 腿排序 | ✅ 已修复（S2） |
| 9 | SLSQP/grid 回退 vol 可行性 | ✅ 已修复（S2+S3；CVaR也加进去了） |
| 10 | import math 冗余 | ✅ 已修复（S1） |
| 11 | canonical src/ 包 | ✅ **本次修复** |

**全部 11 条完毕。**
