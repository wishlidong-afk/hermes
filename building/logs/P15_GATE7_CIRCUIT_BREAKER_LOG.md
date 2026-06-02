# P15 Gate 7 — 熔断端到端测试

**时间**: 2026-06-02  
**范围**: 注入四类异常，验证 Governance 完整熔断链路  
**结果**: 23/23 测试通过；293 总测试 OK；**7/7 道系统级总闸全部通过**

---

## 测试覆盖（6 类 × 共 23 个测试）

### Gate 7.1 — 坏数据 → DEGRADED（5 个）

| 注入 | 期望 | 结果 |
|---|---|---|
| `data_conf=0.0` | DEGRADED，weakest=data | ✅ |
| `failover.is_degraded=True` | CAUTION 或 DEGRADED | ✅ |
| `data_conf=None`（缺失） | notes 含 "missing"，不视作安全 | ✅ |
| `staleness_days=7`（tau=3） | stale 组件 < 0.2 | ✅ |
| 全健康输入 | NORMAL > 0.95（无误报） | ✅ |

### Gate 7.2 — 强分歧 → REVIEW 级别（4 个）

| 注入 | 期望 | 结果 |
|---|---|---|
| EXIT vs meta=0.05 vs STRONG_TREND | disagreement > 0.40 | ✅ |
| HOLD + 一致信号 | disagreement < 0.30 | ✅ |
| 高分歧喂置信脊柱 | decision_confidence < 0.95 | ✅ |
| 无 meta/mirror 单源 | disagreement = 0.0 | ✅ |

### Gate 7.3 — 高脆弱度 → CAUTION（4 个）

| 注入 | 期望 | 结果 |
|---|---|---|
| 刀尖决策（total=75，阈值=75） | fragility > 0.3 | ✅ |
| 安全决策（total=10） | fragility < 0.05 | ✅ |
| fragility=0.8 喂脊柱 | mode ≠ NORMAL | ✅ |
| fragility=0 | mode = NORMAL（无误报） | ✅ |

### Gate 7.4 — PSI 漂移 → DriftMonitor alert（4 个）

| 注入 | 期望 | 结果 |
|---|---|---|
| 分布偏移 +30pt | alert=True，psi>0.25 | ✅ |
| 相同分布 | alert=False | ✅ |
| alert=True 喂脊柱 | DEGRADED，drift 组件=0.0 | ✅ |
| C10 IC 从 0.38 衰减到 0.08 | ic_decay_alert=True | ✅ |

### Gate 7.5 — DEGRADED 下 optimizer 权重收缩（2 个）

| 验证 | 结果 |
|---|---|
| DEGRADED(0.3) 总权重 ≤ NORMAL(1.0) 的 35% | ✅ |
| EXTREME_CORR + DEGRADED 下 R3 仍 100% 不违反 | ✅ |

### Gate 7.6 — 归因 + 冠军挑战者人工门控（4 个）

| 验证 | 结果 |
|---|---|
| 贡献度之和 = 1.0 | ✅ |
| 最高贡献因子排第一 | ✅ |
| 反事实 = total - factor | ✅ |
| 挑战者远优于冠军时 requires_human_gate=True | ✅ |

---

## 7 道系统级总闸 — 全部通过

| # | 总闸 | 状态 |
|---|---|---|
| 1 | 单一风险源（唯一 cov） | ✅ |
| 2 | 单一处置入口（无 scaler 链） | ✅ |
| 3 | R3 不变式 100% | ✅ |
| 4 | 置信脊柱贯通 | ✅ |
| 5 | PBO<0.5 + CI | ✅ |
| 6 | 因子健康 + 概率校准 | ✅ |
| **7** | **可解释可治理（熔断端到端）** | ✅ **DONE** |

**M3 → 迈向 M4 的全部工程门控已通过。**

## 状态

P15: **DONE / GATE-7-COMPLETE / ALL-7-GATES-PASSED**
