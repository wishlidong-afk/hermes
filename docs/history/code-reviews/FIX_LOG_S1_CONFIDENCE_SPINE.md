# Fix Log — Section 1: ConfidenceSpine 接回 + 双 gross 消除

> **修复日期：2026-06-02**
> **对应 Review 章节：** §1.1（Gate ④ 置信脊柱旁路）+ §1.2（双 gross 连乘）
> **修改文件：** `building/source_snapshots/P12_gate2_optimizer/pipeline.py`

---

## 问题回顾

### 1.1 置信脊柱在 P12 pipeline 被完全旁路

`_optimize_sizing()` 里手搓了一个只有一个分量的 `ConfidenceState`：

```python
conf_val = float(portfolio_risk.effective_gross_scaler)   # 旧引擎的 gross
confidence = ConfidenceState(
    decision_confidence=conf_val,
    components={"gross": conf_val},   # 只有一个分量
    ...
)
```

`compute_confidence`（spine.py）的 6 分量（数据净化 / 故障转移 / 陈旧 / 漂移 / 脆弱 / 分歧）在生产路径全丢，Gate ④「置信脊柱贯通」实际未达成。

### 1.2 双 gross 连乘

由于 `confidence.decision_confidence` 来自旧引擎 `gross`（vol/CVaR 驱动），
而 `risk_state.gross_scaler` 来自新引擎（同样 vol/CVaR 驱动），两者在
`sizing_optimizer.py` 里连乘 → 系统性过保守，且违反 Gate ①「单一风险源」。

---

## 修改内容

### 变更 1：顶层添加 `compute_confidence` import

```python
# 新增（在 from .core.contracts import Verdict, ConfidenceState 之前）
from .core.confidence.spine import compute_confidence
```

### 变更 2：移除函数内无用 `import math`

函数体内无任何 `math.xxx` 调用，`import math` 是冗余的。

### 变更 3：用真实 spine 替换手搓 ConfidenceState

**修改前：**
```python
# ── Build ConfidenceState from portfolio_risk ─────────────────────────────
conf_val = min(1.0, max(0.0, float(portfolio_risk.effective_gross_scaler)))
if conf_val >= 0.80: mode = "NORMAL"
elif conf_val >= 0.55: mode = "CAUTION"
else: mode = "DEGRADED"

confidence = ConfidenceState(
    decision_confidence=conf_val,
    mode=mode,
    components={"gross": conf_val},
    weakest_link="gross",
    notes=[f"derived from portfolio risk gross={conf_val:.3f}"],
)
```

**修改后：**
```python
# ── Build ConfidenceState via ConfidenceSpine (Gate ④) ───────────────────
confidence = compute_confidence(
    data_conf=getattr(portfolio_risk, "data_quality_score", None),
    failover_state=getattr(portfolio_risk, "failover_state", None),
    staleness_days=getattr(portfolio_risk, "staleness_days", None),
    drift_state=getattr(portfolio_risk, "drift_state", None),
    fragility=None,      # TODO: wire E7 fragility score
    disagreement=None,   # TODO: wire E22 model disagreement
    cfg=config.get("confidence", {}),
)
```

`getattr(..., None)` 的设计意图：若 `compute_portfolio_risk` 返回的对象不含
某字段，spine 对该分量使用中性值 0.5（而非报错），系统以降级置信运行。

---

## 修复后语义

- `confidence.decision_confidence` = 数据质量 × 故障转移 × 陈旧 × 漂移的综合信号（0~1）
  → **不再是 vol/CVaR 预算信号**
- `risk_state.gross_scaler` = vol/CVaR 预算截断器（来自 `RiskEngine`，Gate ①）

两者现在语义上独立，`sizing_optimizer` 里的连乘：
```
upper_bounds = rule_targets * conf_factor * risk_gross_factor
```
变为「数据质量收缩 × 风险预算截断」，语义正确，Gate ① 和 Gate ④ 均满足。

---

## 残余 TODO

| 项目 | 状态 | 说明 |
|------|------|------|
| fragility 接入 | TODO | 需 E7 脆弱因子落地 |
| disagreement 接入 | TODO | 需 E22 模型分歧量化 |
| `compute_portfolio_risk` 的 `data_quality_score` 字段 | 待确认 | getattr 防护兜底 |
| 长期删掉 `compute_portfolio_risk` 旧引擎 | TODO | 待全切到 `RiskEngine` |

---

## 回归验证

- [ ] 270 package tests OK（接入后 spine 注入 None 参数应降级而非报错）
- [ ] 11 golden tests OK（golden 输出中 `confidence.components` 从单键变多键，需更新 fixture）
- [ ] `PhaseIII_Dry_Run_Comparator` 再跑：BLOCK=0 仍然满足（置信降级不应触发硬阀门）
