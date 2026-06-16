# 资金效率回测结果 + 落地决策

**Date**: 2026-06-09
**回测**: `run_full_backtest` 2018-01→2026, 冻结快照 `/tmp/capeff_snapshot`(避免 live `serve` 重写 CSV 的读写竞态)。每变体独立进程。
**关联**: review/CAPITAL_EFFICIENCY_PLAN_2026_06_08.md(①-⑤ 思路)。

## 结果(快照一致基线)

| 变体 | lever | CAGR | MaxDD | Calmar | Sharpe | Sortino | 判断 |
|---|---|---:|---:|---:|---:|---:|---|
| baseline | 现状 | 15.39% | −14.04% | 1.096 | 1.116 | 1.459 | — |
| cont_frac | ② 平滑卖出悬崖 | 15.33% | −14.04% | 1.092 | 1.118 | 1.462 | 打平/微负 → **不翻** |
| gov_volcaps | ③ 总闸+风险加权上限 | 15.39% | −14.04% | 1.096 | 1.116 | 1.459 | 字面零效果 → **不翻** |
| mstr_btc | ④ MSTR→BTC-USD | **15.69%** | −14.04% | **1.118** | 1.132 | 1.481 | 唯一真赢 → **翻** |
| capeff_all | ②③④ 组合 | 15.63% | −13.96% | 1.119 | 1.134 | 1.484 | ≈ 全是 ④ 贡献 |

## 逐项结论

- **① T3 再建仓闸门 — PARK(不做)**。`run_full` 按分数衰减再入场,从不跑 3-3-4 档位闸门,harness 测不出;且用户实际**按分数一清就满仓买回、不走档位**,所以 T3 闸门对真实行为零影响。诊断 review/T3_REENTRY_GATE_TIMING.md 量化了"若按档位"的天花板(中位 +3.7%),但工作流决定了不适用。代码保留(flag 默认 `market_252d_high`)。
- **② 平滑卖出比例悬崖 — 不翻**。CAGR −0.06pp、Calmar −0.004,打平。69→70 悬崖 8 年里命中不够多;平滑的中段多卖抵消了收益。代码留着无害。
- **③ 总闸 + 风险加权上限 — 不翻**。和 baseline 同到分。总闸 floor 的 `confidence×gross` 在 `use_portfolio_risk_budget=false` 时≈1、永不触发;vol-weighted caps 从未 binding。只有打开组合风险预算才有意义。
- **④ MSTR DEFCON3 路由 QQQ→BTC-USD — 翻(LIVE)**。CAGR +0.30pp、Calmar +0.022、Sharpe +0.016、MaxDD 不变。逻辑:DEFCON3 是常规降档非崩盘,保留加密论点(BTC)比切科技(QQQ)多吃上行。Live 等价物 = IBIT。
- **⑤ 硬阀门诊断**(review/HARD_VALVE_FREQUENCY_MSTR.md):H-M2(单日−15%)是近乎纯 whipsaw(0% 崩盘命中、中位 fwd20 +18%)→ "先 85% 再确认"缓冲候选;H-M4/H-M6 是真尾部保险(最差 −55%/−49%)→ 保留即时 100%。**缓冲实现+回测列为下一步**,本轮未动硬阀门逻辑。

## 本次落地(human-gate 2026-06-09)

翻成 LIVE 默认(repo config):
- `routing.defcon3.MSTR`: `QQQ` → `BTC-USD`(④)
- `features.use_suspect_valve_guard`: `true`(第一梯队 F3;flag_sweep Calmar 1.10→1.16、MaxDD −14.0→−13.3)
- `features.use_scored_missing_weight`: `true`(第一梯队 F5/F6;+0.1pp、中性偏正)

保持关:② `sell_fraction_mode`、③ `vol_gross_floor`/`vol_weighted_caps`、f8(naaim/pcr 收紧,回测有害)、① `t3_gate_mode`。

回滚:三项改回 `QQQ`/`false`/`false`。
全套测试 384 green(2 个断言旧默认的测试已显式 pin flag)。

> ⚠️ 部署到每日实盘还需把这 3 项同样翻到 `.hermes` 那份 config(repo↔.hermes 同步,用户管)。
