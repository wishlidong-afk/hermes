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
| 15 集成、dry-run、切换 | **IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE** | local only | shadow + full sensitivity passed | Phase II 252 日 shadow、相关闸敏感性、2113 日 full-window sensitivity 已跑通；live 开关保持关闭 | 2026-06-01 |

## NEXT 工单进度

| NEXT | 状态 | 关键指标 | 阻塞 |
|---|---|---|---|
| NEXT-0 数据地基 | DONE-CODE | 34/38 symbols ≤2018-01-02 | - |
| NEXT-1 软数据 | IN-PROGRESS / 盲区门已过 | MSTR 26 / FNGU 19 / SOXL 19 | PCR/NAAIM/BTC 待接 |
| NEXT-2 回测 | **DONE / P1-COMPLETE** | real-only CAGR 44.39% Sharpe 1.79 DSR 1.66 | - |
| P0 合成历史 | **DONE / STRICT-GATE-PASSED** | FNGU TE 4.67%, corr 0.9986 | - |
| NEXT-3 校准 | **DONE / M3-COMPLETE** | deployment PBO=0.1538；chosen E75_D65_R50 | - |
| NEXT-4 向前软数据 | TODO | - | 可并行 |
| NEXT-5 元模型 | LOCKED | - | 标签未达 |
| NEXT-6 IBKR 对账 | TODO | - | greenfield |
| P4 整合地基 | **DONE / PHASE0-I-PIPELINE-LOCAL-SYNCED** | 253 package tests OK + 11 golden tests OK | live 开关关闭 |
| P5 Phase II Shadow | **IN-PROGRESS / FULL-BACKTEST-SENSITIVITY-DONE** | shadow rows=252；full rows=2113 / errors=0 / scenario count=21 / R3 violations=0 / review candidate 110/0.70：CAGR 18.06%、MaxDD -22.47%、Sharpe 1.0115、fixed OOS below-median 0.3077 | 需 exact optimizer 抽样复核 + dry-run，人审后再进 Phase III |

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

**Phase 0–I 完整交付**：15 个组件 + E1–E30 全部 30/30 完整骨架 + 再建仓持久化 + 审计导出。远端 P4 source snapshots 已落地本地 `.hermes`，并修复 integration config 路径、Python 3.9 日期、RiskEngine 数值稳定、SizingOptimizer shrinkage 与 MarketContext 测试警告。

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
| Daily old-vs-new dry-run comparator | TODO |
| Turnover review | TODO |

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
7. **Phase III 统一处置**：先做 daily old-vs-new dry-run comparator，再替换旧 scaler 乘法链。
8. **Phase IV 验证与治理**：实跑 PBO/CI/对抗验证。
9. **补 NEXT-1 剩余软数据**：PCR/NAAIM/BTC funding-basis-DVOL。
