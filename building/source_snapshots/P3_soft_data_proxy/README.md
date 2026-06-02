# P3 Soft Data Proxy — Source Snapshot

**Date**: 2026-06-02

## Contents

| File | Change |
|---|---|
| `core/data/crypto.py` | Full rewrite: `CryptoFundingSource` reading `btc_funding_basis.csv` proxy |
| `core/data/adapters.py` | `default_sources()` replaces `MissingSource("btc_micro")` with `CryptoFundingSource()` |
| `tests/test_phase10_adapters.py` | Updated assertion: `btc_micro` → `btc_funding_basis` |

## CSVs generated (local only, not in repo)

- `data/soft_history/cboe_equity_pcr.csv` — VIX-derived PCR proxy, 2095 rows
- `data/soft_history/naaim_exposure.csv` — QQQ-13wk-derived NAAIM proxy, 423 weekly rows
- `data/soft_history/btc_funding_basis.csv` — BTC momentum-derived funding/basis proxy, 3034 rows

## Result

270 package tests OK. All three adapters return `data_available=True` for 2026-05-29.
