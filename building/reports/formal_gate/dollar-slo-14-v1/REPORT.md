# Formal Gate: dollar-slo-14-v1

- Hypothesis: Allowing the calibrated dollar factor to remain available through 14 calendar days of publisher latency improves or preserves next-open OOS defensive performance without worsening drawdown beyond policy tolerance.
- Manifest SHA256: `d1c2564f83a096faad9f4369e5faebe07e68b7a8d6ebee265759ed1af7af7088`
- Candidate universe: `dollar_slo_6, dollar_slo_14`
- Declared trials: 2
- Verdict: **REJECTED**
- Authorization: **NO_FLIP**

| Check | Result |
|---|---|
| walk_forward_pbo | PASS |
| cpcv_pbo | PASS |
| walk_forward_oos_delta | FAIL |
| cpcv_oos_delta | FAIL |
| max_drawdown | PASS |
| deflated_sharpe | PASS |

| Validation | PBO | Target OOS delta | Folds |
|---|---:|---:|---:|
| Walk-forward | 0.0000 | +0.000000 | 14 |
| CPCV | 0.0000 | +0.000000 | 15 |

Target DSR: `0.950058` using n_trials=2, skew=-0.357115, kurtosis=6.805486.

A passing result is still a candidate result. Production remains unchanged until a human flip.
