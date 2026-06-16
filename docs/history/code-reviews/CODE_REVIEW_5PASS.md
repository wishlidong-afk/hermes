# 五轮全局 Code Review — 提升点汇总

> **日期：2026-06-02** ｜ 对 canonical 包 `hermes_escape_top` 做 5 个不同视角的全局审查。
> 每轮列"发现 → 提升建议",并标优先级(🔴 高 / 🟡 中 / 🟢 低)。
> 本轮所有修复已落地、316/316 测试绿、全窗口回测 R3=0/errors=0、train-greedy PBO=0.077。
> 以下是**在此之上**还能提升的点。

---

## 第 1 轮 · 正确性与数值稳健

- 🟡 **HAR-RV 无共线性防护**(`risk_engine.har_rv_forecast`):`rv_daily/rv_w/rv_m` 高度相关时
  `lstsq` 解不稳定。建议加岭项或条件数检查,beta 异常时回退 EWMA。
- 🟡 **EWMA 方差初始化** `var=r[0]**2` 对首观测敏感。建议用前 5–10 日均值初始化。
- 🟡 **shrinkage 仍是启发式**(`_shrinkage_intensity = n_pairs/(n_obs+n_pairs)`),非真 Ledoit-Wolf。
  真 LW 需原始观测;若要更准,应在数据级用收益样本算最优收缩强度。
- 🟢 **硬阀门阈值是魔法数**(`hard_valves.py`:−0.15/−0.22/−0.18/MA200/0.96…全部硬编码)。
  与"参数须可校准"的理念冲突;建议迁到 config,便于回测调参与审计。
- 🟢 **`portfolio_cvar` 历史法在尾部样本<20 直接返回 0**——在极短窗口会低估风险。已有保护,
  建议显式标记"CVaR 不可估"而非静默 0(下游会当成"无尾部风险")。

## 第 2 轮 · 架构与耦合

- 🔴 **三套并存的代码树**:`hermes_escape_top/`(canonical)+ 遗留 `core/` 重复树
  + 单体 `scripts/escape_top_system.py`(v25)。这是最大的系统性风险:同一逻辑多处实现,
  golden 测单体、活路径测包,二者会持续分叉。**建议路线**:把单体退役为"包的薄包装",
  或反之,最终只留一套真相。
- 🟡 **两个 pipeline**:`pipeline.py`(活)与 `core/pipeline.py`(P4 旧,含 `datetime.utcnow()`)。
  确认旧的是否仍被引用;若否,删除以免误用。
- 🟡 **旧风险引擎按设计保留作 baseline**(已记录),但应设一个明确的"退役验收清单",
  避免它无限期半活着。
- 🟢 **`web/render.py` 用 `risk.get('gross_scaler', risk.get('effective_gross_scaler'))`** 兼容两套键名
  ——是双引擎遗留的痕迹,单一源后可简化。

## 第 3 轮 · 性能与可扩展

- 🟡 **回测 exact optimizer 慢**:2113 日 × 21 场景 ≈ 数小时(每日每场景一次 SLSQP)。
  `_fast_project_targets` 是近似快路径,但与 exact 可能分叉。建议:① 缓存按 (cov,bounds) 量化的解;
  ② 或给 SLSQP 用上一交易日解作 warm-start,收敛更快。
- 🟡 **`_below_ema_days` 每次 `frame.copy()` + 可能 `indicator_frame()` 重算**
  (`hard_valves.py`),在回测里每标的每日多次调用。建议预计算指标列、避免重复 copy。
- 🟢 **`risk_contribution` 等用 Python 循环**;腿数小无碍,扩到多标的时应向量化。
- 🟢 **grid solver `itertools.product`** 已加 `max_points` 上限,但 n 大时仍指数;
  >4 腿应切真正的凸求解器(cvxpy/OSQP)。

## 第 4 轮 · 可测试性与可观测/确定性

- 🔴 **审计时间戳非确定**:`core/pipeline.py:353` 与 `core/audit/exporter.py` 用
  `datetime.utcnow()`。违反"同输入逐位一致"——同一 as_of 两次跑审计不一致,难做 golden/复现。
  **建议**:审计时间戳改用 `as_of` 驱动,或把易变字段移出 hash 范围。
- 🟡 **v25 golden 生成器采"滑动日期窗口"**(随数据时钟取近端),导致 golden 不可长期复现。
  建议固定采样日期集,使 golden 只在逻辑变更时才需重生成。
- 🟡 **`optimize_targets` 的 binding-constraint 标签**:启用 Kelly/liquidity/CPPI 改写 upper_bounds 后,
  "CONFIDENCE" 标签可能名不副实。建议按"哪个 cap 实际触顶"精确标注,提升可解释性。
- 🟢 **35 处 `except Exception`**:多数是合理的 fail-safe,但建议收窄异常类型 + 记一条 warning,
  避免真 bug 被静默吞掉(尤其 `_optimize_sizing` 的异常回退、`_drift_state` 的兜底)。
- 🟢 **缺针对"修复不变式"的回归测试**:已有 `verify_followup_fixes.py`(独立),
  建议把"健康输入→非 DEGRADED""Kelly 默认关""R3 恒成立"纳入正式 pytest 套件,长期守门。

## 第 5 轮 · 安全与运行红线

- 🟢 **三条红线代码层基本到位**:只读不下单、缺数据→低 confidence(已落到 `_data_confidence`)、
  硬阀门优先。建议加一条**断言级测试**:`sizing` 输出的任何 `target_weight` 必有
  `mode in {twap,execute_now}` 且无真实下单调用路径(防回归)。
- 🟡 **IBKR 只读对账**:`pipeline` 里 `ibkr.enabled` 默认关,连接失败仅打印。建议:
  ① 连接信息走 config/env 不入库;② 失败时在 payload 标 `ibkr.degraded=true` 并喂 failover 信号
  (正好补上当前缺失的 failover 真信号)。
- 🟡 **`feature flags 默认 OFF` 需有测试守护**:确保没有任何 flag 在合并中被默认打开
  (Kelly 这次就是反例——曾被默认 True)。建议加"所有 live 开关默认 False"的元测试。
- 🟢 **机密**:仓库目前只推源码,未含 config/data/ibkr 凭证(已在同步时把关)。建议在 repo 加
  `.gitignore` + 一个 CI 机密扫描,防止将来误推 `.hermes` 全量。

---

## 跨轮最高优先级(给 owner 的 3 件事)

1. 🔴 **消除三套代码树**——这是所有"分叉/golden 漂移/双引擎"问题的总根。定一套真相,其余降为包装或删除。
2. 🔴 **审计确定性**——`utcnow()` 改 `as_of` 驱动,恢复"逐位一致",让 golden/复现可信。
3. 🟡 **把魔法数与 live 开关 config 化 + 加元测试守护**——硬阀门阈值、Kelly/CPPI 开关等,
   既便于校准,也防止"默认被打开"这类回归。

> 说明:以上均为**在已达成可用、三重验证状态之上**的增量提升,非阻塞项。
> 阻塞性问题(脊柱旁路、双 gross、Kelly 误用、mu 假清仓、numpy-2.4 兼容、回测验证)
> 已在前几轮全部解决。
