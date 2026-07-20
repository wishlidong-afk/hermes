# Factor Capacity Inventory

Generated directly from `build_registry(symbol, config)`.
Config SHA-256: `c57cd6cac10484397ef4f9c0d7d259a1ea6dd9d3412077d5dbcb8e2736d7ad1c`

`defined_max` includes configured-off scoring definitions; `configured_reachable_max` excludes
non-scoring placeholders and deliberate missing-only gates. The scorer applies `module_cap` last.

## Module Summary

| Symbol | Module | Defined max | Reachable max | Cap | Post-cap | Clipped reachable |
|---|---|---:|---:|---:|---:|---:|
| MSTR | A | 50.0 | 50.0 | 20.0 | 20.0 | 30.0 |
| MSTR | B | 26.0 | 21.0 | 25.0 | 21.0 | 0.0 |
| MSTR | C | 36.0 | 36.0 | 35.0 | 35.0 | 1.0 |
| MSTR | D | 20.0 | 20.0 | 20.0 | 20.0 | 0.0 |
| FNGU | A | 50.0 | 50.0 | 20.0 | 20.0 | 30.0 |
| FNGU | B | 26.0 | 26.0 | 25.0 | 25.0 | 1.0 |
| FNGU | C | 36.0 | 36.0 | 35.0 | 35.0 | 1.0 |
| FNGU | D | 20.0 | 20.0 | 20.0 | 20.0 | 0.0 |
| SOXL | A | 50.0 | 50.0 | 20.0 | 20.0 | 30.0 |
| SOXL | B | 26.0 | 26.0 | 25.0 | 25.0 | 1.0 |
| SOXL | C | 36.0 | 36.0 | 35.0 | 35.0 | 1.0 |
| SOXL | D | 20.0 | 20.0 | 20.0 | 20.0 | 0.0 |

## Factor Definitions

| Symbol | Module | Factor | Max | Capacity state | Dependencies |
|---|---|---|---:|---|---|
| FNGU | A | `A10_REAL_RATE` | 4.0 | ACTIVE_SCORING | `SOFT.real_rate_10y_pctl` |
| FNGU | A | `A11_DOLLAR` | 4.0 | ACTIVE_SCORING | `SOFT.dollar_broad_pctl` |
| FNGU | A | `A15_DEFENSIVE_ROTATION` | 4.0 | ACTIVE_SCORING | `SOFT.defensive_cyclical_pctl` |
| FNGU | A | `A1_QQQ_MA200_BREAK` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ma200` |
| FNGU | A | `A1_VIX_COMPLACENCY` | 4.0 | ACTIVE_SCORING | `^VIX.close` |
| FNGU | A | `A2_AAII_BULL` | 2.0 | ACTIVE_SCORING | `SOFT.aaii_bull_bear_spread, SOFT.aaii_bull_pctl` |
| FNGU | A | `A2_CBOE_EQUITY_PCR` | 2.0 | ACTIVE_SCORING | `SOFT.equity_pcr, SOFT.equity_pcr_pctl` |
| FNGU | A | `A2_CNN_FEAR_GREED` | 0.0 | NON_SCORING_PLACEHOLDER | `A2 cnn_fear_greed` |
| FNGU | A | `A2_NAAIM` | 2.0 | ACTIVE_SCORING | `SOFT.naaim_exposure, SOFT.naaim_pctl` |
| FNGU | A | `A3_COMPONENT_BREADTH` | 4.0 | ACTIVE_SCORING | `SOFT.aggregate_pct_above_50dma, SOFT.aggregate_pct_above_200dma, SOFT.aggregate_breadth_chg_5d` |
| FNGU | A | `A4_QQQ_STRETCH` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ema20, QQQ.rsi14` |
| FNGU | A | `A5_NET_LIQUIDITY` | 4.0 | ACTIVE_SCORING | `SOFT.net_liq_chg10_pctl` |
| FNGU | A | `A6_FUND_FLOW` | 4.0 | ACTIVE_SCORING | `QQQ.cmf20, QQQ.mfi14, QQQ.ad_slope20` |
| FNGU | A | `A7_VIX_TERM_STRUCTURE` | 4.0 | ACTIVE_SCORING | `^VIX.close, ^VIX3M.close` |
| FNGU | A | `A8_QQQ_DISTRIBUTION` | 4.0 | ACTIVE_SCORING | `QQQ.distribution_days_25d, SPY.distribution_days_25d` |
| FNGU | B | `B1_RSI_OVERHEAT` | 5.0 | ACTIVE_SCORING | `rsi14` |
| FNGU | B | `B2_MA200_EXTENSION` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| FNGU | B | `B3_POST_PEAK_DAMAGE` | 5.0 | ACTIVE_SCORING | `drawdown_60d_high_pct` |
| FNGU | B | `B4_CBOE_OPTIONS_STRESS` | 6.0 | ACTIVE_SCORING | `SOFT.vvix_pctl, SOFT.skew_index, SOFT.skew_pctl` |
| FNGU | B | `B5_SOCIAL_EUPHORIA` | 0.0 | NON_SCORING_PLACEHOLDER | `B5 social` |
| FNGU | B | `B6_VALUATION_HEAT` | 5.0 | ACTIVE_SCORING | `SOFT.FNGU_valuation_pctl` |
| FNGU | C | `C10_MACRO_TREND_STRUCTURE` | 10.0 | ACTIVE_SCORING | `close, ema50, ma50, ma150, ma200` |
| FNGU | C | `C11_MA220_REBUILD_GAP` | 4.0 | ACTIVE_SCORING | `close, ma220` |
| FNGU | C | `C12_VOL_EXPANSION` | 4.0 | ACTIVE_SCORING | `realized_vol20` |
| FNGU | C | `C6_SHARP_DROP` | 5.0 | ACTIVE_SCORING | `return_2d` |
| FNGU | C | `C7_AVWAP_PLATFORM_SUPPORT` | 4.0 | ACTIVE_SCORING | `close, avwap_anchored_20d, support_20d_low` |
| FNGU | C | `C8_DISTRIBUTION_PRESSURE` | 4.0 | ACTIVE_SCORING | `distribution_days_25d` |
| FNGU | C | `C9_CHANDELIER_BREAK` | 5.0 | ACTIVE_SCORING | `close, chandelier_exit` |
| FNGU | D | `D1_ASSET_MA200_BREAK` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| FNGU | D | `D2_ASSET_MA220_BREAK` | 3.0 | ACTIVE_SCORING | `close, ma220` |
| FNGU | D | `D3_TRAILING_PEAK_DAMAGE` | 4.0 | ACTIVE_SCORING | `close, ema50, drawdown_60d_high_pct` |
| FNGU | D | `D4_RADAR_CONFIRMATION` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ma200, QQQ.ema50` |
| FNGU | D | `D_F4_COMPONENT_FLOW` | 4.0 | ACTIVE_SCORING | `NVDA.cmf20, NVDA.mfi14, NVDA.ad_slope20, AAPL.cmf20, AAPL.mfi14, AAPL.ad_slope20, MSFT.cmf20, MSFT.mfi14, MSFT.ad_slope20, AMZN.cmf20, AMZN.mfi14, AMZN.ad_slope20, META.cmf20, META.mfi14, META.ad_slope20, GOOGL.cmf20, GOOGL.mfi14, GOOGL.ad_slope20, TSLA.cmf20, TSLA.mfi14, TSLA.ad_slope20, NFLX.cmf20, NFLX.mfi14, NFLX.ad_slope20, AVGO.cmf20, AVGO.mfi14, AVGO.ad_slope20` |
| MSTR | A | `A10_REAL_RATE` | 4.0 | ACTIVE_SCORING | `SOFT.real_rate_10y_pctl` |
| MSTR | A | `A11_DOLLAR` | 4.0 | ACTIVE_SCORING | `SOFT.dollar_broad_pctl` |
| MSTR | A | `A15_DEFENSIVE_ROTATION` | 4.0 | ACTIVE_SCORING | `SOFT.defensive_cyclical_pctl` |
| MSTR | A | `A1_QQQ_MA200_BREAK` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ma200` |
| MSTR | A | `A1_VIX_COMPLACENCY` | 4.0 | ACTIVE_SCORING | `^VIX.close` |
| MSTR | A | `A2_AAII_BULL` | 2.0 | ACTIVE_SCORING | `SOFT.aaii_bull_bear_spread, SOFT.aaii_bull_pctl` |
| MSTR | A | `A2_CBOE_EQUITY_PCR` | 2.0 | ACTIVE_SCORING | `SOFT.equity_pcr, SOFT.equity_pcr_pctl` |
| MSTR | A | `A2_CNN_FEAR_GREED` | 0.0 | NON_SCORING_PLACEHOLDER | `A2 cnn_fear_greed` |
| MSTR | A | `A2_NAAIM` | 2.0 | ACTIVE_SCORING | `SOFT.naaim_exposure, SOFT.naaim_pctl` |
| MSTR | A | `A3_COMPONENT_BREADTH` | 4.0 | ACTIVE_SCORING | `SOFT.aggregate_pct_above_50dma, SOFT.aggregate_pct_above_200dma, SOFT.aggregate_breadth_chg_5d` |
| MSTR | A | `A4_QQQ_STRETCH` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ema20, QQQ.rsi14` |
| MSTR | A | `A5_NET_LIQUIDITY` | 4.0 | ACTIVE_SCORING | `SOFT.net_liq_chg10_pctl` |
| MSTR | A | `A6_FUND_FLOW` | 4.0 | ACTIVE_SCORING | `QQQ.cmf20, QQQ.mfi14, QQQ.ad_slope20` |
| MSTR | A | `A7_VIX_TERM_STRUCTURE` | 4.0 | ACTIVE_SCORING | `^VIX.close, ^VIX3M.close` |
| MSTR | A | `A8_QQQ_DISTRIBUTION` | 4.0 | ACTIVE_SCORING | `QQQ.distribution_days_25d, SPY.distribution_days_25d` |
| MSTR | B | `B1_RSI_OVERHEAT` | 5.0 | ACTIVE_SCORING | `rsi14` |
| MSTR | B | `B2_MA200_EXTENSION` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| MSTR | B | `B3_POST_PEAK_DAMAGE` | 5.0 | ACTIVE_SCORING | `drawdown_60d_high_pct` |
| MSTR | B | `B4_CBOE_OPTIONS_STRESS` | 6.0 | ACTIVE_SCORING | `SOFT.vvix_pctl, SOFT.skew_index, SOFT.skew_pctl` |
| MSTR | B | `B5_SOCIAL_EUPHORIA` | 0.0 | NON_SCORING_PLACEHOLDER | `B5 social` |
| MSTR | B | `B6_VALUATION_HEAT` | 5.0 | CONFIG_DISABLED | `B6 valuation` |
| MSTR | C | `C10_MACRO_TREND_STRUCTURE` | 10.0 | ACTIVE_SCORING | `close, ema50, ma50, ma150, ma200` |
| MSTR | C | `C11_MA220_REBUILD_GAP` | 4.0 | ACTIVE_SCORING | `close, ma220` |
| MSTR | C | `C12_VOL_EXPANSION` | 4.0 | ACTIVE_SCORING | `realized_vol20` |
| MSTR | C | `C6_SHARP_DROP` | 5.0 | ACTIVE_SCORING | `return_2d` |
| MSTR | C | `C7_AVWAP_PLATFORM_SUPPORT` | 4.0 | ACTIVE_SCORING | `close, avwap_anchored_20d, support_20d_low` |
| MSTR | C | `C8_DISTRIBUTION_PRESSURE` | 4.0 | ACTIVE_SCORING | `distribution_days_25d` |
| MSTR | C | `C9_CHANDELIER_BREAK` | 5.0 | ACTIVE_SCORING | `close, chandelier_exit` |
| MSTR | D | `D1_ASSET_MA200_BREAK` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| MSTR | D | `D2_ASSET_MA220_BREAK` | 3.0 | ACTIVE_SCORING | `close, ma220` |
| MSTR | D | `D3_TRAILING_PEAK_DAMAGE` | 4.0 | ACTIVE_SCORING | `close, ema50, drawdown_60d_high_pct` |
| MSTR | D | `D4_RADAR_CONFIRMATION` | 4.0 | ACTIVE_SCORING | `BTC-USD.close, BTC-USD.ma200` |
| MSTR | D | `D_M3_BTC_VOLATILITY_PROXY` | 4.0 | ACTIVE_SCORING | `BTC-USD.realized_vol20, BTC-USD.return_10d, BTC-USD.drawdown_60d_high_pct` |
| MSTR | D | `D_M4_BALANCE_SHEET_PROXY` | 0.0 | NON_SCORING_PLACEHOLDER | `D-M4` |
| MSTR | D | `D_M5_CRYPTO_SENTIMENT` | 0.0 | NON_SCORING_PLACEHOLDER | `D-M5` |
| SOXL | A | `A10_REAL_RATE` | 4.0 | ACTIVE_SCORING | `SOFT.real_rate_10y_pctl` |
| SOXL | A | `A11_DOLLAR` | 4.0 | ACTIVE_SCORING | `SOFT.dollar_broad_pctl` |
| SOXL | A | `A15_DEFENSIVE_ROTATION` | 4.0 | ACTIVE_SCORING | `SOFT.defensive_cyclical_pctl` |
| SOXL | A | `A1_QQQ_MA200_BREAK` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ma200` |
| SOXL | A | `A1_VIX_COMPLACENCY` | 4.0 | ACTIVE_SCORING | `^VIX.close` |
| SOXL | A | `A2_AAII_BULL` | 2.0 | ACTIVE_SCORING | `SOFT.aaii_bull_bear_spread, SOFT.aaii_bull_pctl` |
| SOXL | A | `A2_CBOE_EQUITY_PCR` | 2.0 | ACTIVE_SCORING | `SOFT.equity_pcr, SOFT.equity_pcr_pctl` |
| SOXL | A | `A2_CNN_FEAR_GREED` | 0.0 | NON_SCORING_PLACEHOLDER | `A2 cnn_fear_greed` |
| SOXL | A | `A2_NAAIM` | 2.0 | ACTIVE_SCORING | `SOFT.naaim_exposure, SOFT.naaim_pctl` |
| SOXL | A | `A3_COMPONENT_BREADTH` | 4.0 | ACTIVE_SCORING | `SOFT.aggregate_pct_above_50dma, SOFT.aggregate_pct_above_200dma, SOFT.aggregate_breadth_chg_5d` |
| SOXL | A | `A4_QQQ_STRETCH` | 4.0 | ACTIVE_SCORING | `QQQ.close, QQQ.ema20, QQQ.rsi14` |
| SOXL | A | `A5_NET_LIQUIDITY` | 4.0 | ACTIVE_SCORING | `SOFT.net_liq_chg10_pctl` |
| SOXL | A | `A6_FUND_FLOW` | 4.0 | ACTIVE_SCORING | `QQQ.cmf20, QQQ.mfi14, QQQ.ad_slope20` |
| SOXL | A | `A7_VIX_TERM_STRUCTURE` | 4.0 | ACTIVE_SCORING | `^VIX.close, ^VIX3M.close` |
| SOXL | A | `A8_QQQ_DISTRIBUTION` | 4.0 | ACTIVE_SCORING | `QQQ.distribution_days_25d, SPY.distribution_days_25d` |
| SOXL | B | `B1_RSI_OVERHEAT` | 5.0 | ACTIVE_SCORING | `rsi14` |
| SOXL | B | `B2_MA200_EXTENSION` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| SOXL | B | `B3_POST_PEAK_DAMAGE` | 5.0 | ACTIVE_SCORING | `drawdown_60d_high_pct` |
| SOXL | B | `B4_CBOE_OPTIONS_STRESS` | 6.0 | ACTIVE_SCORING | `SOFT.vvix_pctl, SOFT.skew_index, SOFT.skew_pctl` |
| SOXL | B | `B5_SOCIAL_EUPHORIA` | 0.0 | NON_SCORING_PLACEHOLDER | `B5 social` |
| SOXL | B | `B6_VALUATION_HEAT` | 5.0 | ACTIVE_SCORING | `SOFT.SOXL_valuation_pctl` |
| SOXL | C | `C10_MACRO_TREND_STRUCTURE` | 10.0 | ACTIVE_SCORING | `close, ema50, ma50, ma150, ma200` |
| SOXL | C | `C11_MA220_REBUILD_GAP` | 4.0 | ACTIVE_SCORING | `close, ma220` |
| SOXL | C | `C12_VOL_EXPANSION` | 4.0 | ACTIVE_SCORING | `realized_vol20` |
| SOXL | C | `C6_SHARP_DROP` | 5.0 | ACTIVE_SCORING | `return_2d` |
| SOXL | C | `C7_AVWAP_PLATFORM_SUPPORT` | 4.0 | ACTIVE_SCORING | `close, avwap_anchored_20d, support_20d_low` |
| SOXL | C | `C8_DISTRIBUTION_PRESSURE` | 4.0 | ACTIVE_SCORING | `distribution_days_25d` |
| SOXL | C | `C9_CHANDELIER_BREAK` | 5.0 | ACTIVE_SCORING | `close, chandelier_exit` |
| SOXL | D | `D1_ASSET_MA200_BREAK` | 5.0 | ACTIVE_SCORING | `close, ma200` |
| SOXL | D | `D2_ASSET_MA220_BREAK` | 3.0 | ACTIVE_SCORING | `close, ma220` |
| SOXL | D | `D3_TRAILING_PEAK_DAMAGE` | 4.0 | ACTIVE_SCORING | `close, ema50, drawdown_60d_high_pct` |
| SOXL | D | `D4_RADAR_CONFIRMATION` | 4.0 | ACTIVE_SCORING | `SOXX.close, SOXX.ma200, SOXX.ema50` |
| SOXL | D | `D_S4_COMPONENT_FLOW` | 4.0 | ACTIVE_SCORING | `NVDA.cmf20, NVDA.mfi14, NVDA.ad_slope20, AVGO.cmf20, AVGO.mfi14, AVGO.ad_slope20, AMD.cmf20, AMD.mfi14, AMD.ad_slope20, TSM.cmf20, TSM.mfi14, TSM.ad_slope20, ASML.cmf20, ASML.mfi14, ASML.ad_slope20, AMAT.cmf20, AMAT.mfi14, AMAT.ad_slope20, LRCX.cmf20, LRCX.mfi14, LRCX.ad_slope20, KLAC.cmf20, KLAC.mfi14, KLAC.ad_slope20, QCOM.cmf20, QCOM.mfi14, QCOM.ad_slope20, MU.cmf20, MU.mfi14, MU.ad_slope20` |
