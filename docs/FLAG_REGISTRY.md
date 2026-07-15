# Feature Flag Registry

All flags live in `config.json → features`. Default = **OFF** (`false`) unless marked ✅ below.

A flag must pass the pre-registered formal IS-selection/OOS-PBO gate before being turned ON in production.
Rollback = set the flag back to `false` (byte-identical behavior restored).

> **Research evidence freeze (2026-07-10):** existing `GATE_REPORT*.md` PBO columns are fixed-variant OOS bottom-half rates, not formal PBO. They remain historical diagnostics for past decisions but cannot authorize any new flag or routing change. The replacement formal gate is implemented in `scripts/formal_gate.py`; authorization remains frozen until a pre-registered experiment produces fresh v3 artifacts and a one-shot formal result.
>
> **PIT data-correctness migrations:** authoritative replacements of the same economic datum use the separate, pre-declared policy in [`ADR-001`](adr/ADR-001-pit-data-correctness-migrations.md). This does not reclassify or authorize any existing Rejected experiment, including `fred-vintage-pit-v1`.

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
| `data_mstr_mnav` | OFF | shadow-data | MSTR mNAV data source from manual BTC holdings CSV + local market data; B6 alpha consumption gate failed, source stays OFF/parked |

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
| `use_soft_data_max_age` | **ON** ✅ | live | Treat over-age soft records as missing; `slo_only` no-op and live staleness behavior verified; rollback sets the flag false |
| `use_full_confidence_spine` | **ON** ✅ | live | Wire fragility/disagreement into confidence spine; historical 13-fold evidence passed and the human-approved flag is deployed |
| `use_b6_mnav_valuation` | OFF | gate-failed | Consume `SOFT.MSTR_valuation_pctl` as B6 mNAV valuation heat; failed full in-system gate, stays OFF |
| `use_no_advice_state` | **ON** ✅ | live | Emit an explicit no-advice state when required decision evidence is blocked instead of fabricating a normal recommendation |
| `use_indicator_cache` | OFF | candidate | Cache indicator frames by symbol/history identity; OFF preserves the uncached scoring path |
| `use_market_admission_gate` | **ON (live config; repo default OFF)** ✅ | live | Live since 2026-07-14: require Yahoo + Alpaca SIP consensus before supported U.S. equity/ETF OHLCV rows can replace canonical history; mismatch or missing witness preserves the prior certified row |
| `use_btc_spot_witness` | **ON (live config; repo default OFF)** ✅ | live | Live since 2026-07-14: Coinbase completed UTC-day close gates Yahoo BTC-USD candidates; activation recertification `b1ee0b6f3fb34f73a500661559c78356` admitted 38 MATCH + 2 NOT_APPLICABLE rows with zero rejects |
| `use_cboe_official_indices` | **ON (live config; repo default OFF)** ✅ | live | Live since 2026-07-14: official CBOE VIX/VIX3M/VIX9D/SKEW/VVIX files are the five canonical single writers; Yahoo is witness-only, and mismatched or unconfirmed rows stay frozen. Activation evidence: `building/reports/data_quality/cboe_official_indices_live_activation_2026_07_14.json` |
| `use_fred_vintage_pit` | OFF | gate-failed | Exact ALFRED output-type-3 event storage and as-of replay remain available for research, but the one-shot formal gate rejected replacing the live legacy FRED path. Production stays on the documented `date+1` approximation. |

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
| F5/F6 scored missing weight | Live | Missing-data scoring semantics | `building/reports/flag_sweep/GATE_REPORT.md`; historical median OOS objective +0.062, legacy OOS bottom-half rate 0.31 | `features.use_scored_missing_weight=false` |
| F4 partial factor eval | Live | Live robustness under partial data | `building/reports/flag_sweep/SWEEP_SUMMARY.md`; no-op on clean history, robustness win | `features.use_partial_factor_eval=false` |
| Regime multipliers | Live | Scoring module weights | `features.use_regime_multipliers=true`; default ON matches the unconditional pre-2026-06-10 behavior | `features.use_regime_multipliers=false` |
| Routing combo: MSTR→BTC-USD + DEFCON1 GLD leg | Live | Routing | `src/hermes_escape_top/config/config.json` `_defcon3_note`; historical combo OOS bottom-half rate 0.31, OOS Δ+0.117, CAGR +1.90pp vs baseline; DEFCON1 GLD standalone +1.59pp | `routing.defcon3.MSTR="QQQ"`; restore DEFCON1 BOXX70/TREND30 and remove `extra_legs.GLD` |
| Deployment baseline | Current comparator | Docs, validation provenance | `docs/BASELINE_CURRENT.md`; cache v4 `baseline.json` is `CURRENT_EXECUTION_EVIDENCE` at gate-code commit `360aced`, `equity_timing=next_open`, 15.58% CAGR / -20.83% MaxDD / 1.064 Sharpe | Rebuild after any gate-code/config/history/soft-history provenance change; baseline alone authorizes no flip |

### Rejected / parked

| Experiment | State | Why it failed or parked | Evidence | Retry rule |
|---|---|---|---|---|
| `use_decision_stabilizer` | Rejected | Median OOS objective below baseline; full stabilizer worsened MaxDD by +1.18pp despite higher in-sample CAGR | `building/reports/flag_sweep/GATE_REPORT.md`; `building/reports/flag_sweep/SWEEP_SUMMARY.md` | Do not revive without a new mechanism and new prior |
| `use_status_hysteresis` / hysteresis-only | Rejected | Historical OOS objective below baseline and OOS bottom-half rate >= 0.5 | `building/reports/flag_sweep/GATE_REPORT.md` | Do not re-test as a smoothing-only patch |
| `use_close_confirmation` | Rejected | Same confirmation-delay family as stabilizer; worsens tail-exit behavior | `building/reports/flag_sweep/GATE_REPORT.md`; config `_flag_review_calibration` | Only revisit inside a clean, leading-data-only arming design |
| NAAIM/PCR tightening (`f8_tightened`) | Rejected | Worse on every full-system metric; standalone forward edge did not survive in-system | `building/reports/flag_sweep/SWEEP_SUMMARY.md` | Do not retune A2 thresholds in the saturated A module |
| H-M2 buffer (`use_hm2_buffer`) | Rejected | Lone H-M2 cases typically confirmed next day; delaying full exit lost about 0.30pp CAGR | `review/HM2_BUFFER_RESULTS.md` | Keep code flag-gated OFF; no second parameter search |
| COT NQ (`data_cot_nq`) | Rejected | Pipeline works, but gate failed: OOS objective below baseline, full CAGR lower | `building/reports/flag_sweep/GATE_REPORT_cot_nq.md` | Keep data pipeline for future research; flag remains OFF |
| MOVE + A19 + NAAIM batch-2 | Rejected | Added negative marginal value on top of A10/A11/A15; A module is cap-saturated | `docs/FACTOR_EXPLORATION_RESULTS_2026_06_08.md` | Do not add more A-module points without decoupling the cap/design |
| CNN Fear & Greed (`data_cnn_fgi`) | Rejected for performance | Full coverage and correctly wired, but effect is within noise: CAGR -0.03pp, MaxDD flat | `building/reports/flag_sweep/CNN_RESULT.md` | May be kept as a non-decision data feed, not a performance flag |
| Continuous sell fraction | Rejected for performance, accepted operationally | Gate was essentially neutral-to-slightly-worse; operational cliff-removal was human-approved separately | `building/reports/flag_sweep/GATE_REPORT_continuous_sell_fraction.md`; config `_sell_fraction_mode_note` | Do not sell as alpha; evaluate only as operator-experience logic |
| On-chain MSTR exchange inflow pressure (`data_onchain_mstr`, `CM_EXCHANGE_INFLOW_PRESSURE`) | Rejected | Historical T19 diagnostics: full CAGR 17.38%, MaxDD -13.77%, Sharpe 1.223; median OOS objective tied baseline (Δ +0.000), OOS bottom-half rate 0.00, DSR 1.197 | `building/reports/flag_sweep/GATE_REPORT_CM_EXCHANGE_INFLOW_PRESSURE.md`; `building/reports/flag_sweep/CM_EXCHANGE_INFLOW_PRESSURE.json` | Do not retune this signal; new on-chain work needs a new prior and a fresh formal gate |
| On-chain MSTR exchange netflow pressure (`data_onchain_mstr`, `CM_EXCHANGE_NETFLOW_PRESSURE`) | Rejected | Historical T19 diagnostics: full CAGR 17.36%, MaxDD -13.77%, Sharpe 1.222; median OOS objective tied baseline (Δ +0.000), OOS bottom-half rate 0.08, DSR 1.196 | `building/reports/flag_sweep/GATE_REPORT_CM_EXCHANGE_NETFLOW_PRESSURE.md`; `building/reports/flag_sweep/CM_EXCHANGE_NETFLOW_PRESSURE.json` | Do not retune this signal; new on-chain work needs a new prior and a fresh formal gate |
| MSTR B6 mNAV valuation (`data_mstr_mnav` + `use_b6_mnav_valuation`, `mnav_b6`) | Rejected | Historical diagnostics: CAGR 17.86%, median OOS objective below baseline (Δ -0.030), MaxDD -14.40%, OOS bottom-half rate 0.31, DSR 1.194 | `building/reports/flag_sweep/GATE_REPORT_mnav_b6.md`; `building/reports/flag_sweep/mnav_b6.json` | Keep the PIT mNAV source parked for diagnostics; do not turn on B6 valuation or retune this mapping without a new prior |
| Dollar soft-data SLO 6→14 days (`dollar-slo-14-v1`) | Rejected | One-shot formal gate found no next-open edge: WF and CPCV OOS Δ were both +0.000000. PBO 0.00, DSR 0.950058 and unchanged MaxDD passed, but strict OOS-improvement checks failed | `building/reports/formal_gate/dollar-slo-14-v1/result.json`; `building/reports/formal_gate/dollar-slo-14-v1/REPORT.md`; `docs/history/2026-07-11_dollar_slo_alignment_evidence.md` | Keep the production 6-day threshold. Do not retest this threshold; only a new upstream source or different mechanism with a new prior may open a new experiment |
| Exact FRED/ALFRED vintage replay (`use_fred_vintage_pit`, `fred-vintage-pit-v1`) | Rejected | One-shot formal gate: WF OOS Δ +0.165206 passed, but CPCV OOS Δ -0.077120 failed and MaxDD worsened from -20.83% to -22.55% (1.73pp, above the 1pp tolerance). PBO and DSR passed; full CAGR fell from 15.56% to 13.90%. | `building/reports/formal_gate/fred-vintage-pit-v1/result.json`; `building/reports/formal_gate/fred-vintage-pit-v1/REPORT.md`; `docs/history/2026-07-14_fred_vintage_pit_gate_result.md` | Keep production flag OFF and do not retune/re-run this experiment. The exact event store may be used as non-scoring audit/research evidence; a future production migration requires a new mechanism, prior, and manifest. |
| Arm-then-fire current design | Parked | Current arming inputs overlap additive scored factors, creating double-counting | `docs/FACTOR_EXPLORATION_RESULTS_2026_06_08.md` | Redesign as leading-data-only before one final gate |

### Candidate / next research

| Experiment | State | Hypothesis | Required validation |
|---|---|---|---|
| `use_indicator_cache` | Candidate | Reusing an indicator frame should reduce repeated score latency without changing payload semantics | OFF-path byte identity and a fresh performance measurement are required before any live flip |
| `use_market_admission_gate` | Live | Dual-source consensus prevents a corrupt or cross-wired Yahoo row from entering canonical history | 914 tests; four-date/six-artifact OFF identity; isolated and live read-only certification; operation `c192975dd63c478a904b21c152108a1c`; 8766 strategy health OK |
| `use_btc_spot_witness` | Live | Coinbase completed-day close should catch a corrupt Yahoo BTC row without rejecting normal cross-venue variation | `building/reports/data_quality/btc_spot_witness_off_equivalence_2026_07_14.json`; `btc_spot_witness_historical_overlap_2026_07_14.json`; 365/365 overlap, 0 days above 1%, max 0.5042%; 964 tests; live operation `b1ee0b6f3fb34f73a500661559c78356` |

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
- B6 valuation (5 pts): mNAV source is wired/parked, but B6 consumption gate failed and remains OFF

Effective live B cap = **16 pts** until B5/B6 are approved live. The `_module_caps_note` in
config.json also records this.

---

*Last updated: 2026-07-14 (FRED/ALFRED exact-vintage PIT candidate registered; production flag remains OFF)*
