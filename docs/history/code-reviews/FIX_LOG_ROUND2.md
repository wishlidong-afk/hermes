# Fix Log — Round 2（对第一轮修复的复审 + 二次修复）

> **修复日期：2026-06-02**
> **修改文件（仅 canonical `src/`，snapshots 保持 archive-only）：**
> - `src/hermes_escape_top/pipeline.py`
> - `src/hermes_escape_top/core/portfolio/sizing_optimizer.py`
> - `src/hermes_escape_top/core/portfolio/risk_engine.py`
> **验证：** `review/verify_followup_fixes.py`（25 项断言全绿，可独立运行）

---

## 背景

第一轮修复（commit `237c9fd` / `7927c8c`）声称关闭了全部 11 项 review。逐行复审后发现:
**结构性修复(删 sklearn 死分支、改 RC key、建 src/ 包)是对的;但两处"接线类"修复
接错了量,合起来会让系统每天近乎清仓,且 commit 自带的回归 checklist 一项都没勾(没跑过)。**

本轮把这些问题彻底改对,并补了一个**可独立运行的验证脚本**——因为完整 pipeline 还缺 17 个
未迁移模块、跑不起来,但核心数学(`build_risk_state` / `compute_confidence` / `optimize_targets`)
是自洽的,可以用合成输入直接断言行为。

---

## 🔴 修复 1：置信脊柱接到了错误的数据源 → 永久 DEGRADED

### 问题
第一轮把 spine 接回来了,但喂给它的是:
```python
data_conf=getattr(portfolio_risk, "data_quality_score", None)   # 这些字段根本不存在
failover_state=getattr(portfolio_risk, "failover_state", None)
staleness_days=getattr(portfolio_risk, "staleness_days", None)
drift_state=getattr(portfolio_risk, "drift_state", None)
```
`portfolio_risk` 是旧 `risk_budget` 引擎的输出,**没有这四个字段**。四个 `getattr` 全 → `None`
→ spine 六分量全取中性 0.5 → `confidence = 0.5` → 恒 `< 0.55` → **每次运行都是 DEGRADED**,
且 `getattr(..., None)` 静默兜底,不报错。叠加第一轮默认开启的 Kelly,实际上界 ≈ rule 的 3.75%。

### 修复（`pipeline.py`）
按原 P4 pipeline 的契约,从**真实信号源**计算,monitor 跑干净就传"健康"具体状态而非 None：
```python
confidence = compute_confidence(
    data_conf=_data_confidence(bundles, config),          # 由 scores 的 missing_weight 推导
    failover_state={"is_degraded": False},                # 健康默认(真 failover 待接)
    staleness_days=_max_staleness_days(histories, config, as_of),  # 最新 bar 距 as_of
    drift_state={"psi": 0.0, "alert": False},             # 健康默认(真 drift 待接)
    fragility=0.0, disagreement=0.0,                      # E7/E22 占位
    cfg=config.get("confidence", {}),
)
```
新增两个 helper:
- `_data_confidence`：`clip(1 - mean(missing_weight)/blind_spot_gate, floor, 1.0)`。
  **「缺数据≠安全」红线现在落在这里**——缺数据 → 低 data_conf → 小仓位,而不是靠 None→0.5。
- `_max_staleness_days`：交易标的最新 bar 与 `as_of` 的最大间隔;`as_of` 缺失时返回 None(中性)。

`_optimize_sizing` 新增 `as_of` 参数,`score_pipeline` 调用处已传入。

### 验证
```
healthy confidence=0.899 mode=NORMAL    ← 数据健康 → NORMAL(不再永久 DEGRADED)
all-None still DEGRADED                  ← 保留并记录这个陷阱
low data_conf lowers confidence          ← 红线生效
```

---

## 🔴 修复 2：Kelly 默认开启 + p_act 用错量

### 问题
`kelly_cfg.get("enabled", True)` 默认开;且 `p_act=conf_factor`。
**p_act 是「这笔交易获胜的概率」,conf_factor 是「数据质量综合分」——范畴错误。**
即使置信健康,`kf≈0.255`,每条腿砍到 25%;叠加修复 1 的永久 0.5,砍到 ~7.5%。

### 修复（`sizing_optimizer.py`）
- **默认 `enabled=False`**（opt-in）。
- 启用时**必须显式提供 `kelly.p_act`**（校准胜率);缺失则 `raise ValueError`,
  从代码层禁止再用 confidence 顶替 p_act。

### 验证
```
default proxy mode -> weights not crushed to ~0    ← 关掉 Kelly 后仓位正常(sum≈0.396)
kelly.enabled without p_act raises ValueError      ← 类别错误被硬禁止
```

---

## 🟠 修复 3：mu 估计——撤掉会"假清仓"的裸历史均值,改为安全的可选倾斜

### 问题（第一轮引入的新隐患）
第一轮把 mu 改成**裸 252 日年化均值**并默认启用。但下行规避效用
`U = w'μ − dd·√(w'Σw)`(dd=3)等价于一个**绝对 Sharpe>3 门槛**——杠杆 ETF 年化波动~95%,
没有任何标的能过,于是 **优化器把所有腿清零**(假清仓)。验证脚本一开始就复现了这点
(`sum=0.0000`)。这比原来的"退化但稳定"更危险。

### 修复（`sizing_optimizer.py`）
引入 `mu_mode`：
- **默认 `"proxy"`**：`base_mu = vol·max(2, dd+1)`,保证 `mu > dd·vol`,优化器退化为
  「在风险预算内顶到上界」——**这正是 Phase II/III 验证过的姿态**。是否持有由评分/裁决层
  (`rule_target_weight`)决定,不该由本优化器用绝对 Sharpe 门槛二次否决。
- **可选 `"historical_tilt"`**（**默认关,需回测验证后再开**）：用横截面收缩后的趋势均值
  做**有界排名倾斜**,且 `base_mu ≥ proxy`(姿态不变),只在**vol 预算 binding 时**让优化器
  偏向高收益腿。绝不直接用裸均值。

### 验证
```
proxy-mode   target_weights={FNGU:0.132, MSTR:0.132, SOXL:0.132}   ← 姿态保留,不清仓
tilt-mode    target_weights={FNGU:0.80,  MSTR:0.781, SOXL:0.0}     ← 预算binding时偏向高收益腿
historical_tilt favours higher-return leg (FNGU 最大)              ← 真正差异化且守 R3
```

---

## 🟡 修复 4：CVaR「摆设约束」移除,改为如实记录其来源

### 问题
第一轮加的 SLSQP CVaR 约束在年化 vol≈61% 处才 binding,而 vol_budget=35% 永远更紧 →
**CVaR 约束永不生效**,纯属冗余;且正态近似低估杠杆 ETF 肥尾,本身不对。

### 修复（`sizing_optimizer.py`）
- 从 SLSQP 移除 CVaR 约束,删除死代码 `_cvar_normal_factor`,`_solve_slsqp` 去掉 cvar 参数。
- 在 docstring 如实说明:**CVaR 已通过 `risk_state.gross_scaler`(= `min(vol_scaler, cvar_scaler)`)
  在 upper_bounds 上游强制**,无需在优化器里重复。

### 验证
```
_cvar_normal_factor removed                ← 死代码已清
_solve_slsqp signature has no cvar params  ← 约束不再重复
```

---

## 🟡 修复 5：EXTREME_CORR 分子分母统一为同一估计量

### 问题
第一轮把分母换成 `raw_corr`(EWMA),但分子 `dc` 仍被全样本 Pearson 地板过
(`np.maximum(corr, full_corr)`)。分子(Pearson-floored)与分母(EWMA)仍是**两种估计量**,
比值仍会结构性偏高。

### 修复（`risk_engine.py`）
新增 `downside_vs_linear_ratio()`：在**同一样本**上算
`(尾部 Pearson 相关均值, 全样本 Pearson 相关均值)`,两者同源,比值真实反映尾部放大。
`build_risk_state` 的 regime 判定改用它。`downside_corr`(带地板)仍用于 RiskState 的
保守上报,不再污染 regime 比值。

### 验证
```
downside_vs_linear_ratio returns a pair / components finite / build_risk_state regime set
```

---

## 🟢 修复 6：LW 命名诚实化 + 合理收缩强度

### 问题
`_lw_shrinkage_manual = rho/n_obs` 既非真 Ledoit-Wolf,n_obs=252 时 ≈0.0025(几乎不收缩),
而 docstring 写"is correct"。

### 修复（`risk_engine.py`）
- 改名 `_shrinkage_intensity(k, n_obs)`,强度 = `n_pairs/(n_obs+n_pairs)`(有界、obs 越少收缩越多)。
- `ledoit_wolf_shrink` docstring **如实声明这是启发式收缩、非渐近最优 LW**(真 LW 需原始观测,
  此调用点拿不到),公共名保留作兼容。

### 验证
```
shrinkage intensity in [0,1] / fewer obs -> more shrinkage / shrunk off-diag < raw
```

---

## 🟢 修复 7：网格求解器泛化 + 去重复 import

- `_solve_grid` 用 `itertools.product` 泛化到任意维,并按 `max_points` 自动降低 `grid_steps`,
  消除 n>3 时直接返回 `upper*0.3` 的悬崖(全零权重恒可行,保证有解)。
- `pipeline.py` 删掉顶层重复的 `from .core.portfolio.sizing import size_portfolio`
  (函数内 fallback 仍保留局部 import,避免潜在循环导入)。

### 验证
```
grid n=4 returns feasible vector within bounds / R3 respected
```

---

## Gate ① 进展（单一风险源）

`_SizingProxy` 的 `vol_scaler/gross_scaler` 上报从旧 `portfolio_risk.effective_gross_scaler`
改为 **`risk_state.gross_scaler`(RiskEngine,单一来源)**。
`compute_portfolio_risk` 现仅剩两处用途:① `_optimize_sizing` 异常兜底;② 其自身 audit 上报。
**完全删除它需先迁移掉 `risk_budget` 依赖**(见 `MIGRATION_STATUS.md`),属迁移任务,本轮未做。

---

## ⚠️ 仍未完成 / 必须后续跟进（诚实声明）

| 项目 | 状态 | 说明 |
|---|---|---|
| **重跑 Phase II–IV 回测** | **未做(本环境无法做)** | 本轮改动了 sizing 数学(Kelly/CVaR/mu/上报源),**所有旧的 Sharpe/MaxDD/PBO 数字已失效**,必须用迁移后的完整包重跑后才能再声称"已验证" |
| 完整包跑通 270/11 测试 | 未做 | `src/` 仍缺 17 个模块(config/scoring/data/risk_budget…),无法 import 运行;本轮只验证了核心数学(见 `verify_followup_fixes.py`) |
| 真实 failover / drift 接入 | 占位 | 当前传健康默认值;E 模块落地后替换 |
| E7 fragility / E22 disagreement | 占位 0.0 | 待对应增强落地 |
| 删除 `compute_portfolio_risk` | 未做 | 待 `risk_budget` 迁移完成,真正实现 Gate ① |
| binding-constraint 标签 | 小瑕疵 | 启用 Kelly/liquidity/CPPI 后 upper_bounds 被改写,"CONFIDENCE" 标签可能名不副实;默认路径不受影响 |

---

## 如何复跑验证

```bash
python3 review/verify_followup_fixes.py    # 退出码 0 = 25 项断言全绿
```

> **核心结论**:本轮把第一轮"形似神不似"的两处致命接线(spine 数据源、Kelly 的 p_act)
> 和一处新隐患(裸历史 mu 假清仓)彻底改对,并以可运行脚本验证了核心数学。
> 但**完整端到端验证仍被 17 个未迁移模块阻塞**,且**回测数字必须重跑**——
> 在此之前不应声称系统"已通过验证可上线"。
