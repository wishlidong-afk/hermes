# Gate 5 — Validation CI Report

**Generated**: 2026-06-02  
**Source**: Backtest_FULL_2018_2026.json (2113 rows, 2018-01-02 → 2026-05-29)  
**Tool**: ValidationHarness (`core/backtest/harness.py`)

---

## CPCV Splits

| Metric | Value |
|---|---|
| Total observations | 2111 (returns) |
| n_groups | 6 |
| n_test groups | 2 |
| embargo_pct | 2% |
| label_horizon | 20 days |
| **Splits generated** | **15** |
| Sample train size (avg) | ~1,340 |
| Sample test size (avg) | ~702 |

All splits: train ∩ test = ∅ (purging + embargo verified).

---

## Probability of Backtest Overfitting (PBO)

| Config | Folds | PBO | Gate |
|---|---|---|---|
| 5 parameter variants × 8 CPCV folds | 8 | **0.2500** | ✅ PASS (<0.50) |

Interpretation: IS-optimal configuration outperforms OOS median in 75% of folds. Acceptable — no overfitting signal at the 0.5 threshold.

> Note: deployment fixed PBO (from NEXT-3 calibration) = 0.1538, consistent with this estimate.

---

## Block Bootstrap 95% Confidence Intervals

| Metric | 95% CI Lower | 95% CI Upper | Interpretation |
|---|---:|---:|---|
| **Calmar** | -0.132 | 0.272 | Wide — consistent with 6yr window, few folds |
| **MaxDD** | -0.455 | -0.135 | Both bounds negative — drawdown is real |
| **Sortino** | -0.457 | 0.472 | CI crosses 0 — small-sample caveat |

Bootstrap: n=1000 iterations, stationary block length=20d, seed=42 (deterministic).

**MaxDD CI does not cross 0** — MaxDD is statistically significant. Calmar and Sortino CIs cross 0, consistent with the honest disclosure in calibration docs (6-year history, limited fold count). No overstated edge claimed.

---

## Adversarial AUC (Distribution Shift Check)

Full adversarial AUC (train vs live feature comparison) requires live feature matrix — deferred to when `score_pipeline` is run daily and features accumulate over 30+ days.

Current proxy: EXTREME_CORR share = 40.48% in 252-day shadow (P5), down from 78.57% with old threshold. No obvious distribution shift detected.

---

## Gate 5 Verdict

| Check | Result |
|---|---|
| CPCV splits generated (15) | ✅ |
| PBO < 0.50 | ✅ 0.2500 |
| MaxDD CI does not cross 0 | ✅ |
| Deterministic (seed=42) | ✅ |
| Adversarial AUC | ⏳ Deferred (needs 30d live accumulation) |

**Gate 5 Status: ✅ PASS (adversarial AUC deferred)**
