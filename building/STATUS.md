| Phase | 状态 | 分支/PR | 回测达标 | 阻塞 | 更新时间 |
|---|---|---|---|---|---|
| 0 脚手架与契约 | DONE | local only | n/a | - | 2026-05-31 |
| 1 数据层与离线回放 | DONE | local only | n/a | 真实软数据 adapter 尚未接入 | 2026-05-31 |
| 2 指标与特征层 | DONE | local only | n/a | 全部内建 | 2026-06-01 |
| 3 评分核心 A/B/C/D | DONE | local only | n/a | 软数据 blind-spot 属预期 | 2026-06-01 |
| 4 硬阀门 | DONE | local only | n/a | - | 2026-06-01 |
| 5 裁决层 | DONE | local only | n/a | - | 2026-06-01 |
| 6 组合风险预算层 | DONE | local only | NEXT-3 passed | NEXT-3 校准完成；旧 scaler 仍 shadow-only | 2026-06-01 |
| 7 仓位管理 | DONE | local only | NEXT-3 passed | 未接持久化滞回状态 | 2026-06-01 |
| 8 资金路由 | DONE | local only | n/a | 仅 advisory | 2026-06-01 |
| 9 3-3-4 再建仓 | DONE | local only | n/a | T1/T2 未持久化 | 2026-06-01 |
| 10 扩展数据 adapter | IN-PROGRESS | local only | n/a | PCR/NAAIM/BTC funding-basis-DVOL 待接 | 2026-06-01 |
| 11 回测与验证框架 | DONE / M3-COMPLETE | local only | passed | full-proxy + real-only + NEXT-3 校准完成 | 2026-06-01 |
| 12 镜像参考系统 | DONE | local only | n/a | IBKR 未接 | 2026-06-01 |
| 13 元模型 | LOCKED | - | - | 标签解锁门未达 | - |
| 14 WebUI 与可观测性 | PARTIAL | local only | n/a | 未接 IBKR drilldown | 2026-06-01 |
| 15 集成、dry-run、切换 | **IN-PROGRESS / FULL-EXACT-PASSED / REVIEW-GATED** | local only | shadow + WARN sensitivity + full/exact passed | Phase II 252 日 shadow、相关闸敏感性、2113 日 full-window sensitivity 已跑通；P9 已复核 `110/0.90`：CAGR 20.37%、MaxDD -24.32%、R3=0、4 个 exact/fast 抽查通过；live 开关保持关闭 | 2026-06-02 |

## NEXT 工单进度

| NEXT | 状态 | 关键指标 | 阻塞 |
|---|---|---|---|
| NEXT-0 数据地基 | DONE-CODE | 34/38 symbols ≤2018-01-02 | - |
| NEXT-1 软数据 | **IN-PROGRESS / PROXY-CSV-CONNECTED** | MSTR 26→预估~22 / FNGU 19 / SOXL 19；PCR/NAAIM/BTC funding-basis 代理 CSV 已接入 adapter | 真实软数据待手动回填 |
| NEXT-2 回测 | **DONE / P1-COMPLETE** | real-only CAGR 44.39% Sharpe 1.79 DSR 1.66 | - |
| P0 合成历史 | **DONE / STRICT-GATE-PASSED** | FNGU TE 4.67%, corr 0.9986 | - |
| NEXT-3 校准 | **DONE / M3-COMPLETE** | deployment PBO=0.1538；chosen E75_D65_R50 | - |
| NEXT-4 向前软数据 | TODO | - | 可并行 |
| NEXT-5 元模型 | LOCKED | - | 标签未达 |
| NEXT-6 IBKR 对账 | TODO | - | greenfield |
| P4 整合地基 | **DONE / PHASE0-I-PIPELINE-LOCAL-SYNCED** | 270 package tests OK + 11 golden tests OK | live 开关关闭 |
| P5 Phase II Shadow | **DONE / DRY-RUN-PACKAGE-READY** | shadow rows=252；full rows=2113 / errors=0 / scenario count=21 / R3 violations=0 / review candidate 110/0.70：CAGR 18.06%、MaxDD -22.47%、Sharpe 1.0115、fixed OOS below-median 0.3077；4 个 exact spot-check PASS | live 开关保持关闭 |
| P6 Phase III dry-run comparator | **DONE / HUMAN-GATE-READY** | daily comparator rows=252 / errors=0 / R3 violations=0 / PASS=128 / WARN=124 / BLOCK=0 / avg old-new turnover 0.2244→0.2285 | 需人工审阅 WARN 日期；通过后才可设计 scaler migration |
| P7 Phase III WARN review | **DONE / WARN-REVIEW-PACK-DONE** | WARN=124 / EXTREME_CORR=102 / WARN candidate-old avg：1d -0.00%、5d -0.05%、10d -0.29% / readiness=REVIEW_REQUIRED | live 开关保持关闭；需人工决定是否接受机会成本 |
| P8 Phase III WARN sensitivity | **DONE / WARN-SENSITIVITY-DONE** | 24 scenarios / retained-penalty candidate `110/0.90`: WARN 10d -0.13%, max turnover delta 0.2886, R3=0, BLOCK=0 | live 开关保持关闭 |
| P9 Phase III 110/0.90 full/exact | **DONE / FULL-EXACT-PASSED / REVIEW-GATED** | 2113 日 full-window：errors=0、R3=0、CAGR 20.37%、MaxDD -24.32%、Sharpe 1.0171、turnover 338.0594；2020H1/2022H1/2024H1/2026YTD exact/fast 抽查 PASS | 需人工接受约 1.85 pp 回撤放大；live 开关保持关闭 |
| **P10 Migration Acceptance Pack** | **DONE / HUMAN-GATE-PASSED** | 人工于 2026-06-02 确认接受 1.85 pp 回撤放大；110/0.90 候选通过全部门控 | ✅ 人工确认 |
| **P11 Phase III 参数层迁移** | **DONE** | config 已更新 extreme=110/penalty=0.90；新 dry-run PASS=129/WARN=123/BLOCK=0/R3=0；max turnover delta 降至 0.2886；270 tests OK | - |
| **P12 Gate 2 optimizer 替换** | **DONE / GATE-2-COMPLETE** | `pipeline.py` 用 `_optimize_sizing` 替换 `size_portfolio`；`optimize_targets` 唯一处置入口；R3 PASS；`sizing_engine=optimize_targets_v1`；270 tests OK | - |
| **P13 Phase IV Gates 4/5/6** | **DONE / PHASE-IV-GATES-PASSED** | Gate4 置信脊柱 PASS；Gate5 PBO=0.2500 PASS（AUC延后）；Gate6 Factor_Health.md 出炉 32因子 IC，top=C10 avg\|IC\|=0.38；6/7 总闸通过 | Gate7（熔断端到端）TODO |

## P4 整合地基进度

### Phase 0: 输入护栏 ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| E1 数据净化 | `core/data/sanitize.py` | ✅ |
| E30 故障转移 | `core/data/failover.py` | ✅ |

### Phase I: 地基（1 脊柱 + 4 引擎 + 1 优化器 + 治理） ✅ DONE

| 组件 | 文件 | 吸收 | 状态 |
|---|---|---|---|
| 公共契约 | `core/contracts.py` | - | ✅ |
| ConfidenceSpine | `core/confidence/spine.py` | E1/E9/E10/E28/E30 | ✅ |
| RiskEngine | `core/portfolio/risk_engine.py` | E4/E5/E11/E13/E14 | ✅ |
| SizingOptimizer | `core/portfolio/sizing_optimizer.py` | E6/E8/E12/E15/E25/E26/E27 | ✅ |
| FactorLab | `core/factors/lab.py` | E2/E3/E23 | ✅ |
| MarketContext | `core/features/context.py` | E7/E16/E17/E18/E19/E20 | ✅ |
| ValidationHarness | `core/backtest/harness.py` | E21/E22/E23/E24 | ✅ |
| Governance | `core/governance/governance.py` | E10/E28/E29 | ✅ |

### E9 漂移监控 ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| DriftMonitor | `core/monitor/drift.py` | ✅ |

### Pipeline 接线 ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| 统一 Pipeline | `core/pipeline.py` | ✅ |

### E27 税务/洗售感知 ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| Tax/Wash-Sale | `core/portfolio/tax.py` | ✅ |

### Reentry State Tracker ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| 3-3-4 再建仓状态持久化 | `core/reentry/tracker.py` | ✅ |

### Audit Exporter ✅ DONE

| 组件 | 文件 | 状态 |
|---|---|---|
| JSON + Markdown + JSONL 导出 | `core/audit/exporter.py` | ✅ |

**Phase 0–I 完整交付**：15 个组件 + E1–E30 全部 30/30 完整骨架 + 再建仓持久化 + 审计导出。远端 P4 source snapshots 已落地本地 `.hermes`，并修复 integration config 路径、Python 3.9 日期、RiskEngine 数值稳定、SizingOptimizer shrinkage 与 MarketContext 测试警告；当前 270 package tests OK + 11 golden tests OK。

## P5 Phase II Shadow 对照

| 产物 | 状态 |
|---|---|
| `scripts/phase2_shadow_compare.py` | ✅ |
| `reports/PhaseII_Shadow_Compare.md/json` | ✅ |
| `reports/P5_PHASE2_SHADOW_COMPARE_LOG.md` | ✅ |
| `scripts/phase2_corr_sensitivity.py` | ✅ |
| `reports/PhaseII_Corr_Sensitivity.md/json` | ✅ |
| `scripts/phase2_full_backtest_sensitivity.py` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity.md/json` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_Exact_2020H1.md/json` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_Exact_2022H1.md/json` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_Exact_2024H1.md/json` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_Exact_2026YTD.md/json` | ✅ |
| `reports/P5_DRY_RUN_ACCEPTANCE_PACK.md` | ✅ |
| `reports/P5_PHASE2_EXTENDED_DIAGNOSTICS_LOG.md` | ✅ |
| `scripts/phase3_dry_run_compare.py` | ✅ |
| `tests/test_phase3_dry_run_compare.py` | ✅ |
| `reports/PhaseIII_Dry_Run_Comparator.md/json` | ✅ |
| `reports/P6_PHASE3_DRY_RUN_COMPARATOR_LOG.md` | ✅ |
| `scripts/phase3_warn_review.py` | ✅ |
| `tests/test_phase3_warn_review.py` | ✅ |
| `reports/PhaseIII_WARN_Review.md/json` | ✅ |
| `reports/P7_PHASE3_WARN_REVIEW_LOG.md` | ✅ |
| `scripts/phase3_warn_sensitivity.py` | ✅ |
| `tests/test_phase3_warn_sensitivity.py` | ✅ |
| `reports/PhaseIII_WARN_Sensitivity.md/json` | ✅ |
| `reports/P8_PHASE3_WARN_SENSITIVITY_LOG.md` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_P9_110_090.md/json` | ✅ |
| `reports/PhaseII_Full_Backtest_Sensitivity_P9_Exact/Fast_*.md/json` | ✅ |
| `reports/P9_PHASE3_110_090_FULL_EXACT_LOG.md` | ✅ |

| 指标 | 结果 |
|---|---:|
| 回放窗口 | 最近 252 个交易日 |
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
| confidence mode | NORMAL × 252 |
| EXTREME_CORR share | 78.57% |
| avg shadow gross | 0.7229 |
| max abs weight delta | 0.1592 |
| corr sensitivity review candidate | threshold=110 / penalty=0.70 |

## P5 Full Backtest Sensitivity

| 指标 | 结果 |
|---|---:|
| 回放窗口 | 2018-01-02 → 2026-05-29 |
| rows evaluated | 2113 |
| errors | 0 |
| scenario count | 21 |
| R3 violations | 0 |
| review candidate | threshold=110 / penalty=0.70 |
| candidate CAGR | 18.06% |
| candidate MaxDD | -22.47% |
| candidate Sharpe | 1.0115 |
| candidate DSR | 0.8791 |
| candidate fixed OOS below-median | 0.3077 |
| train-greedy PBO | 0.6154 |

## P5 Exact Optimizer Spot-check

| 窗口 | exact/fast 是否一致 | rows | errors | R3 | 备注 |
|---|---|---:|---:|---:|---|
| 2020-01-03 → 2020-07-02 | ✅ | 126 | 0 | 0 | exact 与 fast 浮点级一致 |
| 2022-01-03 → 2022-07-01 | ✅ | 125 | 0 | 0 | exact 与 fast 完全一致 |
| 2024-01-03 → 2024-07-03 | ✅ | 126 | 0 | 0 | exact 与 fast 浮点级一致 |
| 2026-01-05 → 2026-05-29 | ✅ | 101 | 0 | 0 | exact 与 fast 完全一致 |

## P5 Dry-run Acceptance Pack

| Gate | Status |
|---|---|
| P5 candidate ready for shadow dry-run | ✅ |
| Live promotion | BLOCKED |
| R3 invariant | PASS |
| Exact spot-check | PASS |
| Daily old-vs-new dry-run comparator | ✅ DONE |
| Turnover review | WARN review required |

## P6 Phase III Dry-run Comparator

| 指标 | 结果 |
|---|---:|
| 回放窗口 | 最近 252 个交易日 |
| rows evaluated | 252 |
| errors | 0 |
| R3 violations | 0 |
| PASS | 128 |
| WARN | 124 |
| BLOCK | 0 |
| max abs symbol delta | 0.1293 |
| avg max abs symbol delta | 0.0425 |
| max abs route leg delta | 0.2802 |
| avg abs turnover delta | 0.0382 |
| max abs turnover delta | 0.4022 |
| avg old turnover | 0.2244 |
| avg new turnover | 0.2285 |

## P7 Phase III WARN Review

| 指标 | 结果 |
|---|---:|
| WARN rows | 124 |
| WARN share | 49.21% |
| EXTREME_CORR WARN | 102 |
| ROUTE_LEG_DELTA WARN | 50 |
| TURNOVER_DELTA WARN | 28 |
| SYMBOL_DELTA WARN | 20 |
| LOW_GROSS WARN | 16 |
| WARN 1d candidate-old avg | -0.00% |
| WARN 5d candidate-old avg | -0.05% |
| WARN 10d candidate-old avg | -0.29% |
| readiness | REVIEW_REQUIRED |

## P8 Phase III WARN Sensitivity

| 指标 | 当前 110/0.70 | P8 候选 110/0.90 |
|---|---:|---:|
| readiness | REVIEW_REQUIRED | REVIEW_READY |
| R3 violations | 0 | 0 |
| BLOCK | 0 | 0 |
| WARN share | 49.21% | 48.81% |
| EXTREME_CORR share | 40.48% | 40.48% |
| WARN 10d candidate-old avg | -0.29% | -0.13% |
| max turnover delta | 0.4022 | 0.2886 |
| review score | 0.3888 | 0.1340 |

## P9 Phase III 110/0.90 Full-Window + Exact

| 指标 | P5 当前候选 110/0.70 | P9 复核候选 110/0.90 |
|---|---:|---:|
| rows evaluated | 2113 | 2113 |
| errors | 0 | 0 |
| R3 violations | 0 | 0 |
| final value | $401,635.03 | $472,466.65 |
| CAGR | 18.06% | 20.37% |
| max drawdown | -22.47% | -24.32% |
| Sharpe | 1.0115 | 1.0171 |
| Sortino | 1.3141 | 1.3033 |
| turnover | 339.9802 | 338.0594 |
| max abs weight delta | 0.1698 | 0.1675 |

| exact/fast 抽查窗口 | rows | errors | R3 | 结论 |
|---|---:|---:|---:|---|
| 2020H1 | 126 | 0 | 0 | PASS，浮点级差异 |
| 2022H1 | 125 | 0 | 0 | PASS，完全一致 |
| 2024H1 | 126 | 0 | 0 | PASS，final value 差约 $0.06 |
| 2026YTD | 101 | 0 | 0 | PASS，完全一致 |

## 系统级 7 道总闸

| # | 总闸 | 骨架 | Pipeline 结构验证 |
|---|---|---|---|
| 1 | 单一风险源 | ✅ | ✅ test_gate1 |
| 2 | 单一处置入口 | ✅ | ✅ test_gate2 |
| 3 | R3 100% | ✅ | ✅ test_gate3 + test_r3_invariant；P5 shadow R3 violations=0 |
| 4 | 置信脊柱贯通 | ✅ | ✅ test_gate4 + test_confidence_propagates；P5 shadow NORMAL×252 |
| 5 | PBO<0.5+CI+对抗 | ✅ | ✅ test_gate5 (structural) |
| 6 | 因子健康 | ✅ | ✅ test_gate6 (structural) |
| 7 | 可解释可治理 | ✅ | ✅ test_gate7 + audit completeness |

## 下一步

1. ~~Phase 0 输入护栏~~ ✅
2. ~~Phase I 地基~~ ✅
3. ~~Pipeline 接线~~ ✅
4. ~~Phase II 20 日 shadow 对照~~ ✅
5. ~~Phase II 252 日扩窗 + 相关闸敏感性~~ ✅
6. ~~相关闸 full backtest 校准~~ ✅
7. **Phase III 统一处置**：daily old-vs-new comparator、WARN review、WARN sensitivity、`110/0.90` full-window + exact 复核已完成；下一步生成 updated migration acceptance pack。
8. **Phase IV 验证与治理**：实跑 PBO/CI/对抗验证。
9. **补 NEXT-1 剩余软数据**：PCR/NAAIM/BTC funding-basis-DVOL。
