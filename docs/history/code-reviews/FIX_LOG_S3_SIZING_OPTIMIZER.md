# Fix Log — Section 3: SizingOptimizer 四处修复

> **修复日期：2026-06-02**
> **对应 Review 章节：** §1.3（mu 代理退化）+ §2.1（E12/E15/E26 死代码）+ §2.2（CVaR 画饼）+ §4.2（SLSQP 回退 vol 可行性）
> **修改文件：** `building/source_snapshots/P5_phase2_shadow/hermes_escape_top/core/portfolio/sizing_optimizer.py`

---

## 修复一：mu 代理退化——注释说明（Option C）

### 问题

```python
base_mu = vol_i * max(2.0, dd_aversion + 1.0)  # dd=3 → base_mu = 4 × vol_i
```

效用函数 `U = w'μ − dd·√(w'Σw)`，每条腿边际收益 `μ_i = 4·vol_i` 恒大于边际风险
`dd·vol_i·corr ≤ 3·vol_i`，所以 SLSQP 永远把每条腿顶到上界——等价于上界裁剪，
优化器的复杂度没有带来额外的信息量。

### 处理方式

本次选择 Option C（坦诚注释），不改变现有行为。理由：
- Option A（历史均值）需要 `leg_returns` 传入 `optimize_targets()`，改接口会波及 P5/P6 测试
- 现有上界裁剪行为是保守且正确的；vol budget binding 时 SLSQP 仍然有实质贡献
- 重要的是让读者知道这个限制，而不是隐藏它

添加的注释明确说明：
1. 当前 mu proxy 使优化器等价于上界裁剪
2. 何时 SLSQP 真正起作用（vol budget 紧时）
3. Option A 的接入路径（TODO 标记）

---

## 修复二：E12/E15/E26 死代码——标注 TODO

### 问题

`optimize_targets()` 的函数头注释写着 `Absorbs E6/E8/E12/E15/E25/E26/E27`，
但 `liquidity_cap()`（E12）、`cppi_exposure_cap()`（E15）、`kelly_fraction()`（E26）
在 `optimize_targets()` 函数体里**从未被调用**，只有测试文件在用它们。

### 处理方式

在上界计算后添加注释：

```python
upper_bounds = confidence_bounds * risk_gross_factor
# TODO: E12 liquidity_cap(), E15 cppi_exposure_cap(), E26 kelly_fraction()
# are defined in this module but not yet applied here. Wire them once ADV20,
# price, netliq, and equity/floor data are available from the pipeline caller.
```

不修改行为（函数仍然正确），但让读者清楚哪些是实现了但未接入的。

---

## 修复三：CVaR 约束在优化器里是「画饼」——标注 TODO

### 问题

`optimize_targets` docstring 列出 CVaR 为约束之一，但 `_solve_slsqp` 里
只有 vol constraint 进了可行域，CVaR constraint 完全缺失：

```python
constraints=[{"type": "ineq", "fun": vol_constraint}]
# ← 没有 cvar_constraint
```

CVaR 预算通过 `risk_state.cvar_scaler` 折算进了 `upper_bounds`（间接），但优化器
在 upper_bound 内部重新分配权重时可能突破 CVaR 约束。

### 处理方式

在 SLSQP constraints 参数处添加注释，说明：
1. CVaR 通过 `risk_state.cvar_scaler → upper_bounds` 间接执行
2. 显式 CVaR 约束缺失时优化器的潜在违规场景
3. 修复路径（正态近似 CVaR 约束）

---

## 修复四：SLSQP 和 grid 失败回退值未校验 vol 可行性

### 问题

```python
return upper * 0.3   # sizing_optimizer.py:290 (SLSQP 失败时)
# ...
best_w = upper * 0.3  # sizing_optimizer.py:339 (grid n>3 时)
```

`upper * 0.3` 没做 vol 可行性检验，R3 守住但可能超 vol 预算。

### 修复

两处回退均增加 vol 可行性缩放：

```python
# SLSQP 失败回退
w_fallback = np.clip(upper * 0.3, 0.0, upper)
vol_fb = math.sqrt(max(float(w_fallback @ cov @ w_fallback), 1e-12))
if vol_fb > vol_budget:
    w_fallback = w_fallback * (vol_budget / vol_fb)
return w_fallback

# grid n>3 回退
best_w = np.clip(upper * 0.3, 0.0, upper)
vol_fb = math.sqrt(max(float(best_w @ cov @ best_w), 1e-12))
if vol_fb > vol_budget:
    best_w = best_w * (vol_budget / vol_fb)
```

保持比例缩放而非直接归零（`upper * 0.0`），以保留相对配置方向。

---

## 变更摘要

| # | 位置 | 变更类型 | 影响 |
|---|---|---|---|
| 1 | `optimize_targets` mu 计算块 | 添加注释（Option C） | 仅文档，不改行为 |
| 2 | `optimize_targets` upper_bounds 之后 | 添加 E12/E15/E26 TODO | 仅文档，不改行为 |
| 3 | `_solve_slsqp` constraints 参数 | 添加 CVaR TODO | 仅文档，不改行为 |
| 4 | `_solve_slsqp` 回退路径 `:290` | 加 vol 可行性缩放 | 行为变更（边界安全） |
| 5 | `_solve_grid` n>3 回退 `:339` | 加 vol 可行性缩放 | 行为变更（边界安全） |

---

## 残余工作

| 项目 | 优先级 | 说明 |
|---|---|---|
| Option A: 历史均值 mu | P1 | 需要改 `optimize_targets` 接口，接收 `leg_returns` |
| E12 接线 | P2 | 需 ADV20/price/netliq 从 pipeline 传入 |
| E15 接线 | P2 | 需 equity/floor 数据 |
| E26 接线 | P2 | 可直接用 `confidence.decision_confidence` 作为 `p_act` |
| CVaR 显式约束 | P2 | 用正态近似 `σ·φ(Φ⁻¹(α))/α` 即可，无需历史回报 |

---

## 回归验证

- [ ] 270 package tests OK（SLSQP 回退路径的测试应仍然通过，回退值现在 vol 合规）
- [ ] vol_budget 紧时 `_solve_slsqp` 回退行为验证：`vol(w_fallback) <= vol_budget`
- [ ] R3 硬约束仍然满足：`w_opt[i] <= rule_targets[i]`
