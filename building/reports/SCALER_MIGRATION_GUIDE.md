# Scaler Migration Guide（旧 Scaler 链 → SizingOptimizer 迁移指南）

更新时间：2026-06-01

---

## 问题

现有系统用乘法链计算目标仓位：

```python
# OLD (fragile, order-sensitive, no feasibility guarantee)
target = base_weight
target *= gross_scaler          # 组合波动预算
target *= vol_target_scaler     # 波动率目标
target *= R3_clamp              # R3 末位 clamp
target = min(target, sleeve_cap)
```

这条链有三个结构性缺陷：
1. **顺序敏感**：scaler 乘法顺序不同结果不同
2. **重复计数**：gross 和 vol_target 可能用了不同的协方差估计
3. **无可行性保证**：连乘后可能违反约束组合

## 解决方案

用 `SizingOptimizer.optimize_targets()` 替换整条链：

```python
# NEW (single entry, constraint optimization, R3 guaranteed)
sizing = optimize_targets(verdicts, risk_state, confidence, cfg)
target_weights = sizing.target_weights  # {sym: weight}
```

---

## 迁移步骤

### Step 1: 搜索旧 scaler 引用

在本地代码中搜索以下模式：

```bash
grep -rn "gross_scaler\|vol_target_scaler\|scale_position\|apply_scalers\|scaler.*\*\|target.*scaler" hermes_escape_top/
```

### Step 2: 替换模式

| 旧代码 | 新代码 |
|---|---|
| `target *= gross_scaler` | 删除：由 optimizer 内部的 vol_budget 约束处理 |
| `target *= vol_target_scaler` | 删除：由 optimizer 内部的 vol constraint 处理 |
| `target = min(target, rule_target)` | 保留但移入：optimizer 的 R3 上界已含此约束 |
| `target = min(target, sleeve_cap)` | 保留但移入：optimizer 的 upper_bound 已含此约束 |
| `if hard_valve: target = 0` | 保留：verdict 的 rule_target_weight=0 传入 optimizer |

### Step 3: 确认删除清单

每删除一个 scaler，运行：
1. 全部单测（确保不 break）
2. 回测对照（新 vs 旧结果对比）
3. R3 验证（`w_i <= rule_target` 100%）

### Step 4: 验证无残留

```bash
# 确认无残留 scaler 乘法
grep -rn "gross_scaler\|vol_target_scaler\|apply_scalers" hermes_escape_top/ | wc -l
# 应该返回 0
```

---

## 对照回测规范

```python
# 跑新旧并排
old_result = run_full_backtest(cfg_old)  # 旧 scaler 链
new_result = run_full_backtest(cfg_new)  # SizingOptimizer

# 比较
assert new_result.calmar >= old_result.calmar * 0.95  # 不退化超过 5%
assert abs(new_result.max_dd) <= abs(old_result.max_dd) * 1.05  # MaxDD 不恶化超过 5%
assert new_result.turnover <= old_result.turnover * 1.25  # Turnover 增幅 ≤ 25%

# R3 绝对验证
for day in new_result.daily_weights:
    for sym, w in day.items():
        assert w <= verdicts[sym].rule_target_weight + 1e-6
```

---

## 回退方案

如果新优化器不达标：

1. 关闭 `features.use_sizing_optimizer = False`
2. Pipeline 回退到旧 scaler 链（代码保留在注释块中）
3. 分析 SizingOptimizer 的 `binding_constraint` 定位问题
4. 调整参数后重跑对照

---

## 安全保证

- SizingOptimizer 的 R3 是硬约束 + belt-and-suspenders clamp
- 不可行域 → 最保守解（趋向现金）
- 硬阀门 → `execute_now`（不受 TWAP 延迟）
- 所有输出只读、不下单
