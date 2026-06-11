# Flag Gate — Walk-Forward OOS / PBO

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | PBO (OOS) | DSR | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 17.38% | -13.77% | 1.223 | 1.262 | 1.044 |  | 0.23 | 1.197 | — |
| cot_nq | 15.42% | -13.77% | 1.144 | 1.120 | 1.004 | -0.039 | 0.46 | 1.118 | ❌ FAIL (OOS≤base) |
