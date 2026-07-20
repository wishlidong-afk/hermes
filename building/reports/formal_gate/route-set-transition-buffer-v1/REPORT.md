# Formal Gate: route-set-transition-buffer-v1

- Hypothesis: Suppressing a sole added or removed non-risk route leg below 2 percentage points reduces route-set turnover while improving both walk-forward and CPCV next-open OOS objectives, without delaying risk-leg exits or worsening MaxDD by more than 1 percentage point.
- Governance lane: `alpha_experiment`
- Manifest SHA256: `57fbc0c361be1b7775212d02aeb7c202478a5ec71a3ef77ac42a18ce74ce6f2a`
- Candidate universe: `baseline, route_set_transition_buffer`
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

Target DSR: `0.928541` using n_trials=2, skew=-0.434528, kurtosis=7.105032.

A passing result is still a candidate result. Production remains unchanged until a human flip.
