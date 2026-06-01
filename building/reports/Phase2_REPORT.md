# Phase 2 Report - Indicators And Feature Layer

Date: 2026-06-01

## Scope

Phase 2 adds deterministic, replay-safe feature primitives for later A/B/C/D scoring:

- Rolling percentile and z-score normalization with strict no-forward-look behavior.
- Volatility feature layer: 20-day realized volatility, EWMA volatility forecast, baseline realized-volatility comparison, and relative volatility scaler.
- Price and platform layer: EMA/MA, RSI, MACD, ATR, Chandelier 22 x 4.5, 60D drawdown, distribution days, 60D AVWAP proxy, and 60D platform support distance.
- Money-flow layer: VWAP20, CMF20, MFI14, AD line, and AD20 slope for symbols and component baskets.
- Market regime classifier: LOW_VOL_TREND / CHOP / HIGH_VOL / CRISIS / UNKNOWN.
- Asymmetric regime hysteresis: risk deterioration switches immediately; risk improvement requires persistence.

## Contracts

- Missing feature inputs produce `None`/`NaN`; they are not converted into safe scores inside the feature layer.
- Percentile and z-score values at date T use only observations at or before T.
- Volatility scaler is capped between `floor` and `1.0`; missing or invalid volatility inputs return neutral scaler `1.0`.
- Regime transitions are deterministic and can be replayed from historical data.
- AVWAP/platform and CMF/MFI/AD are derived from OHLCV only, so they work in offline replay and never require live soft-data calls.

## Verification

- Unit tests cover causal normalization, percentile scoring, volatility scaling, regime classification, hysteresis behavior, platform support, AVWAP, and money-flow fields.
- No network dependency was added.

## Remaining Gaps

- GARCH and learned regime models remain disabled by config and intentionally out of scope for Phase 2.
