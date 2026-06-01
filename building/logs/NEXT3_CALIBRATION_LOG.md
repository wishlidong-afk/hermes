# NEXT-3 参数校准执行日志

更新时间：2026-06-01

## 目标

按 GitHub `docs/CODEX_GUIDANCE.md` 和本地/远端 `building/STATUS.md` 的最新账本，启动 NEXT-3 参数扫描与正式校准：

- 使用 `Backtest_FULL_2018_2026.json` 作为 full-proxy walk-forward 主样本。
- 使用 `Backtest_FULL.json` 作为 2025-02-20 以来 real-only 敏感性样本。
- 不追单点最优峰值，改用稳定高原参数。
- 披露合成段敏感性与过拟合诊断。

## 已完成实现

1. 新增 `scripts/calibrate_next3_v2.py`。
   - 27 组阈值组合：`EXIT=(75,80,85)`、`DEFENSIVE_EXIT=(60,65,70)`、`REDUCE=(45,50,55)`。
   - 全窗口只模拟每个组合一次，再按 walk-forward fold 切片计算训练/测试目标，避免重复重跑。
   - 保留 train-greedy PBO 作为过拟合诊断。
   - 新增 fixed highland selector：优先选择 OOS below-median 频率最低、mean/median rank 更高、阈值更保守的固定高原组合。

2. 新增 `tests/test_next3_calibration.py`。
   - 覆盖 rank percentile、PBO 计算、阈值网格顺序约束、fixed highland 排序。

3. 优化 `core/routing/leg_proxy.py`。
   - 将 `DBMF -> trend_synth` 的趋势代理序列预计算一次，避免回测/校准循环内反复重建。

4. 修复 golden parity 测试的浮点容差。
   - `tests/golden/test_v25_parity.py` 改为递归近似比较数值字段，并对说明字符串里的浮点尾差做归一化。
   - 重新生成 `tests/golden/fixtures/v25_score_projection_golden.json`，使 golden 基准匹配 P0 合成历史后的当前数据地基。

## 校准结果

候选参数：`E75_D65_R50`

| 参数 | 值 |
|---|---:|
| EXIT | 75 |
| DEFENSIVE_EXIT | 65 |
| REDUCE | 50 |
| TRIM | 35 |
| WATCH | 20 |

| 验收门 | 结果 | 证据 |
|---|---|---|
| NEXT-3 deployment gate | PASS | fixed highland + drawdown + real-only sensitivity |
| Deployment fixed PBO < 0.5 | PASS | PBO=0.1538，13 folds |
| Train-greedy PBO < 0.5 diagnostic | NOT PASSED | PBO=0.6154，说明逐窗口贪心优化过拟合风险高 |
| Full-proxy MaxDD <= 30% | PASS | MaxDD=-28.01% |
| Real-only MaxDD <= 15% | PASS | MaxDD=-10.63% |
| Real-only sensitivity rank >= 0.5 | PASS | Rank=0.7692 |

## 窗口表现

| 窗口 | CAGR | MaxDD | Calmar | Sharpe | Turnover |
|---|---:|---:|---:|---:|---:|
| Full-proxy 2018-2026 | 17.54% | -28.01% | 0.6260 | 0.8595 | 305.7306 |
| Real-only 2025-2026 | 42.48% | -10.63% | 3.9968 | 1.7273 | 60.4567 |

## 验证

- `python3 -m unittest hermes_escape_top.tests.test_next3_calibration hermes_escape_top.tests.test_next0_data_foundation hermes_escape_top.tests.test_phase8_routing`：14 tests OK。
- `python3 -m unittest discover -s tests`：11 tests OK。
- `python3 -m unittest discover -s hermes_escape_top/tests`：90 tests OK。

## 结论

NEXT-3 可以标记为 `DONE / M3-COMPLETE / STABLE-HIGHLAND-PASSED`，但必须保留两条治理约束：

1. 不允许使用 train-greedy 逐窗口最优阈值作为生产规则。
2. `use_portfolio_risk_budget` 等 live/生产开关仍保持关闭；本阶段只产出校准 artifact，不自动切换实盘。

## 产物

- `reports/Calibration_v2.md`
- `config/artifacts/calibration_v2.json`
- `scripts/calibrate_next3_v2.py`
- `tests/test_next3_calibration.py`
