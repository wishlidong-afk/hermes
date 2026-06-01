# Hermes Building Progress

本目录用于同步 Codex 本地搭建进度与 GitHub 线上仓库，作为后续继续维护、验收、回滚和交接的进度中枢。

## 同步范围

- `desktop/逃顶与镜像系统逻辑说明.md`：用户侧总指导文件与验收口径。
- `desktop/Hermes逃顶镜像系统全量搭建日志_2026-06-01.md`：截至 2026-06-01 的全量搭建日志、milestone、验证结果和剩余风险。
- `desktop/Hermes逃顶镜像v3逐条搭建追踪.md`：v3 逐条搭建追踪记录。
- `STATUS.md`：本地 Hermes escape-top 包的当前系统状态。
- `reports/Phase*_REPORT.md`：分阶段实现报告。
- `reports/NEXT*_REPORT.md`：NEXT 阶段数据底座、软数据和回测验收报告。
- `reports/Backtest_FULL.md`：正式回测结果报告。
- `reports/Calibration_v2.md` / `reports/calibration_v2.json`：NEXT-3 稳定高原参数校准报告与机器可读 artifact。
- `reports/GAP_AUDIT_REPORT.md`、`reports/SPEC_TRACE_REPORT.md`：缺口审计与规格追踪报告。
- `logs/`：每个可验收施工部分的执行日志。
- `source_snapshots/`：当前 GitHub 文档仓库未承载完整本地代码时，用于同步关键代码变更快照，确保线上线下可对账。

## 当前验收快照

- 数据底座：已实现历史行情回填、路线腿代理、PIT 快照、manifest 固化。
- 软数据：已接入 FRED、CBOE、AAII、成分股广度、MSTR BTC 代理等评分输入。
- 策略执行：已实现逃顶裁决、硬阀门、资金路由、镜像参考和回测 runner。
- 回测窗口：高置信 real-only 为 2025-02-20 至 2026-05-29；full-proxy 为 2018-01-02 至 2026-05-29。
- 回测结果：`Backtest_FULL.md` 与 `Backtest_FULL_2018_2026.md` 并排记录核心指标；P1 已完成。
- 参数校准：NEXT-3 已完成 v2 稳定高原校准，候选参数为 `EXIT=75 / DEFENSIVE_EXIT=65 / REDUCE=50 / TRIM=35 / WATCH=20`。
- 校准门控：Deployment fixed PBO=0.1538 PASS；full-proxy MaxDD=-28.01% PASS；real-only MaxDD=-10.63% PASS；real-only rank=0.7692 PASS。Train-greedy PBO=0.6154 未过，仅保留为过拟合警报。
- 自动测试：本地最近一次验收为 `90 package tests OK + 11 golden tests OK`。
- P0 最新状态：合成杠杆历史严格接缝调整门控已通过；P1/P2 阻塞已解除，NEXT-3 现为 `DONE / M3-COMPLETE / STABLE-HIGHLAND-PASSED`。

## 线上线下同步维护规则

1. 本地继续搭建后，优先更新 `/Users/liweishi/Desktop` 的总日志与 `.hermes/.../reports` 下的阶段报告。
2. 每次推送 GitHub 前，将上述 Markdown 同步到本目录，保持 `building/` 为远端可读进度镜像。
3. 重大逻辑变更必须同步更新 `SPEC_TRACE_REPORT.md` 和 `STATUS.md`。
4. 数据源、回测窗口、缺失权重或评分阈值变化，必须同步更新 `NEXT*_REPORT.md` 或新增对应报告。
5. 验收结果以本目录 Markdown 与本地测试输出共同为准。
6. 若本地实现代码尚未迁入 GitHub 主源码目录，必须把本阶段关键源码复制到 `source_snapshots/`，避免只有口头进度没有可审计实现。
