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
- `reports/GAP_AUDIT_REPORT.md`、`reports/SPEC_TRACE_REPORT.md`：缺口审计与规格追踪报告。

## 当前验收快照

- 数据底座：已实现历史行情回填、路线腿代理、PIT 快照、manifest 固化。
- 软数据：已接入 FRED、CBOE、AAII、成分股广度、MSTR BTC 代理等评分输入。
- 策略执行：已实现逃顶裁决、硬阀门、资金路由、镜像参考和回测 runner。
- 回测窗口：由于 FNGU 上市历史限制，完整三标的有效窗口为 2025-02-20 至 2026-05-29。
- 回测结果：`Backtest_FULL.md` 中记录 Final Value、CAGR、Max Drawdown、Sharpe、Sortino 等核心指标。
- 自动测试：本地最近一次验收为 78 tests passed。

## 线上线下同步维护规则

1. 本地继续搭建后，优先更新 `/Users/liweishi/Desktop` 的总日志与 `.hermes/.../reports` 下的阶段报告。
2. 每次推送 GitHub 前，将上述 Markdown 同步到本目录，保持 `building/` 为远端可读进度镜像。
3. 重大逻辑变更必须同步更新 `SPEC_TRACE_REPORT.md` 和 `STATUS.md`。
4. 数据源、回测窗口、缺失权重或评分阈值变化，必须同步更新 `NEXT*_REPORT.md` 或新增对应报告。
5. 验收结果以本目录 Markdown 与本地测试输出共同为准。
