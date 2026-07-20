# Formal Gate: cd-trend-ownership-v1

- Hypothesis: Assigning broad MA200 and MA220 price-trend damage exclusively to Module C by suppressing the duplicate D1/D2 votes improves both walk-forward and CPCV next-open OOS objectives without worsening MaxDD by more than 1 percentage point.
- Governance lane: `alpha_experiment`
- Manifest SHA256: `5b3ffa9cffaf7d663d56b12605e04e8a395876238657f096153409a352cdc8f1`
- Candidate universe: `cd_trend_baseline, cd_trend_dedup`
- Declared trials: 2
- Verdict: **REJECTED**
- Authorization: **NO_FLIP**

| Check | Result |
|---|---|
| walk_forward_pbo | FAIL |
| cpcv_pbo | FAIL |
| walk_forward_oos_delta | FAIL |
| cpcv_oos_delta | PASS |
| max_drawdown | PASS |
| deflated_sharpe | PASS |

| Validation | PBO | Target OOS delta | Folds |
|---|---:|---:|---:|
| Walk-forward | 0.5714 | -0.049997 | 14 |
| CPCV | 0.8000 | +0.032739 | 15 |

Target DSR: `0.931188` using n_trials=2, skew=-0.403777, kurtosis=7.034831.

A passing result is still a candidate result. Production remains unchanged until a human flip.
