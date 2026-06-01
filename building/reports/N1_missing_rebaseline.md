# N1 Missing-Weight Rebaseline

Date: 2026-06-01

As-of: `2026-05-29`

## Change Set

The following missing placeholders were replaced with point-in-time fields:

- `A5_NET_LIQUIDITY`: `SOFT.net_liq_chg10_pctl`
- `A2_AAII_BULL`: `SOFT.aaii_bull_bear_spread`, `SOFT.aaii_bull_pctl`
- `A3_COMPONENT_BREADTH`: `SOFT.aggregate_pct_above_50dma`, `SOFT.aggregate_pct_above_200dma`, `SOFT.aggregate_breadth_chg_5d`
- `B4_CBOE_OPTIONS_STRESS`: `SOFT.vvix_pctl`, `SOFT.skew_index`, `SOFT.skew_pctl`
- `D_M3_BTC_VOLATILITY_PROXY`: `BTC-USD.realized_vol20`, `BTC-USD.return_10d`, `BTC-USD.drawdown_60d_high_pct`

## Result

| Symbol | Old Missing Weight | After FRED Only | Current Missing Weight | Delta vs Old | Blind Spot | New Status |
|---|---:|---:|---:|---:|---:|---|
| FNGU | 31.0 | 27.0 | 19.0 | -12.0 | false | HOLD |
| MSTR | 42.0 | 38.0 | 26.0 | -16.0 | false | EXIT |
| SOXL | 31.0 | 27.0 | 19.0 | -12.0 | false | HOLD |

## New Available Reads

```text
A2 AAII: spread=-11.8942%, bull_pctl=16.6667, score=0
A3 breadth: 94.1176% above 50DMA, 82.3529% above 200DMA, score=0
A5 FRED: net_liq_chg10_pctl=44.8413, score=0
B4 CBOE: vvix_pctl=2.7778, skew=144.1800, skew_pctl=43.6508, score=0
D-M3 BTC proxy: vol20=22.4%, ret10=-4.4%, dd60=-10.5%, score=0
```

## Remaining Blind Spots

Shared:

- `A2 cnn_fear_greed` = 2
- `A2 naaim` = 4
- `A2 cboe_equity_pcr` = 4
- `B5 social` = 4
- `B6 valuation` = 5

MSTR extra:

- `D-M4` balance-sheet/mNAV proxy = 4
- `D-M5` crypto sentiment = 3

## Assessment

The hard target `missing_weight < 30` is now met for FNGU, MSTR, and SOXL.

This does not finish NEXT-1. It only removes the model-quality blocker that was causing blind-spot escalation. CBOE PCR, NAAIM, BTC funding/basis/DVOL, and exact MSTR valuation still need true data feeds or explicit proxy contracts.
