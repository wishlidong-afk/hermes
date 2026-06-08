# 逐行 Review — 评分/裁决/缺数据/置信/sizing 主链

**Date**: 2026-06-08
**Scope**: `src/hermes_escape_top/core/` 评分链 (`scorer` / `registry` / `module_a–d` / `hard_valves` / `verdict`) + 缺数据与质量引擎 (`data/quality.py`, `data/base.py`) + 置信脊柱 (`confidence/spine.py`) + sizing (`portfolio/sizing.py`, `invariants.py`) + 两条 pipeline。
**Method**: 逐行阅读 + grep 核实运行时连线。所有"未接上"结论均经 grep 确认无运行时调用方。
**Severity**: 🔴 高 / 🟠 中 / 🟡 低

> 性质提醒：本系统为只读风控（不下单），但硬阀门会建议 100% 清仓，因此"误触发"与"该触发未触发"都是高代价。本 review 的准星是**逃顶准确度 = 更早 + 更少假摔**。

---

## 一、决策完整性：文档/config/函数签名都写了，运行时没接上

> 这三条经 grep 全代码库确认：定义存在，但生产 `pipeline.py`（调 `score_symbol`）与整合 `core/pipeline.py` 均未实际启用。

### 🔴 F1 — 二次收盘确认（行动稳定器）是死代码
- **位置**: `core/decision/verdict.py:33,65`（`make_verdict(require_confirmation=False)`，`previous_status` 默认 None）
- **证据**: 全库无任何调用方传 `require_confirmation=True`，`previous_status` 从未被赋值。
- **影响**: 功能规格 §5「非硬阀门升级需第二个收盘确认」完全未生效 → 每个软信号升级**即时触发** → 假摔/抽搐式进出，砍错的成本直接打在收益上。
- **修法**: 生产 pipeline 落地"上一已确认状态"并把 `previous_status` + `require_confirmation` 串入 `make_verdict`；硬阀门不等待（保持现状）。

### 🔴 F2 — 滞回（hysteresis）未接
- **位置**: config `hysteresis.enter/exit`（`config.json:218`）；`verdict.status_from_score` 只用扁平 `status_thresholds`。
- **证据**: `grep hysteresis` 在运行时代码零命中。
- **影响**: 阈值边界（如 ~50 分）会在 REDUCE/HOLD 之间反复横跳——正是滞回要消除的抖动。
- **修法**: `status_from_score` 接受 `previous_status`，进/出用非对称阈值（进=enter、维持已持有级别用 exit）。

### 🔴 F3 — 可疑 K 线不降级硬阀门
- **位置**: `core/data/sanitize.py`（产出 `suspect_dates`，注释写 "hard valve downgrades to pending"）；`core/scoring/hard_valves.py:evaluate_hard_valves`（不接收 suspect 信息）。
- **证据**: `core/pipeline.py` 从不消费 `suspect_dates`；生产 `pipeline.py` 甚至不跑 sanitize（直接 `score_symbol`）。
- **影响**: 硬阀门触发即 100% 清仓（`verdict.py:34`）。一根坏 tick / 数据源抽风造成的假 -15%，可让系统满仓清空。**这是最贵的单点失败**：护栏写了却没装上。
- **修法**: `evaluate_hard_valves` 增加 `suspect: bool` 入参；当 `as_of ∈ suspect_dates` 时，触发降级为 `pending`（不直接 EXIT，需下个干净收盘确认）。

---

## 二、评分鲁棒性：信号会"静默熄灭"或被结构性稀释

### 🔴 F4 — 因子依赖"全有或全无"，缺一个字段整条因子归零
- **位置**: `core/scoring/registry.py:90`（任一 dependency 缺失 → score=0 + missing）。
- **最严重案例**: `D_F4 / D_S4 成分资金流` 依赖 = 9~10 只成分 × 3 字段 = **27 个依赖**，缺任意一只成分的任意一字段 → 整条龙头资金流因子熄灭（`Factor_Health` 里 nan/alive-some 即此因）。`A3 宽度`(3 字段)、`A6 资金流`(3 字段) 同理。
- **影响**: 顶部信号会因单一输入缺失而消失——对逃顶系统是危险的"假 HOLD"。
- **修法**: 按可得子集打分 + 覆盖率缩放（如 ≥70% 成分可得才计、分数按覆盖率归一）；或拆成 per-成分子因子，缺一只仅 N 减一。

### 🔴 F5 — 永不实现的占位因子长期吃掉盲区预算
- **位置**: `core/scoring/scorer.py:41-52,61`（`missing` 计入 `max_score=0` 的 `missing_only` 占位）；`verdict.py:60`（盲区 +1 级用此值）。
- **数据**: A2_CNN(2)+B5_social(4)+D-M4(4)+D-M5(3) = MSTR 永久 **+13** missing_weight；30 分盲区阈值里 13 分被"结构性永缺"占着。
- **矛盾点**: `scorer.py:43-49` 已算出干净的 `confidence_missing_weight`（仅 `max_score>0`），却只喂置信脊柱/sizing，**没喂 status/score**。同一系统两套 missing_weight，决策侧用了脏的。
- **影响**: 真正的临时数据中断更易触发盲区惩罚；`adjusted_score` 长期上偏。
- **修法**: status / 盲区 +1 / adjusted 全部改用 `confidence_missing_weight`；"结构性不可得"与"本应有却临时缺"分桶。

### 🟠 F6 — 7 个死因子里 5 个是"出生即死"，不是没信号
- **位置**: `module_a.py:10`(A2_CNN)、`module_b.py:15`(B5)、`module_d.py:102-103`(D-M4/D-M5) 均 `missing_only` 占位；B6 依赖只能向前攒的估值分位，历史几乎不填。
- **结论**: `Factor_Health` 判它们 dead 是**接线产物，不是统计结论**（直接回答"先验尸死因子"）。剩余 A2_NAAIM / A2_PCR 是真接了数据但**校准死**（见 F8）。
- **修法**: 要么接数据要么从 missing 记账摘掉，别让它们一边永远 0 分一边永远扣盲区。

### 🟠 F7 — A 模块封顶=20，把新加的前瞻因子稀释掉
- **位置**: `config.json:103`（`module_caps.A=20`）；`scorer.aggregate_modules` `min(score,20)`；`factors_risk.py` 可追加 11 个 ×4。
- **影响**: 启用 A 因子 max 之和已 ≈50，真到顶部同步类 A 因子单独就顶满 20 → 前瞻宏观因子在"最该起作用的时刻"边际为零、归因糊。你们已建更对的通道 `_arming_relief`(arm-then-fire)，但 `use_arm_then_fire=false` 关着，同时前瞻因子又被塞进封顶 A 桶 → 一信号两角色。
- **修法**: 前瞻宏观只走 arm-then-fire / 置信-regime 调节通道，从封顶 A 桶拿掉；一个信号定一个家。

---

## 三、校准

### 🟠 F8 — NAAIM / Equity PCR 阈值太松（IC≈0 是"天天报警"）
- **位置**: `module_a.py:248`（代码自检注释已写："defaults fire ~63% of days → low discrimination"，收紧到 pctl≥85 可使前瞻收益边际翻倍）；PCR `module_a.py:259`（`pcr<=0.62/pctl<=20` 偏宽）。
- **结论**: 非数据问题，是阈值问题——**最便宜的一次 IC 提升**，诊断已写在代码里。
- **修法**: NAAIM/PCR 收紧到欧元区尾部分位；config 驱动、回测确认。

---

## 四、小问题

### 🟡 F9 — `missing_field_weight` 子串匹配 + 首个命中
- **位置**: `data/quality.py:58`（`pattern in field_name`）。因子增多后有"短 pattern 遮蔽长 pattern"隐患，目前未踩雷。
- **修法**: 改精确键查表 + 显式 dedup key。

### 🟡 F10 — 硬阀门里第二套 EMA 计算
- **位置**: `hard_valves.py:180`（`_below_ema_days` 在 ema 列缺失时即时 `indicator_frame` 重算）与 snapshot EMA 两条路径，有不一致风险。
- **修法**: 统一指标单一真相源。

---

## 修复优先级

**第一梯队 — 止血（改动小、收益确定，本次开工）**
1. F1+F2 滞回 + 二次收盘确认接线（config/函数现成，串 `previous_status`）。
2. F3 可疑 K 线降级硬阀门（防灾难性误清仓）。
3. F5+F6 缺数据记账改用 `confidence_missing_weight` + 摘掉永缺占位。
4. F4 因子部分可得化（先救 D_F4/D_S4/A3/A6）。
5. F8 NAAIM/PCR 收紧到尾部。

**第二梯队 — 模型层提准（需回测/PBO 把关）**
6. 分数 → 概率校准（E2）：`final_score → P(20日回撤≥X)`，阈值打在概率上。
7. 前瞻 vs 同步解耦（F7）：启用并用 PBO 校准 arm-then-fire，把 A9–A19 迁出封顶 A 桶。
8. 增量 IC 门禁：新因子须在控制 C10 后仍有增量 IC 方可进封顶桶。

---

## 验证准则（每条修复随附测试）
- F1/F2：抖动序列断言不再来回跳级；硬阀门仍即时。
- F3：可疑 K 线日断言硬阀门降为 pending；干净序列 0 误触发不变。
- F5/F6：摘除占位后 missing_weight 下降、blind_spot 触发时机回归真实；flags-off 行为对照。
- F4：缺单只成分时因子仍按覆盖率出分（非归零）。
- F8：收紧后报警频率显著下降、前瞻 IC 上升。
