# Phase 6 Report - Portfolio Risk Budget

Date: 2026-06-01

## Scope

Phase 6 adds the greenfield portfolio risk-budget layer:

- Computes marginal leg volatility from each symbol's own history.
- Computes correlation on the common return window.
- Applies hand-written correlation shrinkage toward identity.
- Excludes hard-valve / 100%-sold legs from gross-risk calculation while still reporting target weights.
- Computes forecast portfolio volatility and `gross_scaler`.
- Keeps `effective_gross_scaler=1` while the risk-budget feature is not enabled, so current output is shadow-only.

## Verification

- High-correlation, high-volatility synthetic sleeves reduce gross exposure.
- No active legs returns neutral scaler.
- Insufficient common history returns UNKNOWN/neutral.
- Correlation shrinkage moves off-diagonal correlations toward identity.
- `score_pipeline(...)` includes a `portfolio_risk` object.

## Remaining Gaps

- Parameter sweep/backtest calibration is not implemented yet.
- sklearn LedoitWolf is not installed in this environment; the greenfield path uses deterministic manual shrinkage.
- Risk-budget output is recorded in payload but not applied to target weights yet.
