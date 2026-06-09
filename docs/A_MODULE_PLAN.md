# A 模块计划 — 解耦前瞻/同步,破 cap-20 饱和(F7)

**Date**: 2026-06-09
**起因**: CNN Fear & Greed 接入后全系统边际 ≈ 0(`building/reports/flag_sweep/CNN_RESULT.md`:CAGR −0.03pp / MaxDD 持平 / Sharpe +0.011,噪声以内)。根因不是 CNN 没用,是 **A 模块封顶饱和**——往 A 模块加任何因子都是 wash。本文把"为什么是 wash、F7 怎么解、收益与边界、怎么落地"固化成可执行计划。
**性质**: 这是目前唯一还有**结构性**收益的方向(6 年窗口上的因子增删已枯竭)。收益落在 **lead-time(逃顶提前量)** 这一轴,不是凭空 alpha。

---

## 1. 问题诊断

### 1.1 有效性瓶颈 = lead-time,不是信息量
逃顶有效性 = **更早** + **更少假摔**。看 `building/reports/Factor_Health.md`:高 IC 因子**全是同步/确认型**(C10 超级趋势、D3/B3 顶后损伤、D1/D2 MA200 破位、C9 吊灯破位)。它们点亮时**顶已经在、损伤已发生**。系统不瞎,是**慢**——它在等价格自己破位来确认。瓶颈是 lead-time。

### 1.2 cap-20 吞信号(机制级)
- A 模块挂载因子 max 之和 ≈ **56**(A1×2、A2×4、A3–A8 + 已启用 A10/A11/A15),`core/scoring/scorer.py::aggregate_modules` 一句 `min(score, cap)`(`config.json` `module_caps.A = 20`)砍到 20。
- 真到顶部,一堆 A 因子同时点亮,光 3–4 个**共线**因子就顶满 20。此时再加 CNN(2 分)→ `min(22,20)=20` → **边际literally 为 0**。这就是 CNN 回测 = wash 的机制级原因:它的分**被 cap 丢弃**。

### 1.3 前瞻/同步混在一个桶里被平均(核心病)
A 桶混了两类**时间性完全不同**的因子:
- **同步型**(破位时才亮):VIX 飙、派发日、宽度崩。
- **前瞻型**(破位前就能高):real-rate、dollar、MOVE、集中度、情绪欣快(CNN/AAII/NAAIM)。

把两类**加成一个总分、再对总分卡阈值**,结果是**总分的时间点被同步因子主导**(它们占分多、涨得猛)。前瞻因子的"早"被平均、被淹没 → 系统实际开火时机 ≈ 同步因子开火时机 = **晚**。**你花算力采的前瞻信号,在"加总 + 封顶"两步里被稀释没了。**

---

## 2. 方案 F7:把前瞻因子从"加分"挪到"调节"通道

关键**不是**"把 cap 抬到 30 让更多因子计分"(那只是把 A 做大、阈值重标,边际且会引入更多共线噪声)。真正的解法是 **decouple**:让前瞻因子走一条**独立的、提前作用的调节通道**,而不是塞进封顶的总分。

代码里**骨架已存在**:`use_arm_then_fire`(默认关)。
- `core/scoring/scorer.py::_arming_relief` + `_ARM_HIGH/_ARM_LOW`:统计处在风险区的前瞻因子数。
- `core/decision/verdict.py::status_from_score(relief=...)`:relief 降低 WATCH..EXIT 阈值。

机制一句话:
> **前瞻因子"上膛"时(real-rate 高 + dollar 强 + 情绪欣快),降低同步技术因子的触发阈值**;前瞻平静时阈值不动。

---

## 3. 有效性收益

| 轴 | 现在 | F7 后 |
|---|---|---|
| 前瞻信号去向 | 塞进封顶 A 总分 → 顶部被 `min(.,20)` 丢弃 | 走调节通道,降阈值,不被丢 |
| 开火时机 | ≈ 同步因子破位时(晚) | 上膛后第一个小同步抖动即触发(早) |
| 精度 | — | **条件化**:只在前瞻上膛时放松阈值,不是无脑提前 |

**收益拆两条**:
1. **更早(lead-time)**:前瞻拿到独立提前通道,不再被总分平均掉 → 离顶更近就动手 → 少吃一段下跌。
2. **条件化精度**:阈值只在"上膛"时放松 → "上膛才早开火",而非满地假摔。这个 conditionality 就是精度杠杆。

**具体场景(2021-10 顶)**:
- 现在:CNN 欣快(pctl 92)+ real-rate 抬头 → 塞进已近满的 A 桶 → 砍掉 → 0 提前 → 等几周后 MA200 破位/吊灯破才动 → 已吃一大段回撤。
- F7 后:同组前瞻"上膛" → 压低 REDUCE/EXIT 阈值 → **第一个**小派发簇/EMA50 破即触发 REDUCE → 出场离顶近得多。

同样的因子、同样的信息——区别只是**不再在加总+封顶里扔掉前瞻信号**。

---

## 4. 边界与风险(不是免费 alpha)

1. **不保证回测数字大**。A 因子弱、共线,6 年窗口接近局部最优,逃顶是稀疏事件 → measurable 收益可能温和、带噪声。F7 的价值是"**别浪费已采的前瞻信号**",不是变出收益。
2. **double-count 缺陷(必须先修)**:arm-then-fire 用 real_rate/dollar 上膛,而这俩**又是已启用的 A 加分因子(A10/A11)** → 既加分又调阈值 = 算两遍。这是 F7 落地前的**头号阻塞**。
3. **必过 PBO**。提前开火 = 顶没来时也减仓 = 放弃上涨(risk-factor 那种 CAGR drag)。"放松多少分 / 上膛阈值"必须像 A10/A11/A15 一样回测 + PBO 校准、人翻开关。
4. **不增新信息**,只是不丢弃前瞻信息。要质变还得靠真正正交的新信号(axis-D MSTR 链上)。

---

## 5. 实施步骤(可执行)

- **S1 · 干净重构(解 double-count)** — 让"上膛"用的前瞻因子**移出 A 加分桶**、只走调节通道(二选一):
  - (a) 上膛因子从 `module_a_factors` 的加分列表移除,只保留在 `_ARM_HIGH/_ARM_LOW`;或
  - (b) 引入一组 **leading-only** 数据(只上膛不加分),A 加分桶里换成纯同步因子。
  - 验收:flag 关时逐字节不变;flag 开时 real_rate/dollar 不再同时出现在 A 加分与 arming。
- **S2 · 校准** — sweep `arm_then_fire.high_pctl/low_pctl/relief_per_factor/relief_cap`(`config.json` 已有块),选稳健高原而非最优点。
- **S3 · PBO gate** — 复用 `scripts/flag_gate.py` 框架:baseline vs arm-on,跑 walk-forward OOS + PBO + DSR;**额外加 lead-time 指标**(信号到后续 MaxDD 触底的交易日距离 / 标注顶前的命中提前量),因为 top-line CAGR/Sharpe 测不出"早"。
- **S4 · 人翻开关** — 过门(PBO<0.5 且 MaxDD 不恶化且 lead-time 改善)才把 `use_arm_then_fire` 翻 true,config 里写 provenance(仿 `_risk_calibration`)。

涉及文件:`core/scoring/scorer.py`(_arming_relief / 因子注册)、`core/scoring/factors_risk.py`、`core/decision/verdict.py`(status_from_score relief)、`config.json`(features / arm_then_fire)、`scripts/flag_gate.py`(加 lead-time 指标)。

---

## 6. 验收标准(达标才上线,否则 LOCKED)

1. **关时逐字节不变**(全 payload 含 input_hash,多日对照)。
2. **double-count 消除**:上膛因子不再重复计入 A 加分(单测断言)。
3. **lead-time 改善**:标注顶上,信号提前量中位数 > baseline(这是 F7 的主指标,不是 CAGR)。
4. **OOS 稳健**:walk-forward PBO < 0.5,且 **MaxDD 不恶化**(逃顶系统硬约束)。
5. 任一不达标 → 停在"管线就绪 / LOCKED",开关由人翻。

---

> 一句话总览:**现在 = 用同步因子的时间点开火,前瞻信号被 cap 吞掉;F7 = 让前瞻信号在"上膛"时把开火时机提前,有效性提升在 lead-time 轴。** 但要先修 double-count + 校准 + PBO,且 6 年样本上收益可能温和。
