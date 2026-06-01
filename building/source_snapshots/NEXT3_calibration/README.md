# NEXT-3 Calibration Source Snapshots

本目录保存 2026-06-01 NEXT-3 稳定高原校准相关的关键本地源码快照，便于 GitHub 文档仓库在尚未承载完整 `.hermes` 包源码时仍可审计实现。

## 快照文件

- `hermes_escape_top/scripts/calibrate_next3_v2.py`：full-proxy walk-forward + real-only sensitivity 校准脚本。
- `hermes_escape_top/tests/test_next3_calibration.py`：PBO、rank percentile、阈值网格、fixed highland selector 单测。
- `hermes_escape_top/core/routing/leg_proxy.py`：路由腿代理性能修复，避免 `trend_synth` 重复重建。
- `tests/golden/test_v25_parity.py`：golden parity 浮点容差修复。
- `tests/golden/fixtures/v25_score_projection_golden.json`：P0 合成历史后的 v25 golden fixture。

## 验收

- `python3 -m unittest discover -s tests`：11 tests OK。
- `python3 -m unittest discover -s hermes_escape_top/tests`：90 tests OK。
