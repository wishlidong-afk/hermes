# mNAV Module Ownership Decision — 2026-06-11

Task: T17 prework. Documentation only; no code changes.

## Decision

mNAV premium belongs to **B6 valuation heat**, not D.

Reason: mNAV is an MSTR-specific valuation/premium signal. B already owns overheat/valuation semantics; D owns asset-specific structural risk. If the same premium enters both B6 and D, Hermes double-counts one idea and quietly retunes MSTR risk upward without a clean gate.

## Boundary

| Surface | Allowed mNAV meaning | Disallowed overlap |
|---|---|---|
| B6 valuation | MSTR market cap premium/discount versus BTC holdings; percentile/rank of premium heat | None |
| D_M3 BTC risk | BTC trend/volatility/on-chain stress that affects MSTR through underlying BTC risk | mNAV premium, market-cap-to-BTC-holdings premium |
| D_M4 balance sheet / financing | debt maturity, convert pressure, financing/liquidity stress if a PIT source exists | mNAV premium as a proxy |
| D_M5 crypto sentiment | BTC market sentiment or on-chain exchange pressure, if orthogonal and capped inside D budget | mNAV premium as sentiment |
| Routing note | May mention mNAV as rationale for MSTR→BTC-USD route | Must not imply a second scoring contribution |

## Normalization Impact

Wiring B6 is not a small additive factor. Per the T17 task card, B effective max moves from 16 to 21 when B6 becomes available. That changes historical MSTR final scores through the effective-max / missing-weight path, even before B6 fires.

Gate implication: evaluate the complete in-system path with B6 present, not just standalone mNAV forward returns. The gate must include:

- B effective max change
- missing_weight reduction from B6 availability
- MSTR-only impact, with FNGU/SOXL unchanged
- interaction with status thresholds and hard-valve floors

## Weight Scheme

Initial proposal for a single T17 gate:

| Factor | Max | Scoring |
|---|---:|---|
| B6_MSTR_MNAV_VALUATION_HEAT | 5 | premium percentile >= 95: 5; >= 90: 3; >= 80: 2; >= 70: 1; else 0 |

No D weight is added. If mNAV becomes B6, D remains capped at 20 and must not introduce any mNAV/premium feature. If D later receives a separate on-chain survivor from T16/T19, it must replace or split the existing 4-point `D_M3_BTC_VOLATILITY_PROXY` budget, not expand the cap.

## Data Contract

Required PIT inputs:

- `date`
- `mstr_btc_holdings`
- `btc_price_usd`
- `mstr_market_cap_usd`
- `mnav`
- `mnav_premium`
- `mnav_premium_pctl_252`
- `source`
- `asof_reported_date`

BTC holdings are a slow variable and may be maintained by a low-frequency manual CSV from official company disclosures. Market cap and BTC price must be aligned point-in-time; no restated holdings may be applied before the reported date.

## Config Keys For Agent A

Suggested keys for A to merge when implementation starts:

| Key | Default | Comment |
|---|---:|---|
| `features.data_mstr_mnav` | `false` | Collect/read PIT MSTR BTC holdings + mNAV premium data; no scoring by itself |
| `features.use_b6_mnav_valuation` | `false` | Consume `SOFT.MSTR_valuation_pctl` in B6; must be byte-identical while OFF |

If A prefers a single flag, use `features.data_mstr_mnav=false` as both data and consumption gate, but the manual review note must say that enabling it changes B effective normalization and therefore requires a full in-system gate.

## Acceptance Bar

T17 should proceed only if:

- OFF state is byte-identical.
- B6 data availability does not silently lower missing_weight until the flag is ON.
- No D factor reads mNAV or premium.
- One gate decides the change. If it fails, archive to `docs/FLAG_REGISTRY.md` Rejected and do not retune thresholds.
