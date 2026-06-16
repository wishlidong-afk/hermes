# Hermes 项目复盘与前瞻（2026-06-02）

> 本文档是对 Hermes 逃顶 + 镜像系统截至 2026-06-02 的全面复盘：进度评估、代码审查、架构问题、优化建议。

---

## 1. 当前进度总览

### 1.1 整体完成度：**~72%**

| 维度 | 权重 | 完成度 | 说明 |
|---|---:|---:|---|
| 数据层（L0-L1） | 15% | 85% | 价格 2018+ 已有；软数据已接 5 源，PCR/NAAIM/BTC 三源待接 |
| 评分+硬阀门（L2-L3） | 15% | 95% | A/B/C/D + 硬阀门骨架完整；270 tests 通过 |
| 裁决+仓位（L4-L7） | 15% | 90% | 裁决/组合/路由/再建仓均 DONE；旧 scaler 待替换 |
| 回测+校准（L8） | 10% | 95% | NEXT-3 v2 校准完成；full-proxy + real-only 双报告已出 |
| 整合引擎（P4） | 15% | 85% | 15 个组件骨架完成，已落地本地并通过 270 tests |
| Phase II-III 验证 | 10% | 80% | P5-P9 全部完成；110/0.90 候选通过 full/exact；但仍 REVIEW-GATED |
| Phase IV 7 闸 | 10% | 40% | 结构验证通过，但实数据端到端 PBO/CI/对抗 AUC 未跑 |
| WebUI/IBKR/生产 | 5% | 30% | WebUI 部分；IBKR 未接；生产切换未做 |
| 元模型（L9） | 5% | 0% | LOCKED，标签解锁门未达 |

**加权总进度：~72%**

### 1.2 距离"日常可用"还要多久

"日常可用"定义为：人工每日运行 `run_daily.py`，看到评分/裁决/路由/审计的完整输出，且整合引擎在 shadow 模式下并行产出置信/风险数据。

| 剩余任务 | 估算工作量 | 说明 |
|---|---|---|
| 人工审阅 P9 WARN 并决定接受 110/0.90 | 1 天 | 看 WARN 日期机会成本是否可接受 |
| 生成 updated migration acceptance pack | 0.5 天 | 合并 P8/P9 结论成提案 |
| scaler 迁移 + 回测对照验证 | 2-3 天 | 替换旧链、跑新旧并排 |
| Phase IV PBO/CI 实跑 | 2 天 | 用 ValidationHarness 跑 2018-2026 |
| WebUI 接入 audit exporter | 1 天 | JSON/Markdown 审计报告展示 |
| **小计** | **~7 天** | 不含 IBKR 对账和元模型 |

"完全上线"（包括 IBKR 只读对账、剩余软数据补全、元模型解锁）还需额外 3-4 周。

---

## 2. 代码逐模块审查

### 2.1 RiskEngine (`risk_engine.py`)

**P4 原版 → P5 生产版已做的修复（好）**：
- 增加了 `_clean_return_series()` 做 NaN/Inf 清洗
- `ledoit_wolf_shrink` 改为不依赖 sklearn（手写收缩估计量更稳定）
- `downside_corr` 增加了 `min_tail_obs` 保护
- 增加了 `_safe_cov` 确保正定性

**仍存在的问题**：
1. **HAR-RV 拟合不检查多重共线性**：`rv_daily`, `rv_w`, `rv_m` 高度相关时 `lstsq` 可能得到不稳定的 beta，建议加岭回归项或条件数检查
2. **EWMA 初始化**：`var = r[0]**2` 用第一个观测初始化，对单个异常值敏感；建议用前 5 日均值
3. **`_off_diag_mean`** 在 2-leg 场景下只有 2 个 off-diag 元素，统计意义弱，`corr_regime` 判定可能不稳定

### 2.2 SizingOptimizer (`sizing_optimizer.py`)

**P5 版已做的修复（好）**：
- 增加了 `warnings.catch_warnings` 抑制 scipy 收敛警告
- grid solver 的 cov 维度校验更严格

**仍存在的问题**：
1. **`expected_leg_return` 用 `vol * 0.5` 做 mu 估计过于粗糙**：风险溢价应根据历史实际收益或资本资产定价给出更合理的先验，当前等效假设所有标的 Sharpe=0.5
2. **grid solver 在 4-leg 场景下会组合爆炸**：当前限制 3-leg 且 `grid_steps=11`（1331 点），但若未来扩展到 4+ 标的，需要切到更高效的求解器
3. **SLSQP fallback 值 `upper * 0.3` 是硬编码**：求解失败时返回 0.3 倍上界，逻辑上应回退到"最保守可行解"（全部归零或最小允许仓位）

### 2.3 Pipeline (`pipeline.py`)

**问题**：
1. **fragility 计算在 scorer_fn 为 None 时直接返回 0.0**：这意味着默认模式下 fragility 永远不工作，脊柱的 `c_frag` 分支无法被触发
2. **`_compute_staleness` 只看 store 最新日期**：如果 store 包含未来数据（测试场景），staleness 可能为负值
3. **audit dict 的 `timestamp` 用 `datetime.utcnow()`**：不确定性，同输入两次调用 audit 不完全一致（不影响决策但违反"逐位一致"原则的精神）

### 2.4 ConfidenceSpine (`spine.py`)

**设计合理，无重大问题**。
小建议：`_geomean` 在所有值接近 0 时用 `max(1e-9, ...)` 防除零，但如果 6 个组件中有 4 个是 0.5（缺失默认值），几何均值约 0.5，与"DEGRADED"阈值 0.55 很接近——边界行为需要更多测试覆盖。

### 2.5 Phase II/III 验证脚本 (`phase2_shadow_compare.py`, `phase3_dry_run_compare.py`)

**代码质量高**：
- 严格只读、不改状态
- 错误隔离（try/except per row）
- 结果输出 JSON+Markdown 双份
- 清晰的 PASS/WARN/BLOCK 三档门控

**问题**：
1. **P6 `phase3_dry_run_compare.py` 从 `phase2_full_backtest_sensitivity.py` 直接 import 私有函数**（`_build_replay_cache`, `_fast_project_targets` 等）：违反封装，重构难度高
2. **P7/P8/P9 脚本间的复用链越来越长**：P9 复用 P5 脚本跑 full-window，但参数传递链已有 4 层间接引用

### 2.6 FactorLab / MarketContext / ValidationHarness / Governance

这些组件目前仍是 **P4 原版骨架**，没有在 P5-P9 中实际接入。代码本身合理，但需要标注为"待集成"。

### 2.7 Reentry Tracker / Tax / Audit Exporter

小模块，设计清晰。`_business_days_between` 的简单周末跳过逻辑不考虑节假日，在真实使用中会有 1-2 天偏差，建议注明。

---

## 3. 架构层面的问题

### 3.1 代码存在两套 RiskEngine/SizingOptimizer

| 位置 | 版本 | 状态 |
|---|---|---|
| `P4_risk_engine/` | 原版骨架 | 已被 P5 版超越 |
| `P5_phase2_shadow/` | 生产版（含修复） | 正在使用 |

**问题**：两套代码共存可能导致混淆，应明确标注 P4 版为"历史存档"，P5 版为"当前基线"。

### 3.2 source_snapshots 越来越多，缺乏单一可运行包

repo 中有 P0/P3/P4/P5/P6/P7/P8/P9 等 16+ 个 source_snapshot 目录，但没有一个统一的 `hermes_escape_top/` 包可以直接安装运行。真正可运行的代码在本地 `.hermes/skills/investment/escape-top/hermes_escape_top/`，repo 只是快照。

**建议**：创建一个 `src/` 或 `hermes_escape_top/` 顶层目录作为可安装包的 canonical source，source_snapshots 改为纯归档。

### 3.3 EXTREME_CORR 占 78.57% 的天数

Phase II shadow 显示 252 天中 198 天被判定为 EXTREME_CORR，占 78.57%。这意味着当前阈值（`corr_regime_extreme_pctl=92`）对于 MSTR/FNGU/SOXL 三腿来说**几乎永远触发**，因为这三个标的本来就高度相关。

P8/P9 已将阈值调高到 110（即下行相关必须比线性相关高 10% 才算 EXTREME），使 EXTREME 占比降到 40.48%。但这仍然意味着近半时间都在应用额外惩罚。

**根因**：`downside_corr / linear_corr` 的比值对于高 beta 成长股天然偏高，因为它们在下跌时确实更相关。`corr_regime` 的阈值需要根据标的特性而非通用百分位来设定。

### 3.4 train-greedy PBO = 0.6154 是持续警报

无论 110/0.70 还是 110/0.90，train-greedy PBO 都超过 0.5，说明"每个窗口选最优参数"的策略在 OOS 上不可靠。当前的 fixed-parameter 方案（PBO=0.1538 或 0.3077-0.4615）是安全的，但也意味着参数的 OOS 泛化能力有限，不应期望未来表现与回测完全一致。

---

## 4. 优化建议

### 4.1 短期（1-2 周）

| 优先级 | 建议 | 预期收益 |
|---|---|---|
| **P1** | 人工审阅 P9 WARN 并做出 110/0.90 接受/拒绝决策 | 解锁 Phase III 迁移 |
| **P2** | 统一 source_snapshots 为一个 canonical `src/` 包 | 消除代码版本混淆 |
| **P3** | 把 `pipeline.py` 的 `timestamp` 改为 `as_of` 驱动的确定性值 | 恢复"逐位一致"不变式 |
| **P4** | 补 NEXT-1 剩余软数据（PCR/NAAIM CSV 手动回填） | MSTR missing 从 26 降到 ~18 |
| **P5** | HAR-RV 加岭回归防共线性；EWMA 初始化改 5 日均值 | 波动预测鲁棒性 |

### 4.2 中期（3-4 周）

| 优先级 | 建议 | 预期收益 |
|---|---|---|
| **M1** | 跑 Phase IV 完整 PBO/CI/对抗 AUC，产出 Factor_Health.md | 7 闸全通过 |
| **M2** | 重构 P6/P7/P8 的私有函数 import 链为公共 `replay_utils.py` | 降低维护成本 |
| **M3** | `corr_regime` 阈值从全局百分位改为标的特异性基线 | EXTREME_CORR 占比更合理 |
| **M4** | SizingOptimizer 的 mu 估计改为 Bayesian shrinkage 或 Black-Litterman 先验 | 更合理的预期收益 |
| **M5** | WebUI 接入 Audit Exporter，展示每日 Markdown 日报 | 提升可观测性 |

### 4.3 长期（1-3 个月）

| 优先级 | 建议 | 预期收益 |
|---|---|---|
| **L1** | IBKR 只读对账（NEXT-6） | 理想 vs 实际仓位比对 |
| **L2** | 元模型解锁（需攒够 300 标签 + 40 正样本） | 从规则升级到概率驱动 |
| **L3** | 把整个系统打包为 pip-installable 包 + CI/CD | 工程化 |
| **L4** | 对 EXTREME_CORR 惩罚做非对称设计：只在 VIX > 某阈值时生效 | 避免牛市中过度保守 |
| **L5** | 三标的扩展到更多标的（如 TQQQ/UPRO）时的架构准备 | 可扩展性 |

---

## 5. 关键风险提示

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 合成段历史（2018-2025）的信号置信度有限 | 中 | 已标 is_proxy，仅做 Medium 置信度 |
| 6 年回测窗口偏短，walk-forward 折数少 | 中 | 选稳健高原而非最优；诚实声明低置信 |
| EXTREME_CORR 在牛市中可能过度保守 | 中 | P8/P9 已调高阈值到 110/0.90，但仍需实盘验证 |
| 旧 scaler 链和新 SizingOptimizer 并行期的状态同步 | 低 | Phase III 有严格 PASS/WARN/BLOCK 门控 |
| 软数据缺失（missing_weight 26）可能导致评分偏差 | 低 | 盲区门已过 (<30)，但继续补源仍有价值 |

---

## 6. 结论

Hermes 系统在架构设计、安全护栏、验证严谨性方面达到了机构级标准。从"纯文档"到"270+ 测试通过的可运行系统"的跨越已完成。当前最关键的阻塞点是**人工审阅 P9 WARN 并决定参数**，这是唯一不能由代码自动完成的步骤。

一旦参数决策落定，Phase III scaler 迁移和 Phase IV 全闸验证预计 1-2 周可完成，届时系统将达到 **M4 可上线**的成熟度。
