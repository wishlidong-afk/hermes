# P4 ConfidenceSpine Source Snapshots

本目录保存 2026-06-01 P4 整合地基第一块的本地源码快照。

## 快照文件

- `hermes_escape_top/core/contracts.py`：共享契约 dataclasses。
- `hermes_escape_top/core/confidence/spine.py`：`compute_confidence` 纯函数。
- `hermes_escape_top/core/confidence/__init__.py`：导出入口。
- `hermes_escape_top/tests/test_confidence_spine.py`：ConfidenceSpine 单测。

## 验收

- `python3 -m unittest hermes_escape_top.tests.test_confidence_spine hermes_escape_top.tests.test_next3_calibration`：8 tests OK。
- `python3 -m unittest discover -s hermes_escape_top/tests`：94 tests OK。
- `python3 -m unittest discover -s tests`：11 tests OK。

## 说明

本阶段只建立契约和置信仲裁纯函数，尚未接入 live pipeline，因此不会改变当前评分、裁决、仓位和资金路由结果。
