# P4 ConfidenceSpine 骨架执行日志

更新时间：2026-06-01

## 目标

按 `INTEGRATION_ARCHITECTURE.md` Phase 0-I 的要求，先落地整合地基的第一块：公共契约 + 置信脊柱。目标不是立刻改变交易裁决，而是建立后续数据净化、故障转移、漂移、脆弱度和多源分歧的统一仲裁入口。

## 已完成实现

1. 新增 `core/contracts.py`。
   - `Field`
   - `Verdict`
   - `ConfidenceState`
   - `RiskState`
   - `SizingDecision`

2. 新增 `core/confidence/spine.py`。
   - `compute_confidence(...) -> ConfidenceState`
   - 组件：`data / source / stale / drift / fragility / agreement`
   - 木桶加权：`confidence = weakest_weight * min_component + (1 - weakest_weight) * geomean`
   - 模式：`NORMAL / CAUTION / DEGRADED`
   - 缺失信号按 0.5 中性不确定处理并写入 note，不允许默认为安全。

3. 新增 `core/confidence/__init__.py`。

4. 新增 `tests/test_confidence_spine.py`。
   - 健康输入 → NORMAL
   - source failover → CAUTION
   - drift alert → DEGRADED
   - 缺失子信号 → DEGRADED/低置信，不视作安全

## 验证

- `python3 -m unittest hermes_escape_top.tests.test_confidence_spine hermes_escape_top.tests.test_next3_calibration`：8 tests OK。
- `python3 -m unittest discover -s hermes_escape_top/tests`：94 tests OK。
- `python3 -m unittest discover -s tests`：11 tests OK。

## 当前状态

P4 进入 `IN-PROGRESS / PHASE0-CONTRACTS-SPINE-DONE`。

未接入 live pipeline；不改变当前评分、裁决、仓位和路由结果。下一块建议继续实现 RiskEngine 最小骨架或把 ConfidenceState 透传到只读报告。
