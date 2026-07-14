# Formal Gate: fred-vintage-pit-v1

- Hypothesis: Replacing revised-current FRED history with exact ALFRED realtime_start vintages removes look-ahead leakage while preserving or improving next-open out-of-sample defensive performance without worsening maximum drawdown beyond policy tolerance.
- Manifest SHA256: `b21a3506be8f66307568a45ff1980ee2cbbc26671bbb3727f7924f653a9ae58b`
- Candidate universe: `baseline, fred_vintage_pit`
- Declared trials: 2
- Verdict: **REJECTED**
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
| Walk-forward | 0.4286 | +0.165206 | 14 |
| CPCV | 0.0667 | -0.077120 | 15 |

Target DSR: `0.835557` using n_trials=2, skew=-0.473161, kurtosis=6.991216.

A passing result is still a candidate result. Production remains unchanged until a human flip.
