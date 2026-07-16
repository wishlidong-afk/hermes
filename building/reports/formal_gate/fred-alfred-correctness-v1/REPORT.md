# Formal Gate: fred-alfred-correctness-v1

- Hypothesis: Replacing observation-date-plus-one FRED approximations with the same series' authoritative ALFRED realtime_start event history removes known point-in-time leakage. This correctness migration records all performance deterioration and preserves the genuinely unavailable pre-2019 Dollar interval as missing; positive alpha is not an authorization criterion.
- Governance lane: `data_correctness_migration`
- Manifest SHA256: `b3f6b5411cf4a5056abf4f2a70ad2a0d105c4b3bedfcc89f4c6abb6657b5f307`
- Candidate universe: `baseline, fred_vintage_pit`
- Declared trials: 2
- Verdict: **MIGRATION_IMPACT_RECORDED**
- Authorization: **NO_FLIP**

| Check | Result |
|---|---|
| walk_forward_pbo | PASS |
| cpcv_pbo | PASS |
| walk_forward_oos_delta | PASS |
| cpcv_oos_delta | FAIL |
| max_drawdown | FAIL |
| deflated_sharpe | PASS |

| Validation | PBO | Target OOS delta | Folds |
|---|---:|---:|---:|
| Walk-forward | 0.4615 | +0.033584 | 13 |
| CPCV | 0.1333 | -0.146057 | 15 |

Target DSR: `0.948214` using n_trials=2, skew=-0.361694, kurtosis=6.623552.

This records performance impact only. A data-correctness migration remains NO_FLIP until its correctness evidence and baseline restatement receive explicit human approval.
