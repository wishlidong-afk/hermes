# 🔴🟡 处理结果 + 需你确认清单

> **日期：2026-06-02** ｜ 目标:修复 5-pass review 里所有红/黄项;**会改动已验证数字或属破坏性/他人领域的,列出待确认**(不偷偷重开已验证的回测/PBO)。

## ✅ 本轮已直接修复(安全、行为中性或纯增量)

| 项 | 级别 | 处理 |
|---|---|---|
| 审计时间戳非确定(`core/pipeline.py` `datetime.utcnow()`) | 🔴 | 改为 **as_of 锚定**(`{as_of}T00:00:00+00:00`),恢复"逐位一致"。决策无关、无测试断言它。注:活的每日审计(`write_audit_record`)本就无时间戳、已确定;此处修的是**回测/旧 pipeline 路径**。 |
| 缺回归守门测试 | 🟡 | 新增 `tests/test_review_invariants.py`(6 项):Kelly 默认关、Kelly 无校准 p_act 必报错、live flags 默认关、健康输入≠DEGRADED、R3 不变式、只读红线(执行计划仅 advisory)。**套件 316→322,全绿。** |
| 旧引擎退役无验收清单 | 🟡 | 见下「退役验收清单」。 |

> 注:🔴"审计确定性"经核查,**活的决策路径本就确定**(`write_audit_record` 无时间戳),
> 严重度实际低于初判;已修的是回测/旧 pipeline 路径的 `utcnow`。

## 旧引擎(`compute_portfolio_risk`)退役验收清单

满足以下全部即可安全删除旧引擎 + 旧 `size_portfolio` 链:
1. [ ] Phase III 迁移正式人审通过(110/0.90 已过 PBO 门,待签)。
2. [ ] `run_full.py` 回测引擎切到 `optimize_targets`(目前用旧链作 baseline 对照)。
3. [ ] `web/render.py` 去掉 `effective_gross_scaler` 兼容键,只读 `gross_scaler`。
4. [ ] `tests/test_phase6_portfolio_risk.py` 改写或移除(7 处断言依赖旧引擎 + payload)。
5. [ ] payload 去掉 `portfolio_risk` 字段或替换为 RiskEngine 的等价输出。
6. [ ] 删除后全套测试 + 全窗口回测重跑,R3=0/errors=0 不变。

---

## ⚠️ 需你确认的(没有自动改,附原因)

### 🔴 A. 消除三套并存代码树
canonical 包 / 遗留 `core/` 树 / v25 单体 `escape_top_system.py`。这是最大根因,但属**大型重构 + 需全量重验证**,且单体是另一套独立逻辑。**确认后**我才动——并需说明你想"留哪一套为真相"。

### 🟡 B. 数值稳健三项(会改动已验证数字!)
- HAR-RV 加岭/条件数防共线性;
- EWMA 方差初始化 `r[0]**2` → 前 5–10 日均值;
- 收缩从启发式 → 真 Ledoit-Wolf(用原始观测)。

**为何要确认**:这三项都会改变 vol/cov→gross→仓位,从而**让刚验证过的全窗口回测(CAGR21.5%/MaxDD−25.6%/Sharpe1.01)和 PBO=0.077 失效**。要做的话,我会**改完立刻重跑全窗口 + 全网格 PBO 重验证**(约 5h)。确认即整包推进。

### 🟡 C. 回测 exact optimizer 提速(warm-start/缓存)
warm-start 可能让 SLSQP 落到不同局部最优 → **改动回测数字**。同样需重验证。确认后做。

### 🟡 D. IBKR 降级 → failover 真信号
把 IBKR 连接失败/数据降级喂给置信脊柱的 `failover_state`。这正好补上推迟的 **#6(failover)**——但你上轮选了"维持单源"。要接就改这条,**会改变 confidence 行为**,确认后做。

### 🟡 E. v25 golden 生成器固定采样日期
现在它 glob 所有 `daily_raw_data_*.json` fixture,新增 fixture 会让 golden 漂移。固定日期集能根治,但**属 v25 单体(他人)测试设计**,且要重生成 golden。建议由单体 owner 定,故列出。

### 🟡 F. 低价值/高风险的两项(建议不动)
- **binding-constraint 标签精确化**:仅当 Kelly/liquidity/CPPI 启用(默认全关)时标签才不准;当前配置下**标签已准确**。改它要动决策输出逻辑,低收益。
- **`_below_ema_days` 重算指标提速**:在**硬阀门决策关键路径**上,纯提速、有回归风险。不值当为性能动它。

---

**一句话**:能安全做的(确定性、回归守门、退役清单)已做完,套件 322/0 全绿。
**B/C/D 会动已验证数字或触及你已推迟的项,A 是大重构,E 属他人领域,F 低价值高风险**——
这些等你点头。你回「A 做/B 做并重验证/…」我就按选定的开工。
