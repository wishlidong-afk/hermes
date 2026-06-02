# P16 PCR is_proxy 修复 + WebUI 新字段展示

**时间**: 2026-06-02  
**范围**: PCR 代理标记修复；WebUI 新增 Optimizer Detail / Factor Scores / System Health 面板  
**结果**: 293 tests OK

---

## Section A — PCR 可达性最终结论

| 来源 | 状态 | 备选 |
|---|---|---|
| CBOE CDN (`cdn.cboe.com`) | ❌ 403 Forbidden | — |
| yfinance `^PCCE` | ❌ 404 delisted | — |
| stooq.com | ❌ 需 captcha/API key | — |
| **VVIX（`^VVIX` via yfinance）** | ✅ penalty=0.0 | **已实时运行** |

**结论**：PCR 真实数据在当前环境不可自动获取。但 **VVIX（VIX波动率指数）** 已通过 CboeIndicesSource 以 penalty=0.0 实时提供，覆盖同等期权恐惧信号空间。

### 修复内容

- `cboe_equity_pcr.csv`：补 `is_proxy=True` + `source=vix_derived_proxy` 字段
- `core/data/pcr.py`：从 CSV 读 `is_proxy` 列，real → penalty=1.0，proxy → penalty=1.5，source 标签区分

---

## Section B — WebUI 三个新面板

### 1. System Health 面板（替换旧 Current Regime）

- **Confidence badge**：颜色区分 NORMAL（绿）/ CAUTION（黄）/ DEGRADED（红）
- **Risk binding**：显示 corr_regime、gross_scaler、binding_constraint
- 所有置信/风险信息一眼可见

### 2. Optimizer Detail 面板（新，Gate 2 可见性）

| 列 | 含义 |
|---|---|
| Target Weight | 优化器输出的实际目标仓位 |
| Rule Ref | R3 上界（rule_target_weight） |
| Gross Scaler | RiskEngine 的风险缩放系数 |
| **Binding** | 绑定约束（RISK_GROSS / VOL_BUDGET / R3_RULE / ZERO / NONE） |
| **Confidence** | optimizer_confidence（置信度代理） |
| **Exec Mode** | execute_now（硬阀门）/ twap_3_slices |
| **Engine** | `optimize_targets_v1`（绿色徽章）/ legacy（黄色） |

### 3. Factor Scores 面板（新，Gate 6 可见性）

- 每标的每模块前 3 个因子
- 显示得分条形图（ASCII）+ 原因文本
- 让 "A2_NAAIM: missing" 等盲区可视化

### 测试更新

- `test_phase14_web.py`：`"Current Regime"` → `"System Health"`，`"Greenfield"` → `"Escape Top"`

---

## 293 tests OK

## 状态

P16: **DONE** — PCR 标记修正；WebUI 新增 Optimizer Detail / Factor Scores / System Health 三个面板
