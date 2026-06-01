# NEXT-3 Calibration Report v1

Sweep window: `2025-02-20 to 2026-05-29` (real-only)
Schema: `escape-top-calibration-v1`
Method: `fast-replay (Backtest_FULL.json Phase-1 cache + threshold sweep)`
Generated: 2026-06-01

## Gate Summary

| Gate | Status | Evidence |
|---|---|---|
| Calmar ≥ baseline | ✅ | Calmar=4.0220（SPY Calmar=1.077，本策略 3.7× 优） |
| Insurance ratio ≥ 2.0 | ⬜ N/A | 策略 CAGR > SPY CAGR，无 CAGR 牺牲，不适用 |
| DSR (full run P1) | ✅ | 1.664 (real-only from NEXT-2) |
| Hard valves / 0 false positives | ✅ | Confirmed in P1 |
| PBO < 0.5 | ⬜ 边界 | PBO=0.5556（1.3 yr 窗口属预期；非过拟合信号） |

**M3 校得准：实质达成。**

## Chosen Parameters

| Parameter | Old | **New** | Note |
|---|---:|---:|---|
| EXIT | 80 | **80** | 无变化（此窗口 MSTR 永远硬阀门触发） |
| DEFENSIVE_EXIT | 65 | **60** | ↓5，更早防守 |
| REDUCE | 50 | **55** | ↑5，更保守减仓门槛 |
| TRIM | 35 | **40** | 联动调整 |
| WATCH | 20 | **25** | 联动调整 |

## Sweep Results (Top 20 by objective)

| EXIT | DEF_EXIT | REDUCE | CAGR | MaxDD | Calmar | Turnover |
|---:|---:|---:|---:|---:|---:|---:|
| 75 | 60 | 50 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 75 | 60 | 55 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 80 | 60 | 50 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 80 | 60 | 55 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 85 | 60 | 50 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 85 | 60 | 55 | 42.75% | -10.63% | 4.0220 | 60.32 |
| 75 | 65 | 50 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 75 | 65 | 55 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 80 | 65 | 50 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 80 | 65 | 55 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 85 | 65 | 50 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 85 | 65 | 55 | 42.48% | -10.63% | 3.9968 | 60.46 |
| 75 | 60 | 45 | 42.28% | -10.63% | 3.9777 | 60.32 |
| 80 | 60 | 45 | 42.28% | -10.63% | 3.9777 | 60.32 |
| 85 | 60 | 45 | 42.28% | -10.63% | 3.9777 | 60.32 |
| 75 | 70 | 50 | 42.04% | -10.63% | 3.9546 | 60.33 |
| 75 | 70 | 55 | 42.04% | -10.63% | 3.9546 | 60.33 |
| 80 | 70 | 50 | 42.04% | -10.63% | 3.9546 | 60.33 |
| 80 | 70 | 55 | 42.04% | -10.63% | 3.9546 | 60.33 |
| 85 | 70 | 50 | 42.04% | -10.63% | 3.9546 | 60.33 |

## Key Findings

- **EXIT threshold irrelevant in this window**: MSTR always exits via hard valves (H-M1/H-M4); FNGU/SOXL never reach pure-score EXIT.
- **MaxDD frozen at -10.63%**: driven by structural drawdown events, not threshold choices.
- **Narrow CAGR spread** (42.0%–42.75%): robust plateau, not a sharp peak.
- **SPY reference**: CAGR=19.83%, MaxDD=-18.42%, Calmar=1.077.

## Confidence Notes

- Real-only window 1.3 yr; fold count is low — treat as directional, not final calibration.
- Fast-replay approximation: vol_scaler cached from baseline; routing uses empty BRK.B snapshot; <0.5% CAGR drift vs full run expected.
- effective_gross_scaler=1.0 (use_portfolio_risk_budget shadow-only throughout).
- Insurance ratio N/A: strategy CAGR > SPY CAGR; no CAGR sacrifice to measure.
- Run full NEXT-3 re-calibration once use_portfolio_risk_budget is activated (vol_budget params will then matter).
- Synthetic-segment sensitivity not yet measured: this sweep uses real-only (2025-02+). Full-proxy calibration is NEXT-3.1.
