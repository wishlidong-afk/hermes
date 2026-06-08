# 资金效率改造 — 实施思路（先评审,后编码）

**Date**: 2026-06-08
**目标**: 在保住防御内核(MaxDD)的前提下,减少资金闲置/过度换手 → 提升 CAGR-per-risk。
**证据基线**: 你们已量化的代价 — real-only CAGR 44%→26%、blended 18.1%→15.3%(主要是再建仓拖累)。
**纪律**: 每项 flag-gated、默认复刻现状(byte-identical),用 `run_full_backtest` 2018–2026 做 on/off 对照,稳健选参,开关由人翻。

执行顺序(用户指定):① 放宽 T3 → ② 平滑悬崖 → ③ 减仓总闸+风险加权上限 → ④ 修 MSTR→QQQ → ⑤ 查 MSTR 硬阀门频率。

---

## ① 放宽 T3 再建仓门槛（头号杠杆）

**现状**: `core/reentry/plan.py:79-81,105-115`。T3(最后 40% 资金)要求 `_market_one_year_high()` — QQQ 或 SPY 收盘 ≥ 前 252 日最高收盘。大回撤后回到 52 周新高常需数月~数年 → 40% 资金长期趴在 BOXX → 这是 CAGR 拖累主因。

**改法**: 把 T3 闸门做成 config 驱动的可选模式 `reentry.t3_gate_mode`(默认 `market_252d_high` = 现状):
- `market_252d_high`(默认,现状)
- `ma200_reclaim`: QQQ 收盘 > MA200 且离 60 日低点反弹 ≥ `t3_off_low_pct`(默认 10%)
- `shorter_high`: 前 `t3_high_lookback` 日(默认 63≈一季度)新高

实现点:`_market_one_year_high` 泛化为 `_t3_market_gate(snapshots, histories, reentry_cfg)`,按 mode 分派;T1/T2 不动。

**回测对照**: 三种 mode 各跑一遍,看 CAGR / MaxDD / Calmar / 再入场平均滞后天数 / T3 平均闲置占比。**预期**: 放宽显著抬 CAGR;风险是回撤反弹中过早投 T3(假反弹)→ 看 MaxDD 是否被吃掉。稳健选"抬 CAGR 但 MaxDD 退化 < 2pp"的那档。

---

## ② 平滑 status→比例 悬崖（减摩擦+减假摔）

**现状**: `core/decision/verdict.py::sell_fraction_for` 按 status 查 `config.sell_fractions` 阶梯。69→70 一分跳 35pp(FNGU 50%→85%);50→69 区间不卖。

**改法**: 新增 `sell_fraction_mode`(默认 `step` = 现状)+ `continuous`:
- `continuous`: 以 (阈值, 比例) 为锚点,按**实际分数**在相邻档间分段线性插值。需把 `final_score` 传进 `sell_fraction_for`(verdict 已有 score,加一个可选入参,签名向后兼容)。
- 锚点 = status_thresholds × sell_fractions;EXIT 以上恒 100%;WATCH 以下恒 0。

**回测对照**: step vs continuous,看 Turnover / 摩擦成本 / Sharpe / MaxDD。**预期**: 换手与 whipsaw 成本下降、净值更平滑;风险极低(单调、有界)。与第一梯队的滞回叠加测一次(两者都治抖动,确认不过度黏滞)。

---

## ③ 减仓总闸 + 风险加权上限

**现状**: 实际仓位 = `sleeve_cap × (1−sell_fraction) × vol_scaler × gross_scaler`(`core/portfolio/sizing.py`),再叠"盲区+1级"。多层**乘性**叠加、无总闸 → 高波动时 status 已砍 + vol_scaler 再砍 → 可能过度减仓→现金拖累。且 sleeve_cap 静态(MSTR15/FNGU20/**SOXL30**),不按波动加权 → 3x 半导体单独吃掉组合大半风险预算。`use_portfolio_risk_budget` 默认关。

**改法(两个子项,各自 flag)**:
- **减仓总闸** `sizing.max_total_derisk`(默认 1.0 = 不设限): 限制"由 vol/gross 这些*非 status*因子带来的额外削减"幅度,使总削减不超过设定上限,除非 status 本身要求。即 status 的卖出意图为主,vol/gross 只在总闸内微调。报告里拆解每层贡献(可解释性)。
- **风险加权上限** `sizing.vol_weighted_caps`(默认 false): 用各标的 trailing vol 反比归一化 sleeve_cap(总名义不变,把额度从高波动标的挪一点给低波动),或直接对照 `use_portfolio_risk_budget=true`。

**回测对照**: 总闸 off/on(几个上限档)× 静态/风险加权上限 = 小网格,看 vol_budget 命中、风险贡献分散度、Calmar、现金占比。**预期**: 减少过度减仓的闲置 + 让 SOXL 不再主导组合波动;风险是总闸设太松会削弱防御 → 保守选。

---

## ④ 修 DEFCON3 的 MSTR→QQQ 换论点

**现状**: `core/routing/capital_routing.py:108-116` + `config.routing.defcon3 = {SOXL:SOXX, FNGU:QQQ, MSTR:QQQ}`。FNGU/SOXL 是"3x→同标的1x"(干净降维);但 **MSTR→QQQ = 把 BTC-beta 换成科技-beta**,不是降风险而是换赌注。且 MSTR 本就是 1x,没有杠杆可降。

**改法**: DEFCON3 对 MSTR 改为**同论点减档** — 路由到现货 BTC(`BTC-USD`,去掉 mNAV 溢价+单股风险、保留加密暴露);config `defcon3.MSTR: "BTC-USD"`。保留可配置(也可选 BRK.B 做"质量降档")。注:回测需 BTC-USD 有收益序列(已在 history 集)。

**回测对照**: MSTR DEFCON3 destination ∈ {QQQ(现状), BTC-USD, BRK.B},只看 MSTR sleeve 的路由后净值/回撤/相关。**预期**: BTC-USD 更贴论点、减少风格漂移;若 BTC 自身也在崩,降档收益有限 → 对照数据说话。

---

## ⑤ 查 MSTR 硬阀门触发频率（诊断,先不改）

**现状**: 硬阀门一律 100% 清仓。MSTR 单日 -15% 近家常(H-M2 = -15% 且 < EMA10)。若硬阀门过密 → 过度交易 + 现金拖累。

**做法**: 写诊断(不改逻辑): 2018–2026 逐日跑 `evaluate_hard_valves("MSTR", ...)`,统计每个 H-M* 的触发天数/年化频次、触发后 5/10/20 日的前向收益(是真崩还是假摔)。产 `review/HARD_VALVE_FREQUENCY_MSTR.md`。

**若发现过密**: 提议对单日类硬阀门(H-M2)加"先 85% 待确认"缓冲(与第一梯队 suspect-pending 同思路),作为下一步候选 — **本轮只出诊断+建议,不动硬阀门逻辑**(安全地板,改它要格外谨慎)。

---

## 回测方法学

- 引擎: `core/backtest/run_full.py::run_full_backtest(start, end, cfg, enable=, limit=)`。`limit` 先做 smoke(前 N 日)验证管线,再跑全窗口。
- 指标: CAGR / MaxDD / Calmar / Sortino / Sharpe / DD_reduction / Insurance_ratio / Turnover + walk-forward IS/OOS + DSR/PBO。
- 设计: **baseline(现状) → 每项单独 on 的 ablation → 组合 all-on**;报告 vs baseline 的 delta。
- 算力约束(memory 教训): 每次全窗口 ~52min,**同进程跑 >1 个会 OOM** → 每个 backtest 独立进程、后台串行。
- 选参原则: 稳健高原 + 保守宽边际,不取峰值;低样本下诚实标低置信(DSR)。
- 红线: 所有新 flag 默认关;backtest 通过 + 人审后才翻。本轮交付 = 代码(flag-off)+ 回测对照表 + 我的"翻哪些/不翻哪些"建议。

## 预期排序（待回测证实/证伪）
①(再建仓)对 CAGR 杠杆最大;③(风险加权上限+总闸)改善风险分散与闲置;②(平滑)低风险稳态改善;④(MSTR 路由)修正风格漂移、影响局部;⑤ 诊断决定是否进入下一轮硬阀门缓冲。
