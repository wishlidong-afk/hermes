# Flag Gate — Walk-Forward OOS / PBO

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | median OOS obj | Δ vs base | PBO (OOS) | DSR | gate |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline | 15.39% | -14.04% | 0.872 |  | 0.38 | 1.080 | — |
| scored_missing_weight | 15.53% | -14.04% | 0.933 | +0.062 | 0.31 | 1.088 | ✅ PASS |
| hysteresis_only | 15.11% | -13.93% | 0.775 | -0.097 | 0.54 | 1.068 | ❌ FAIL (OOS≤base) (PBO≥.5) |
| decision_stabilizer | 16.96% | -15.22% | 0.814 | -0.058 | 0.23 | 1.138 | ❌ FAIL (OOS≤base) (MaxDD +1.2pp) |
