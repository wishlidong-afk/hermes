# Fix Log — Section 2: RiskEngine 三处修复

> **修复日期：2026-06-02**
> **对应 Review 章节：** §1.4（ledoit_wolf_shrink sklearn 死分支）+ §三（EXTREME_CORR 根因）+ §4.1（risk_contribution 键名 ≥10 腿错位）
> **修改文件：** `building/source_snapshots/P5_phase2_shadow/hermes_escape_top/core/portfolio/risk_engine.py`

---

## 修复一：`ledoit_wolf_shrink` sklearn 分支是错的

### 问题

```python
lw = LedoitWolf(assume_centered=True)
lw.fit(np.eye(corr.shape[0]))   # ← 在单位矩阵上 fit，不是真实数据！
shrinkage = lw.shrinkage_
```

sklearn 的 `LedoitWolf.fit()` 接受原始返回数据（T × k 矩阵），而不是预计算的相关矩阵。
在单位矩阵上 fit 产生的 `shrinkage_` 与实际数据毫无关系。加上 `except (ImportError, Exception)` 静默吞掉所有错误，安装了 sklearn 时收缩强度是无意义值，反而比没有 sklearn 更差。

**间接后果：** 收缩强度错误导致 `ledoit_wolf_shrink` 返回的 off-diagonal 值偏小，系统性放大 EXTREME_CORR 比率（分母偏小 → 比值偏高）。

### 修复

删除 sklearn 分支，只保留手写的 `_lw_shrinkage_manual`：

```python
def ledoit_wolf_shrink(corr: np.ndarray, n_obs: int) -> np.ndarray:
    """Ledoit-Wolf shrinkage toward identity using analytic formula."""
    corr = _finite_square_matrix(corr)
    shrinkage = _lw_shrinkage_manual(corr, n_obs)
    target = np.eye(corr.shape[0])
    shrunk = (1.0 - shrinkage) * corr + shrinkage * target
    np.fill_diagonal(shrunk, 1.0)
    return shrunk
```

---

## 修复二：EXTREME_CORR 分子分母不一致（根因修复）

### 问题

原复盘把 78% EXTREME_CORR 占比归因为「阈值定太低」，实际根因更深：

| 量 | 估计方式 | 偏差方向 |
|---|---|---|
| 分母 `corr_mean` | `_off_diag_mean(corr)` — Ledoit-Wolf **收缩后**的 EWMA corr | 收缩把 off-diagonal 拉向 0 → **偏小** |
| 分子 `downside_corr_mean` | `_off_diag_mean(dc)` — tail corr 被 `np.maximum(corr, full_corr)` 做地板 → **偏大** |

`downside / linear × 100` 因此结构性地恒 > 100，阈值被迫从 92 抬到 110。

### 修复

将 `raw_corr`（shrinkage 之前的 EWMA corr）保存下来，用它作为 EXTREME_CORR 比率的分母：

```python
# 修改前
corr_mean = _off_diag_mean(corr)    # 收缩后，偏小

# 修改后
corr_mean = _off_diag_mean(raw_corr)  # 收缩前，与分子统一基础估计量
```

同时修复 fallback 路径（`n_obs < min_periods`）缺失 `raw_corr` 赋值的问题：
```python
raw_corr = np.eye(len(legs_reported))   # fallback 时保持维度一致
corr = np.eye(len(legs_reported))
```

### 阈值键名改名（backward compat）

将 `corr_regime_extreme_pctl`（名称有误导性，实际是比值 × 100 非百分位）改为
`corr_regime_extreme_ratio`，同时保留旧键作 fallback：

```python
extreme_ratio_threshold = float(risk_cfg.get(
    "corr_regime_extreme_ratio",
    risk_cfg.get("corr_regime_extreme_pctl", 110)
))
```

默认值从 92 → 110（与 P8/P9 接受的候选参数对齐）。

### 注意事项

此修复改变了 EXTREME_CORR 触发频率。当前接受的候选参数 `110/0.90` 是基于有 bug 的
估计量校准的。修复后分子分母更接近，比值会整体下降，110 可能触发更少，需在下次
phase3 dry-run 中重新评估阈值是否需要降低。

---

## 修复三：`risk_contribution` 键名 ≥10 腿时错位

### 问题

```python
rc = risk_contribution(w_vec, cov)
rc_named = {legs_reported[i]: v for i, (_, v) in enumerate(sorted(rc.items()))}
```

`sorted(rc.items())` 对字典键进行字母序排序：
- 3 腿（leg_0, leg_1, leg_2）：字母序 = 数字序，无问题
- ≥10 腿：`leg_10` 排在 `leg_2` 之前，`legs_reported[i]` 映射到错误标的

当前 3 腿场景不受影响，但 L5 标的扩展时会踩坑。

### 修复

改用位置索引直接映射，避免任何排序：

```python
rc_named = {legs_reported[i]: rc[f"leg_{i}"] for i in range(len(legs_reported))}
```

---

## 变更摘要

| # | 位置 | 变更类型 | 影响 |
|---|---|---|---|
| 1 | `ledoit_wolf_shrink` | 删除 sklearn 死分支 | 收缩强度现在基于真实数据 |
| 2 | `build_risk_state` `:330` | 新增 `raw_corr` fallback 赋值 | 维度一致性保证 |
| 3 | `build_risk_state` `:330` | 新增 `raw_corr` 正常路径保存 | 供 EXTREME_CORR 使用 |
| 4 | `build_risk_state` `:373` | `corr_mean` 改用 `raw_corr` | EXTREME_CORR 分母无偏 |
| 5 | `build_risk_state` `:377` | 阈值变量名 `extreme_pctl` → `extreme_ratio_threshold` | 语义清晰 |
| 6 | `build_risk_state` `:404` | `rc_named` 改用位置索引 | ≥10 腿安全 |
| 7 | `build_risk_state` `:441` | `estimator_meta` 更新键名 | 输出一致 |

---

## 回归验证

- [ ] 270 package tests OK（risk_engine 单测重点验证 `ledoit_wolf_shrink` 收缩值合理）
- [ ] EXTREME_CORR 触发频率应低于修复前（252 日 shadow 重跑对比）
- [ ] `rc_named` 的 symbol → RC 映射应与 `legs_reported` 顺序一致（新增断言测试建议）
