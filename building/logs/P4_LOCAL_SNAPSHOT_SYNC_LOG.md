# P4 GitHub 快照本地落地日志

更新时间：2026-06-01

## 目标

读取 GitHub `wishlidong-afk/hermes` 最新 `building/` 与 `source_snapshots/`，将远端 P4 Phase 0-I + Pipeline 快照真正同步到本地 `.hermes` 实现，并修复本地运行环境中的接口差异。

## 已拉取版本

- GitHub 分支：`hermes-docs`
- 起点：`0e202a7`
- 拉取后：`0e4d311`
- 拉取方式：`git fetch origin && git pull --ff-only origin hermes-docs`

## 已落地内容

从 `building/source_snapshots/P4_*` 同步到本地 `.hermes`：

- Audit exporter
- Drift monitor
- FactorLab
- Governance
- Input guardrails：sanitize / failover
- MarketContext
- Integration config
- Unified pipeline
- Reentry tracker
- RiskEngine
- SizingOptimizer
- Tax awareness
- ValidationHarness

## 本地修复

1. `integration_config` 路径修复。
   - 原快照路径为 `hermes_escape_top/config/integration_config.py`。
   - 本地已有 `hermes_escape_top/config.py` 模块，不能同时作为 package。
   - 已改为 `hermes_escape_top/integration_config.py`，并更新测试导入。

2. Python 3.9 兼容修复。
   - `date(2026, 06, 1)` 改为 `date(2026, 6, 1)`。

3. RiskEngine 下行相关保守化。
   - `downside_corr` 使用 full-sample correlation 作为 tail correlation floor。
   - 避免小样本尾部估计把风险看得比常态更安全。

4. SizingOptimizer shadow-mode return proxy 修复。
   - 在真实 expected-return 模型未接入前，提高临时 `base_mu` proxy，避免优化器在正常置信度和低置信度下都塌缩到近零，导致 confidence shrinkage 不可检验。
   - R3 clamp 仍保留，保证不会比规则裁决更激进。

5. MarketContext 测试消除 pandas chained assignment 警告。
   - 改用 `.loc` 写测试数据，兼容未来 pandas Copy-on-Write 行为。

## 验证

- `python3 -m unittest hermes_escape_top.tests.test_integration_config hermes_escape_top.tests.test_reentry_tracker hermes_escape_top.tests.test_risk_engine hermes_escape_top.tests.test_sizing_optimizer`：49 tests OK。
- `python3 -m unittest discover -s hermes_escape_top/tests`：244 tests OK。
- `python3 -m unittest discover -s tests`：11 tests OK。

## 当前结论

远端 P4 快照已经落到本地可运行实现。当前本地 `.hermes` 与 GitHub `building/source_snapshots` 的 P4 代码需要以本日志之后同步回去的版本为准。

下一步建议：

1. Phase II shadow 对照：把 `core/pipeline.py` 接真实 store/scorer，生成 shadow-vs-current 对照报告。
2. P3 软数据补全：PCR / NAAIM / BTC funding-basis-DVOL。
3. Phase III：逐步替换旧 scaler 乘法链，但保持 live 开关关闭，等待人工 dry-run。
