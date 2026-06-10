# Feature Flag Registry

All flags live in `config.json → features`. Default = **OFF** (`false`) unless marked ✅ below.

A flag must pass the 13-fold walk-forward + PBO gate before being turned ON in production.
Rollback = set the flag back to `false` (byte-identical behavior restored).

---

## Data flags — controls which soft inputs are collected

| Flag | Default | Status | What it gates |
|------|---------|--------|---------------|
| `data_gex` | OFF | stub | GEX (Gamma Exposure) — data source not implemented |
| `data_skew_vvix` | **ON** ✅ | live | CBOE SKEW + VVIX term-structure inputs (A7) |
| `data_net_liquidity` | **ON** ✅ | live | FRED net-liquidity (WALCL − WTREGEN − RRP) |
| `data_aaii` | **ON** ✅ | best-effort | AAII bull/bear sentiment (A2) |
| `data_naaim` | **ON** ✅ | live | NAAIM Exposure Index (A2) |
| `data_cnn_fgi` | OFF | unmaintained | CNN Fear & Greed — endpoint historically unstable |
| `data_component_breadth` | **ON** ✅ | live | NDX/SOX breadth from FNGU/SOXL component proxies (A3) |
| `data_cboe_pcr` | **ON** ✅ | live | CBOE equity put/call ratio (A2) |
| `data_hy_oas` | OFF | calibrated-off | HY OAS spread percentile (A9) — gate-failed standalone |
| `data_real_rate` | **ON** ✅ | live | FRED DFII10 real rate percentile (A10) — gate-passed 2026-06-08 |
| `data_dollar` | **ON** ✅ | live | FRED DTWEXBGS broad dollar percentile (A11) — gate-passed 2026-06-08 |
| `data_yield_curve` | OFF | calibrated-off | FRED T10Y3M yield curve (A12) — gate-failed standalone |
| `data_credit_etf` | OFF | calibrated-off | HYG/IEF ratio (A13) — gate-failed standalone |
| `data_concentration` | OFF | calibrated-off | RSP/SPY equal-vs-cap weight (A14) — gate-failed standalone |
| `data_defensive_rotation` | **ON** ✅ | live | XLP+XLU+XLV / XLY+XLI+XLF rotation (A15) — gate-passed 2026-06-08 |
| `data_financial_stress` | OFF | calibrated-off | XLF/SPY financial-stress ratio (A16) — gate-failed standalone |
| `data_nfci` | OFF | pending-gate | FRED NFCI financial-conditions index (A17) |
| `data_move` | OFF | pending-gate | MOVE bond-vol index from local OHLCV (A18) |
| `data_ndx_concentration` | OFF | pending-gate | QQQE/QQQ NDX equal-vs-cap concentration (A19) |
| `data_cot_nq` | OFF | pending-gate | CFTC COT NQ futures combined net-long/OI percentile (A20) — backfill via `scripts/backfill_cot.py` |

---

## Model/algorithm flags

| Flag | Default | Status | What it gates |
|------|---------|--------|---------------|
| `use_meta_label` | OFF | unimplemented | Meta-label filtering layer — not implemented |
| `use_portfolio_risk_budget` | OFF | pending-gate | Vol-target risk-budget overlay on sizing |
| `use_regime_multipliers` | **ON** ✅ | live | Apply CRISIS/HIGH_VOL/LOW_VOL_TREND module-weight multipliers in scorer.py — default-ON because the logic was unconditional before this flag was added |
| `use_arm_then_fire` | OFF | pending-gate | Macro leading signals lower trigger thresholds |
| `use_decision_stabilizer` | OFF | gate-failed | Score smoothing across days — **FAILED 2026-06-09: median OOS below baseline, +1.18pp MaxDD** |
| `use_status_hysteresis` | OFF | gate-failed | Hysteresis band on status transitions — **FAILED 2026-06-09** |
| `use_close_confirmation` | OFF | gate-failed | Require close confirmation before status escalation — **FAILED 2026-06-09** |
| `use_suspect_valve_guard` | **ON** ✅ | live | Ignore hard valves on zero-volume/suspect bars (F3) — gate-passed 2026-06-09 |
| `use_scored_missing_weight` | **ON** ✅ | live | Proportional score adjustment for missing fields (F5/F6) — gate-passed 2026-06-09 |
| `use_partial_factor_eval` | **ON** ✅ | live | Score modules even when only partial factor data available (F4) — gate-passed 2026-06-09 |
| `use_hm2_buffer` | OFF | pending-gate | Downgrade lone H-M2 (single -15% day) from EXIT to DEFENSIVE_EXIT |

---

## Dead flags — removed 2026-06-10

These flags had zero code references and were removed from config.json:

| Flag | Why removed |
|------|-------------|
| `data_btc_micro` | No implementation; BTC micro-structure source was never built |
| `use_garch` | GARCH vol forecast replaced by EWMA; no code path references this |
| `use_rolling_quantile` | Rolling-quantile normalization removed; fixed window is the only path |
| `use_regime_weights` | **MISLEADING**: regime multipliers are ALWAYS active in `scorer.py` (lines ~140–160) regardless of this flag. The flag was inert. See `_module_caps_note` in config.json. To actually disable regime multipliers, clear `regime.multipliers`. |
| `routing_v2` | Routing v2 logic was merged into main; flag was inert |

---

## Regime multipliers (gated, default ON)

The regime multiplier logic in `scorer.py` was unconditional until 2026-06-10
(the old `use_regime_weights` flag was inert). It is now gated by
`use_regime_multipliers` (default **ON** = unchanged behaviour). Current values:

| Regime | A | B | C |
|--------|---|---|---|
| CRISIS | ×1.25 | ×0.8 | ×1.25 |
| HIGH_VOL | ×1.15 | ×0.9 | ×1.15 |
| LOW_VOL_TREND | — | ×1.15 | — |

Set `use_regime_multipliers: false` to disable (flat module weights in all regimes).

---

## B-module capacity note

Nominal B cap = **25 pts**. Currently achievable = **21 pts**:

- B5 social (4 pts): stub — `_score_b5_social()` always returns 0
- B6 valuation (5 pts): unwired — no live mNAV/valuation pipeline

Effective B cap = **16 pts** until B5/B6 are wired. The `_module_caps_note` in
config.json also records this.

---

*Last updated: 2026-06-10 (improve/free-improvements-2026-06-10)*
