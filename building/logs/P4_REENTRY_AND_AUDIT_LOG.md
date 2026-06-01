# P4 Reentry Tracker + Audit Exporter 执行日志

更新时间：2026-06-01

---

## 模块 1：Reentry State Tracker（`core/reentry/tracker.py`）

### 解决的问题

Phase 9 (3-3-4 再建仓) 标注 "T1/T2 活跃状态仍未持久化"。此模块实现 T1/T2/T3 三档建仓的完整状态管理和 JSON 持久化。

### 已完成

| 函数/类 | 功能 |
|---|---|
| `TrancheState` | 持久化状态：phase / entry_date / entry_price / lock_reasons |
| `check_three_locks(state, as_of, ...)` | 三锁门控：时间锁(11交易日) + 情绪锁(<19) + 结构锁(C<5+背离解除) |
| `advance_tranche(state, lock_check, ...)` | 状态推进：LOCKED → T1 → T2 → T3（按条件逐级） |
| `serialize_states / deserialize_states` | JSON 序列化/反序列化 |

### 三档条件（按 FUNCTIONAL_SPEC §8）

- **T1 (30%)**：雷达 > EMA20 + MACD 金叉
- **T2 (30%)**：T1 浮盈 + 雷达突破 20 日高 + 在 EMA20 上方
- **T3 (40%)**：T1/T2 浮盈 + 大盘 252 日新高

### 安全规则

- 有卖出信号或硬阀门 → 强制 LOCKED，无条件
- 卖出后 11 个交易日内不得建仓
- 总分 ≥ 19 → 情绪锁不放行

### 测试（13 个）

- 三锁全通 / 时间锁阻塞 / 情绪锁阻塞 / 结构锁阻塞
- 硬阀门强制锁 / 卖出信号强制锁
- LOCKED 保持 / T1 激活 / T2 激活
- T3 需大盘新高 / T3 有大盘新高则激活
- JSON round-trip / 合法 JSON

---

## 模块 2：Audit Exporter（`core/audit/exporter.py`）

### 解决的问题

Pipeline 产出的 audit dict 需要转换为可消费格式：WebUI (JSON)、人工审阅 (Markdown)、后验追踪 (signal journal JSONL)。连接 Phase 15 (集成) 到 Phase 14 (WebUI)。

### 已完成

| 函数 | 功能 |
|---|---|
| `export_json(audit, path)` | 审计 → 格式化 JSON，可选写文件 |
| `export_markdown(audit)` | 审计 → 7 段 Markdown 日报（Scores/Verdicts/Risk/Confidence/Weights/Regime/Drift） |
| `build_signal_entry(...)` | 构建 signal journal 条目（供后验 P&L） |
| `export_signal_journal(entries, path)` | JSONL 追加导出 |

### Markdown 输出结构

```
# Hermes Daily Audit — 2026-06-01
## Scores          (symbol × total 表格)
## Verdicts        (symbol × status × rule_weight 表格)
## Risk            (portfolio_vol / gross / regime / binding)
## Confidence      (mode / confidence / weakest_link)
## Target Weights  (symbol × weight × binding 表格)
## Regime          (per-symbol 体制标签)
## Drift           (PSI + alert 状态)
```

### 测试（8 个）

- JSON 合法 / 全字段存在
- Markdown 含标题 / 含全部 7 段 / 含标的名 / mode 加粗
- Signal entry 字段齐全 / JSONL 格式正确

---

## 当前状态

| 缺口 | 之前 | 之后 |
|---|---|---|
| Phase 9 T1/T2 持久化 | 未持久化 | ✅ JSON 序列化 |
| Phase 14/15 审计导出 | 无结构化导出 | ✅ JSON + Markdown + JSONL |
