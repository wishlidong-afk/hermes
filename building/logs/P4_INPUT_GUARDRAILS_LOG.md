# P4 Phase 0 输入护栏执行日志（E1 净化 + E30 故障转移）

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` Phase 0 的要求，构建输入护栏层。E1 数据净化防止假硬阀门触发；E30 故障转移提供有序源切换。两者产出的 `data_confidence` 和 `failover_state` 直接喂入 ConfidenceSpine。

## 已完成实现

### E1 数据净化 `core/data/sanitize.py`

| 检测类型 | 严重度 | 逻辑 |
|---|---|---|
| BAD_TICK | HIGH | 零成交量 + 极端价格变动（>15%）→ 假 K 线 |
| SPLIT_MISMATCH | MEDIUM | 隔夜缺口 > 40% → 可能的拆股/复权异常 |
| STALE | MEDIUM | 连续 N 日（默认3）收盘价完全相同 |
| OUTLIER | LOW | 收益 > N sigma（默认5）→ 标记但不删除 |
| CROSS_SOURCE | HIGH | 与交叉验证源差异 > 2% |

**关键规则**：
- HIGH 异常日期加入 `suspect_dates` → 如果硬阀门在该日触发，降级为"待确认"
- 真实崩盘（高成交量 + 大跌）**不会**被误标为 BAD_TICK
- data_confidence = 1.0 - 加权异常惩罚

### E30 故障转移 `core/data/failover.py`

- `FailoverSource(name, [SourceSpec(...), ...])`：有序数据源列表
- `fetch(as_of)` → `FailoverResult`：按优先级尝试，健康检查 + 自动切换
- `to_confidence_input(result)` → 直接可喂 ConfidenceSpine 的 `failover_state` dict
- Primary 可用 → is_degraded=False；切到 backup → is_degraded=True + rank 标注
- 全部失败 → data=None, active_source="NONE", 优雅降级

### 测试（11 个）

| 测试 | 覆盖 |
|---|---|
| 零量极端移动→BAD_TICK HIGH | E1 坏 tick |
| 真实崩盘（高量大跌）不误标 | E1 安全 |
| 连续相同收盘→STALE | E1 陈旧 |
| 交叉源差异→CROSS_SOURCE | E1 跨源 |
| 干净数据→高 confidence | E1 正常 |
| 空 DataFrame | E1 边界 |
| Primary 健康→无降级 | E30 正常 |
| Primary 宕机→fallback + is_degraded | E30 降级 |
| 全部宕机→优雅空结果 | E30 边界 |
| 健康检查失败→跳过 | E30 健康检查 |
| to_confidence_input 格式 | E30 接口 |

## 数据流接线

```
数据源 → FailoverSource.fetch()  → FailoverResult
                                    ├─ data → sanitize_ohlcv() → SanitizeResult
                                    │                              ├─ clean_df → 下游特征/评分
                                    │                              ├─ data_confidence → ConfidenceSpine.data_conf
                                    │                              └─ suspect_dates → 硬阀门"待确认"降级
                                    └─ failover_state → ConfidenceSpine.failover_state
```

## 当前状态

P4 Phase 0 输入护栏 `DONE`。

Phase I 全部 7 个核心组件 + Phase 0 输入护栏（2 个）= 9 个组件全部骨架完成。
