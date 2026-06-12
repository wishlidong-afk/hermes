# Feature Flag Registry

All flags live in `config.json → features`. Default = **OFF** (`false`) unless marked ✅ below.

A flag must pass the 13-fold walk-forward + PBO gate before being turned ON in production.
Rollback = set the flag back to `false` (byte-identical behavior restored).

This registry is also the experiment ledger. Every experiment should end in one
of four states:

| State | Meaning | Required evidence |
|------|---------|-------------------|
| Candidate | Worth researching; no live behavior change | hypothesis + affected surface + planned validation |
| Shadow | Wired but not consumed by live decisions | byte-identical OFF proof + payload/report evidence |
| Live | Human-approved and enabled | gate/report link + rollback path |
| Rejected | Failed, neutral-with-no-edge, or superseded | reason + source report so it is not retried casually |

---

## Data flags — controls which soft inputs are collected

| Flag | Default | Status | What it gates |
|------|---------|--------|---------------|
| `data_gex` | OFF | stub | GEX (Gamma Exposure) — data source not implemented |
| `data_skew_vvix` | **ON** ✅ | live | CBOE SKEW + VVIX term-structure inputs (A7) |
| `data_net_liquidity` | **ON** ✅ | live | FRED net-liquidity (WALCL − WTREGEN − RRP) |
| `data_aaii` | **ON** ✅ | best-effort | AAII bull/bear sentiment (A2) |
| `data_naaim` | **ON** ✅ | live | NAAIM Exposure Index (A2) |
| `data_cnn_fgi` | OFF | rejected-for-performance | CNN Fear & Greed — wired/full coverage, but system marginal effect is noise |
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
| `data_move` | OFF | rejected-additive | MOVE bond-vol index from local OHLCV (A18) — useful standalone, negative marginal value in saturated A module |
| `data_ndx_concentration` | OFF | rejected-additive | QQQE/QQQ NDX equal-vs-cap concentration (A19) — failed as part of batch-2 additive experiment |
| `data_cot_nq` | OFF | gate-failed | CFTC COT NQ futures combined net-long/OI percentile (A20) — pipeline retained, flag stays OFF |
| `data_onchain_mstr` | OFF | gate-failed | CoinMetrics on-chain MSTR lab feed; T19 inflow/netflow pressure candidates failed gate and stay OFF |
| `data_mstr_mnav` | OFF | candidate | MSTR mNAV data source from manual BTC holdings CSV + local market data; source registers only when ON |

---

## Model/algorithm flags

| Flag | Default | Status | What it gates |
|------|---------|--------|---------------|
| `use_meta_label` | OFF | unimplemented | Meta-label filtering layer — not implemented |
| `use_portfolio_risk_budget` | OFF | pending-gate | Vol-target risk-budget overlay on sizing |
| `use_regime_multipliers` | **ON** ✅ | live | Apply CRISIS/HIGH_VOL/LOW_VOL_TREND module-weight multipliers in scorer.py — default-ON because the logic was unconditional before this flag was added |
| `use_arm_then_fire` | OFF | shadow-redesign-needed | Macro leading signals lower trigger thresholds; current design double-counts scored inputs |
| `use_decision_stabilizer` | OFF | gate-failed | Score smoothing across days — **FAILED 2026-06-09: median OOS below baseline, +1.18pp MaxDD** |
| `use_status_hysteresis` | OFF | gate-failed | Hysteresis band on status transitions — **FAILED 2026-06-09** |
| `use_close_confirmation` | OFF | gate-failed | Require close confirmation before status escalation — **FAILED 2026-06-09** |
| `use_suspect_valve_guard` | **ON** ✅ | live | Ignore hard valves on zero-volume/suspect bars (F3) — gate-passed 2026-06-09 |
| `use_scored_missing_weight` | **ON** ✅ | live | Proportional score adjustment for missing fields (F5/F6) — gate-passed 2026-06-09 |
| `use_partial_factor_eval` | **ON** ✅ | live | Score modules even when only partial factor data available (F4) — gate-passed 2026-06-09 |
| `use_hm2_buffer` | OFF | gate-failed | Downgrade lone H-M2 (single -15% day) from EXIT to DEFENSIVE_EXIT — real path rejected |
| `use_soft_data_max_age` | OFF | candidate | Treat over-age soft records as missing; `slo_only` no-op confirmed vs baseline: 17.3785% CAGR / -13.7734% MaxDD / Sharpe 1.222571 (`building/reports/flag_sweep/slo_only.json`, `slo_only_equity.json`) |
| `use_full_confidence_spine` | OFF | candidate | Wire fragility/disagreement into confidence spine; footprint: `spine_only` = `slo_spine` at 16.9649% CAGR / -13.5822% MaxDD / Sharpe 1.213529, vs baseline ΔCAGR -0.4136pp, MaxDD +0.1912pp, Sharpe -0.0090 |
| `use_b6_mnav_valuation` | OFF | candidate | Consume `SOFT.MSTR_valuation_pctl` as B6 mNAV valuation heat; requires full in-system gate because MSTR B normalization changes |

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

## Experiment ledger

### Live / accepted

| Experiment | State | Impact surface | Evidence | Rollback |
|---|---|---|---|---|
| A10 real rate + A11 dollar + A15 defensive rotation | Live | Data, A module scoring, thresholds | `docs/RISK_FACTORS_CALIBRATION_2026_06_08.md`; deployment fixed PBO 0.153846 | Set `data_real_rate`, `data_dollar`, `data_defensive_rotation` false and restore prior thresholds |
| F3 suspect valve guard | Live | Data quality, hard valves | `building/reports/flag_sweep/GATE_REPORT.md`; risk reduction and live robustness | `features.use_suspect_valve_guard=false` |
| F5/F6 scored missing weight | Live | Missing-data scoring semantics | `building/reports/flag_sweep/GATE_REPORT.md`; median OOS objective +0.062, PBO 0.31 | `features.use_scored_missing_weight=false` |
| F4 partial factor eval | Live | Live robustness under partial data | `building/reports/flag_sweep/SWEEP_SUMMARY.md`; no-op on clean history, robustness win | `features.use_partial_factor_eval=false` |
| Regime multipliers | Live | Scoring module weights | `features.use_regime_multipliers=true`; default ON matches the unconditional pre-2026-06-10 behavior | `features.use_regime_multipliers=false` |
| Routing combo: MSTR→BTC-USD + DEFCON1 GLD leg | Live | Routing | `src/hermes_escape_top/config/config.json` `_defcon3_note`; combo gate PBO 0.31, OOS Δ+0.117, CAGR +1.90pp vs baseline; DEFCON1 GLD standalone +1.59pp | `routing.defcon3.MSTR="QQQ"`; restore DEFCON1 BOXX70/TREND30 and remove `extra_legs.GLD` |
| Deployment baseline freeze | Live reference | Docs, validation provenance | `docs/BASELINE_2026_06_11.md` | Regenerate from reports if source artifacts change |

### Rejected / parked

| Experiment | State | Why it failed or parked | Evidence | Retry rule |
|---|---|---|---|---|
| `use_decision_stabilizer` | Rejected | Median OOS objective below baseline; full stabilizer worsened MaxDD by +1.18pp despite higher in-sample CAGR | `building/reports/flag_sweep/GATE_REPORT.md`; `building/reports/flag_sweep/SWEEP_SUMMARY.md` | Do not revive without a new mechanism and new prior |
| `use_status_hysteresis` / hysteresis-only | Rejected | OOS objective below baseline and PBO >= 0.5 | `building/reports/flag_sweep/GATE_REPORT.md` | Do not re-test as a smoothing-only patch |
| `use_close_confirmation` | Rejected | Same confirmation-delay family as stabilizer; worsens tail-exit behavior | `building/reports/flag_sweep/GATE_REPORT.md`; config `_flag_review_calibration` | Only revisit inside a clean, leading-data-only arming design |
| NAAIM/PCR tightening (`f8_tightened`) | Rejected | Worse on every full-system metric; standalone forward edge did not survive in-system | `building/reports/flag_sweep/SWEEP_SUMMARY.md` | Do not retune A2 thresholds in the saturated A module |
| H-M2 buffer (`use_hm2_buffer`) | Rejected | Lone H-M2 cases typically confirmed next day; delaying full exit lost about 0.30pp CAGR | `review/HM2_BUFFER_RESULTS.md` | Keep code flag-gated OFF; no second parameter search |
| COT NQ (`data_cot_nq`) | Rejected | Pipeline works, but gate failed: OOS objective below baseline, full CAGR lower | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` | Keep data pipeline for future research; flag remains OFF |
| MOVE + A19 + NAAIM batch-2 | Rejected | Added negative marginal value on top of A10/A11/A15; A module is cap-saturated | `docs/FACTOR_EXPLORATION_RESULTS_2026_06_08.md` | Do not add more A-module points without decoupling the cap/design |
| CNN Fear & Greed (`data_cnn_fgi`) | Rejected for performance | Full coverage and correctly wired, but effect is within noise: CAGR -0.03pp, MaxDD flat | `building/reports/flag_sweep/CNN_RESULT.md` | May be kept as a non-decision data feed, not a performance flag |
| Continuous sell fraction | Rejected for performance, accepted operationally | Gate was essentially neutral-to-slightly-worse; operational cliff-removal was human-approved separately | `building/reports/flag_sweep/GATE_REPORT_continuous_sell_fraction.md`; config `_sell_fraction_mode_note` | Do not sell as alpha; evaluate only as operator-experience logic |
| On-chain MSTR exchange inflow pressure (`data_onchain_mstr`, `CM_EXCHANGE_INFLOW_PRESSURE`) | Rejected | T19 gate failed: full CAGR 17.38%, MaxDD -13.77%, Sharpe 1.223; median OOS objective tied baseline but did not strictly improve (Δ +0.000), PBO 0.00, DSR 1.197 | `building/reports/flag_sweep/GATE_REPORT_CM_EXCHANGE_INFLOW_PRESSURE.md`; `building/reports/flag_sweep/CM_EXCHANGE_INFLOW_PRESSURE.json` | Do not retune this signal; new on-chain work needs a new prior and a fresh one-shot gate |
| On-chain MSTR exchange netflow pressure (`data_onchain_mstr`, `CM_EXCHANGE_NETFLOW_PRESSURE`) | Rejected | T19 gate failed: full CAGR 17.36%, MaxDD -13.77%, Sharpe 1.222; median OOS objective tied baseline but did not strictly improve (Δ +0.000), PBO 0.08, DSR 1.196 | `building/reports/flag_sweep/GATE_REPORT_CM_EXCHANGE_NETFLOW_PRESSURE.md`; `building/reports/flag_sweep/CM_EXCHANGE_NETFLOW_PRESSURE.json` | Do not retune this signal; new on-chain work needs a new prior and a fresh one-shot gate |
| Arm-then-fire current design | Parked | Current arming inputs overlap additive scored factors, creating double-counting | `docs/FACTOR_EXPLORATION_RESULTS_2026_06_08.md` | Redesign as leading-data-only before one final gate |

### Candidate / next research

| Experiment | State | Hypothesis | Required validation |
|---|---|---|---|
| `use_soft_data_max_age` | Candidate | Stale soft data should behave like missing data rather than fresh evidence | `building/reports/flag_sweep/slo_only.json` + `slo_only_equity.json`: no-op confirmed against `baseline.json` (same 17.3785% CAGR / -13.7734% MaxDD / Sharpe 1.222571; same manifest `0bd99464...`; commit `9953cea...`); next: live staleness simulation + health/UI evidence |
| `use_full_confidence_spine` | Candidate | Real fragility/disagreement inputs should replace hard-coded zeros | `building/reports/flag_sweep/spine_only.json` and `slo_spine.json`: 16.9649% CAGR / -13.5822% MaxDD / Sharpe 1.213529; footprint vs baseline is ΔCAGR -0.4136pp, MaxDD improves +0.1912pp, Sharpe -0.0090; requires human review before any live flip |
| `data_mstr_mnav` | Candidate | A PIT mNAV source can provide the B6 valuation input without changing production while OFF | `src/hermes_escape_top/core/data/risk_signals.py`; `src/hermes_escape_top/data/soft_history/mstr_btc_holdings.csv`; source parsing tests; OFF source-registration proof; gate precondition: MSTR history must include `market_cap_usd` or `shares_outstanding` |
| `use_b6_mnav_valuation` | Candidate | Direct MSTR valuation/premium data may fill the B6 gap without duplicate D-module scoring | `docs/MNAV_MODULE_OWNERSHIP_DECISION_2026_06_11.md`; byte-identical OFF proof; one full in-system gate of the complete B normalization path |

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

*Last updated: 2026-06-11 (Agent B T19 on-chain gates + T17 mNAV + T9/T10 evidence cards)*
