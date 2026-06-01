# NEXT-1 Report - Historical Soft Data

Date: 2026-06-01

Source spec: `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## Scope Completed

Implemented and wired the first historical soft-data block:

- N1-T01 FRED net liquidity -> `A5_NET_LIQUIDITY`
- N1-T02 CBOE indices from local history -> `B4_CBOE_OPTIONS_STRESS`
- N1-T04 AAII sentiment from local Excel history -> `A2_AAII_BULL`
- N1-T06 component breadth from local component histories -> `A3_COMPONENT_BREADTH`
- MSTR interim D-M3 BTC micro proxy from `BTC-USD` price history -> `D_M3_BTC_VOLATILITY_PROXY`

The D-M3 item is explicitly a proxy. It does not replace the later funding/basis/DVOL adapters, but it removes the unsafe all-missing edge while those feeds are still pending.

## Implemented Files

- `core/data/macro.py`
  - `FredNetLiquiditySource`
  - `CboeIndicesSource`
  - FRED graph CSV fetch and point-in-time frame generation.
- `core/data/sentiment.py`
  - `AaiiSource`
  - `NaaimSource` contract and local CSV reader.
- `core/data/breadth.py`
  - `ComponentBreadthSource`
  - 50DMA/200DMA component breadth and 5D breadth-change fields.
- `core/data/store.py`
  - Read-time quality filters for known bad `BTC-USD`, `^VVIX`, and `^SKEW` rows.
- `core/data/adapters.py`
  - Historical soft-data sources are now part of `default_sources()`.
- `pipeline.py`
  - Builds the `SOFT` pseudo snapshot used by scoring.
- `core/scoring/module_a.py`
  - A2 AAII, A3 breadth, A5 net-liquidity wired.
- `core/scoring/module_b.py`
  - B4 CBOE options stress wired.
- `core/scoring/module_d.py`
  - D-M3 BTC volatility proxy wired for MSTR.
- `config/config.json`
  - Enables `data_skew_vvix`, `data_net_liquidity`, `data_aaii`, `data_component_breadth`.

## Current Data Reads

As of `2026-05-29`:

| Field | Value | Source | Score Use |
|---|---:|---|---|
| `net_liq_chg10_pctl` | 44.8413 | FRED | A5 score 0 |
| `aaii_bull_bear_spread` | -11.8942% | AAII Excel | A2 score 0 |
| `aaii_bull_pctl` | 16.6667 | AAII Excel | A2 score 0 |
| `aggregate_pct_above_50dma` | 94.1176% | local component histories | A3 score 0 |
| `aggregate_pct_above_200dma` | 82.3529% | local component histories | A3 score 0 |
| `skew_index` | 144.1800 | local CBOE history | B4 score 0 |
| `skew_pctl` | 43.6508 | local CBOE history | B4 score 0 |
| `vvix_pctl` | 2.7778 | local CBOE history, quality-filtered | B4 score 0 |
| `BTC vol20 / ret10 / dd60` | 22.4% / -4.4% / -10.5% | BTC price proxy | D-M3 score 0 |

Data quality note:

- Raw `BTC-USD` and `^VVIX` contained bad terminal rows. The reader now filters impossible rows before scoring, preventing false MSTR/B4 stress spikes.
- The raw CSVs were also repaired and the price manifest was re-frozen:
  - `BTC-USD 2026-05-29 close = 73372.5234375`
  - `^VVIX 2026-05-29 close = 86.05999755859375`
  - `data_manifest_id = 594e08958dde96fd6ce97c3c04fb91c0a0deb2480f94ec2f765f7d7cb89f524d`

## Missing-Weight Rebaseline

As of `2026-05-29`:

| Symbol | Before NEXT-1 | After FRED Only | Current | Total Change | Current Status |
|---|---:|---:|---:|---:|---|
| FNGU | 31.0 | 27.0 | 19.0 | -12.0 | HOLD |
| MSTR | 42.0 | 38.0 | 26.0 | -16.0 | EXIT |
| SOXL | 31.0 | 27.0 | 19.0 | -12.0 | HOLD |

N1-T10 target check:

- Required: all three symbols `missing_weight < 30`.
- Current: PASS.
- Caveat: true CBOE PCR, NAAIM, BTC funding/basis/DVOL, social, valuation, and GEX remain pending. The current PASS is sufficient to remove blind-spot escalation, not sufficient to claim the soft-data layer is complete.

## Current Score Snapshot

```text
FNGU HOLD  final_score=9.91   missing_weight=19.0  hard=[]
MSTR EXIT  final_score=45.03  missing_weight=26.0  hard=['H-M1', 'H-M4']
SOXL HOLD  final_score=15.09  missing_weight=19.0  hard=[]
```

## Verification

```text
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m unittest discover -s hermes_escape_top/tests
Ran 78 tests in 19.375s
OK

PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m compileall -q hermes_escape_top
OK
```

## Remaining NEXT-1 Work

- N1-T03 CBOE put/call history.
- N1-T05 NAAIM exposure history.
- N1-T07/N1-T08/N1-T09 true BTC funding, basis, and DVOL feeds.
- Replace D-M3 price proxy with true BTC microstructure once those feeds are cached.
- Keep CNN FGI, GEX, news/social, and exact MSTR mNAV in NEXT-4 forward-only unless reliable historical feeds are found.
