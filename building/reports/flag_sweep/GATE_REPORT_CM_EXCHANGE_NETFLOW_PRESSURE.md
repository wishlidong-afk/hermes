# Legacy Flag-Gate Diagnostic (Historical; Authorization Frozen)

> **STALE RESEARCH EVIDENCE:** This report predates the formal IS-selection/OOS-PBO gate. The former `PBO (OOS)` values are fixed-variant OOS bottom-half rates, not formal PBO, and cannot authorize a new flag flip.

Folds: 13 · baseline = `baseline`

| variant | full CAGR | full MaxDD | Sharpe | Calmar | median OOS obj | Δ vs base | OOS bottom-half rate (diagnostic) | DSR (diagnostic) | historical result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baseline | 17.38% | -13.77% | 1.223 | 1.262 | 1.044 |  | 0.08 | 1.197 | — |
| CM_EXCHANGE_NETFLOW_PRESSURE | 17.36% | -13.77% | 1.222 | 1.261 | 1.044 | +0.000 | 0.08 | 1.196 | ❌ FAIL (OOS≤base) |
