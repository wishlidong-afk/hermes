# Legacy Flag-Gate Diagnostic (Historical; Authorization Frozen)

> **STALE RESEARCH EVIDENCE:** This report predates the formal IS-selection/OOS-PBO gate. The former `PBO (OOS)` values are fixed-variant OOS bottom-half rates, not formal PBO, and cannot authorize a new flag flip.

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | OOS bottom-half rate (diagnostic) | DSR (diagnostic) | historical result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 16.97% | -13.58% | 1.215 | 1.250 | 1.191 |  | 0.31 | 1.189 | — |
| cot_nq | 15.42% | -13.77% | 1.144 | 1.120 | 1.004 | -0.187 | 0.69 | 1.118 | ❌ FAIL (OOS≤base) (bottom-half rate≥.5) |
