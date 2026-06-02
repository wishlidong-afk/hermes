# Factor Health Report

**Generated**: 2026-06-02  
**Backtest window**: 2018-01-02 → 2026-05-29 (2113 days)  
**Outcome**: 20-day forward final_score delta (Spearman IC)  
**Symbols**: MSTR / FNGU / SOXL  

## Summary

| Metric | Value |
|---|---|
| Total factors | 32 |
| Alive in all 3 symbols | 19 |
| Alive in some symbols | 6 |
| Dead in all symbols | 7 |
| Top factor | C10_MACRO_TREND_STRUCTURE (avg|IC|=0.3791) |

## Factor IC Table (ranked by avg |IC|)

| Rank | Factor | Avg\|IC\| | MSTR IC | FNGU IC | SOXL IC | MSTR t | Status |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `C10_MACRO_TREND_STRUCTURE` | 0.3791 | -0.3479 | -0.3808 | -0.4085 | -16.97 | ✅ alive-all |
| 2 | `D3_TRAILING_PEAK_DAMAGE` | 0.3484 | -0.2874 | -0.3690 | -0.3888 | -13.72 | ✅ alive-all |
| 3 | `B3_POST_PEAK_DAMAGE` | 0.3480 | -0.2575 | -0.4044 | -0.3820 | -12.19 | ✅ alive-all |
| 4 | `A3_COMPONENT_BREADTH` | 0.3461 | -0.3050 | -0.3845 | -0.3488 | -14.65 | ✅ alive-all |
| 5 | `D4_RADAR_CONFIRMATION` | 0.3321 | -0.3129 | -0.3621 | -0.3213 | -15.07 | ✅ alive-all |
| 6 | `C9_CHANDELIER_BREAK` | 0.3198 | -0.2752 | -0.3769 | -0.3074 | -13.09 | ✅ alive-all |
| 7 | `A7_VIX_TERM_STRUCTURE` | 0.2929 | -0.2597 | -0.3054 | -0.3135 | -12.30 | ✅ alive-all |
| 8 | `A6_FUND_FLOW` | 0.2924 | -0.2507 | -0.3395 | -0.2871 | -11.84 | ✅ alive-all |
| 9 | `D1_ASSET_MA200_BREAK` | 0.2808 | -0.2289 | -0.2917 | -0.3219 | -10.75 | ✅ alive-all |
| 10 | `C11_MA220_REBUILD_GAP` | 0.2754 | -0.2381 | -0.2635 | -0.3245 | -11.21 | ✅ alive-all |
| 11 | `D2_ASSET_MA220_BREAK` | 0.2734 | -0.2219 | -0.2777 | -0.3205 | -10.41 | ✅ alive-all |
| 12 | `B2_MA200_EXTENSION` | 0.2727 | +0.2270 | +0.2689 | +0.3223 | 10.66 | ✅ alive-all |
| 13 | `A1_QQQ_MA200_BREAK` | 0.2561 | -0.2684 | -0.2617 | -0.2382 | -12.74 | ✅ alive-all |
| 14 | `C7_AVWAP_PLATFORM_SUPPORT` | 0.2485 | -0.3340 | -0.0036 | -0.4080 | -16.20 | ⚠️ alive-some |
| 15 | `A8_QQQ_DISTRIBUTION` | 0.2411 | -0.2270 | -0.2726 | -0.2236 | -10.66 | ✅ alive-all |
| 16 | `C12_VOL_EXPANSION` | 0.1837 | -0.0666 | -0.2737 | -0.2108 | -3.05 | ✅ alive-all |
| 17 | `C6_SHARP_DROP` | 0.1800 | -0.1182 | -0.2101 | -0.2118 | -5.44 | ✅ alive-all |
| 18 | `C8_DISTRIBUTION_PRESSURE` | 0.1672 | -0.2481 | -0.0226 | -0.2308 | -11.71 | ✅ alive-all |
| 19 | `A2_AAII_BULL` | 0.1534 | +0.1826 | +0.1176 | +0.1600 | 8.49 | ✅ alive-all |
| 20 | `B4_CBOE_OPTIONS_STRESS` | 0.0760 | -0.1156 | -0.0519 | -0.0605 | -5.32 | ✅ alive-all |
| 21 | `B1_RSI_OVERHEAT` | 0.0433 | +0.0121 | +0.0507 | +0.0672 | 0.55 | ⚠️ alive-some |
| 22 | `A5_NET_LIQUIDITY` | 0.0151 | -0.0246 | +0.0073 | -0.0134 | -1.12 | ⚠️ alive-some |
| 23 | `A2_CNN_FEAR_GREED` | 0.0000 | +0.0000 | +0.0000 | +0.0000 | 0.00 | ❌ dead |
| 24 | `A2_NAAIM` | 0.0000 | +0.0000 | +0.0000 | +0.0000 | 0.00 | ❌ dead |
| 25 | `A2_CBOE_EQUITY_PCR` | 0.0000 | +0.0000 | +0.0000 | +0.0000 | 0.00 | ❌ dead |
| 26 | `B5_SOCIAL_EUPHORIA` | 0.0000 | +0.0000 | +0.0000 | +0.0000 | 0.00 | ❌ dead |
| 27 | `B6_VALUATION_HEAT` | 0.0000 | +0.0000 | +0.0000 | +0.0000 | 0.00 | ❌ dead |
| 28 | `D_M3_BTC_VOLATILITY_PROXY` | nan | -0.2833 | +nan | +nan | -13.51 | ⚠️ alive-some |
| 29 | `D_M4_BALANCE_SHEET_PROXY` | nan | +0.0000 | +nan | +nan | 0.00 | ❌ dead |
| 30 | `D_M5_CRYPTO_SENTIMENT` | nan | +0.0000 | +nan | +nan | 0.00 | ❌ dead |
| 31 | `D_F4_COMPONENT_FLOW` | nan | +nan | -0.3032 | +nan | 0.00 | ⚠️ alive-some |
| 32 | `D_S4_COMPONENT_FLOW` | nan | +nan | +nan | -0.3053 | 0.00 | ⚠️ alive-some |

## Key Findings

### Top Signals (avg |IC| > 0.25)
- **`C10_MACRO_TREND_STRUCTURE`** avg|IC|=0.3791: MSTR=-0.3479 FNGU=-0.3808 SOXL=-0.4085
- **`D3_TRAILING_PEAK_DAMAGE`** avg|IC|=0.3484: MSTR=-0.2874 FNGU=-0.3690 SOXL=-0.3888
- **`B3_POST_PEAK_DAMAGE`** avg|IC|=0.3480: MSTR=-0.2575 FNGU=-0.4044 SOXL=-0.3820
- **`A3_COMPONENT_BREADTH`** avg|IC|=0.3461: MSTR=-0.3050 FNGU=-0.3845 SOXL=-0.3488
- **`D4_RADAR_CONFIRMATION`** avg|IC|=0.3321: MSTR=-0.3129 FNGU=-0.3621 SOXL=-0.3213
- **`C9_CHANDELIER_BREAK`** avg|IC|=0.3198: MSTR=-0.2752 FNGU=-0.3769 SOXL=-0.3074
- **`A7_VIX_TERM_STRUCTURE`** avg|IC|=0.2929: MSTR=-0.2597 FNGU=-0.3054 SOXL=-0.3135
- **`A6_FUND_FLOW`** avg|IC|=0.2924: MSTR=-0.2507 FNGU=-0.3395 SOXL=-0.2871
- **`D1_ASSET_MA200_BREAK`** avg|IC|=0.2808: MSTR=-0.2289 FNGU=-0.2917 SOXL=-0.3219
- **`C11_MA220_REBUILD_GAP`** avg|IC|=0.2754: MSTR=-0.2381 FNGU=-0.2635 SOXL=-0.3245
- **`D2_ASSET_MA220_BREAK`** avg|IC|=0.2734: MSTR=-0.2219 FNGU=-0.2777 SOXL=-0.3205
- **`B2_MA200_EXTENSION`** avg|IC|=0.2727: MSTR=+0.2270 FNGU=+0.2689 SOXL=+0.3223
- **`A1_QQQ_MA200_BREAK`** avg|IC|=0.2561: MSTR=-0.2684 FNGU=-0.2617 SOXL=-0.2382

### Dead Factors (|IC| < 0.02 in all symbols)
- `A2_CNN_FEAR_GREED` — consistently 0 or missing; consider removing or substituting
- `A2_NAAIM` — consistently 0 or missing; consider removing or substituting
- `A2_CBOE_EQUITY_PCR` — consistently 0 or missing; consider removing or substituting
- `B5_SOCIAL_EUPHORIA` — consistently 0 or missing; consider removing or substituting
- `B6_VALUATION_HEAT` — consistently 0 or missing; consider removing or substituting
- `D_M4_BALANCE_SHEET_PROXY` — consistently 0 or missing; consider removing or substituting
- `D_M5_CRYPTO_SENTIMENT` — consistently 0 or missing; consider removing or substituting

### Redundancy Clusters

Factors with similar signals (manual cluster based on domain knowledge):

| Cluster | Members | Action |
|---|---|---|
| Macro trend | C10, D1, D2, B2, C11 | High IC but correlated (MA-family) — keep highest IC (C10), reduce weights of others |
| Damage signals | D3, B3 | Both measure drawdown damage — keep higher-IC D3 for SOXL, B3 for FNGU |
| Breadth | A3, D4 | Both measure participation breadth — complementary, keep both |
| VIX/Term | A1, A7 | QQQ MA200 and VIX term structure — different dimensions, keep both |

## ECE / Calibration Note

Score probability calibration (E2) pending full isotonic regression run.
Current IC evidence suggests C10, D3, B3 are the strongest predictors of 20d risk.
Recommend weighting these factors higher in future calibration sweep.

## Gate 6 Verdict

- **Alive factors (all 3 symbols)**: 19/32
- **Top avg |IC|**: 0.3791 (`C10_MACRO_TREND_STRUCTURE`)
- **Dead factors**: 7
- **Gate 6 Status**: ✅ PASS — factor IC computed, health documented, redundancy clusters identified