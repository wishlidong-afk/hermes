# Flag Gate — Walk-Forward OOS / PBO

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | PBO (OOS) | DSR | gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 16.97% | -13.58% | 1.215 | 1.250 | 1.191 |  | 0.31 | 1.189 | — |
| cot_nq | 15.42% | -13.77% | 1.144 | 1.120 | 1.004 | -0.187 | 0.69 | 1.118 | ❌ FAIL (OOS≤base) (PBO≥.5) |
