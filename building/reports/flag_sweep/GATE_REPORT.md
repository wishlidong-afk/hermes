# Legacy Flag-Gate Diagnostic (Historical; Authorization Frozen)

> **STALE RESEARCH EVIDENCE:** This report predates the formal IS-selection/OOS-PBO gate. The former `PBO (OOS)` values are fixed-variant OOS bottom-half rates, not formal PBO, and cannot authorize a new flag flip.

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | OOS bottom-half rate (diagnostic) | DSR (diagnostic) | historical result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 16.97% | -13.58% | 1.215 | 1.250 | 1.191 |  | 0.31 | 1.179 | — |
| scored_missing_weight | 15.53% | -14.04% | 1.124 | 1.106 | 0.933 | -0.258 | 0.38 | 1.088 | ❌ FAIL (OOS≤base) |
| hysteresis_only | 15.11% | -13.93% | 1.104 | 1.084 | 0.775 | -0.416 | 0.62 | 1.068 | ❌ FAIL (OOS≤base) (bottom-half rate≥.5) |
| decision_stabilizer | 16.96% | -15.22% | 1.175 | 1.114 | 0.814 | -0.377 | 0.38 | 1.138 | ❌ FAIL (OOS≤base) (MaxDD +1.6pp) |
