# On-Chain Data Source Audit — 2026-06-11

Task: T16 step 0, before any factor coding.

## Verdict

Coin Metrics Community API is usable for an offline MSTR on-chain lab subset:

- MVRV: usable via `CapMVRVCur`
- exchange flows: usable via `FlowInExUSD`, `FlowOutExUSD`, derived netflow
- exchange supply: usable via `SplyExUSD`
- market/price denominators: usable via `PriceUSD`, `CapMrktCurUSD`, `SplyCur`

It is not sufficient for the full requested field set:

- realized cap absolute value (`CapRealUSD`) returns 403 without paid credentials
- SOPR and holder-segment SOPR fields return 403 without paid credentials
- realized-cap derivatives such as `MCRC`, `RCTC`, and `RevAllTimeUSD` return 403

Proceeding rule: write offline lab code only for the verified community subset. Do not implement SOPR/realized-cap factor code until a paid/pro source or approved alternative is available.

## Official Source Check

| Check | Result | Source |
|---|---|---|
| Community root endpoint | `https://community-api.coinmetrics.io/v4` | [Coin Metrics Community Data](https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data) |
| Authentication | No API key required for community endpoints | [Coin Metrics Community Data](https://gitbook-docs.coinmetrics.io/packages/coin-metrics-community-data) |
| Rate limit | 10 requests per 6 seconds per IP; implement against this lower bound even if response headers are looser | [API Conventions](https://gitbook-docs.coinmetrics.io/access-our-data/api) |
| License | Community data is free for non-commercial use under a Creative Commons license; commercial redistribution/client use needs legal/pro review | [API Conventions](https://gitbook-docs.coinmetrics.io/access-our-data/api) |
| Python client | Official client can use community API with `CoinMetricsClient()` and handles pagination | [Coin Metrics Python API Client](https://coinmetrics.github.io/api-client-python/docs/) |

## Live API Probe

Probe date: 2026-06-11. Endpoint shape:

```text
https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc&metrics=<metric>&frequency=1d&start_time=2018-01-01&end_time=2018-01-05
```

| Metric | Purpose | Probe result | Notes |
|---|---|---|---|
| `CapMVRVCur` | MVRV | OK | 2018 sample returned daily rows |
| `CapRealUSD` | realized cap absolute | 403 | catalog-all visible but not community timeseries |
| `FlowInExUSD` | exchange inflow | OK | 2018 sample returned daily rows |
| `FlowOutExUSD` | exchange outflow | OK | 2018 sample returned daily rows |
| `FlowNetExUSD` | exchange netflow | 400 | not a supported metric; derive `FlowInExUSD - FlowOutExUSD` |
| `SplyExUSD` | exchange-held supply | OK | 2018 sample returned daily rows |
| `SOPR` | spent-output profit ratio | 403 | catalog-all visible but not community timeseries |
| `SOPRSth155d` | short-term holder SOPR | 403 | paid/pro only in current probe |
| `SOPRLth155d` | long-term holder SOPR | 403 | paid/pro only in current probe |
| `PriceUSD` | BTC price denominator | OK | 2018 sample returned daily rows |
| `CapMrktCurUSD` | market cap denominator | OK | 2018 sample returned daily rows |
| `SplyCur` | current supply | OK | 2018 sample returned daily rows |
| `MCRC` / `RCTC` / `RevAllTimeUSD` | realized-cap derivatives | 403 | paid/pro only in current probe |

Historical depth probe for the usable subset:

- first rows found by 2013-01-11 for `CapMVRVCur`, exchange flows, exchange supply, price, and market cap
- recent rows returned through 2026-06-10
- Hermes research window 2018-01-01 to 2026-05-29 is covered

## Alternative Source Assessment

| Source | What it can cover | Constraint | Decision |
|---|---|---|---|
| Coin Metrics Pro | `CapRealUSD`, SOPR, LTH/STH SOPR, realized-cap derivatives, same API semantics | paid API key / commercial terms | best upgrade path if SOPR or realized cap absolute is required |
| Glassnode API | MVRV breakdowns, realized cap breakdowns, SOPR family, richer holder cohorts | API key required; terms/tier must be checked before use | viable paid alternative for T16 phase 2 |
| CryptoQuant API | exchange inflow/outflow/netflow, cohort realized cap, SOPR-style metrics | API key/product access; separate methodology | viable paid alternative, especially for exchange-flow cross-checks |
| Blockchain.com charts/API | free general Bitcoin market/network charts | lacks MVRV/SOPR/exchange wallet entity metrics needed here | insufficient as primary T16 source |

## Implementation Boundary

Approved for offline lab:

- MVRV heat
- exchange inflow/netflow pressure
- exchange-supply pressure
- derived composite on-chain heat from the verified fields above

Explicitly not approved for code in this pass:

- SOPR
- short/long-term holder SOPR
- absolute realized cap as a direct factor
- realized-cap derivatives requiring 403-gated metrics

Any future production data flag should be proposed to Agent A as `features.data_onchain_mstr=false` or equivalent, with max-age SLO and source terms reviewed before merge.
