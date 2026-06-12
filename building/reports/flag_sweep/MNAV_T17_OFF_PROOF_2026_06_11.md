# T17 mNAV OFF Proof — 2026-06-11

Scope: `features.data_mstr_mnav=false` and `features.use_b6_mnav_valuation=false` (default config).

No full-window backtest or gate was run. This proof uses isolated score runs with `HERMES_DATA_DIR` pointed at a temporary cloned data root, with IBKR patched to `{"source": "disabled"}`.

| as_of | input_hash before | input_hash after | match | MSTR score/status after |
|---|---|---|---|---|
| 2021-02-19 | `edf8ad06f6850295abdf28845af5dd7971c2b1552f7c9de7c2636f27a25d8ea8` | `edf8ad06f6850295abdf28845af5dd7971c2b1552f7c9de7c2636f27a25d8ea8` | yes | 35.84315789473684 / REDUCE |
| 2023-08-01 | `b9585de8a488d155bfba3b87f24d47a031d03d4382ba2454d1f8948448eca1af` | `b9585de8a488d155bfba3b87f24d47a031d03d4382ba2454d1f8948448eca1af` | yes | 23.851368421052634 / WATCH |
| 2025-01-13 | `c092f6828996ea7c0eb8677c899446aee3cb8585d16b8e54bf6d8f4304817b10` | `c092f6828996ea7c0eb8677c899446aee3cb8585d16b8e54bf6d8f4304817b10` | yes | 41.27652631578947 / EXIT |
| 2026-05-29 | `f3d17a1452228d080193958df1bc2c8a82a9c6990902c7956de9841b9fbf3025` | `f3d17a1452228d080193958df1bc2c8a82a9c6990902c7956de9841b9fbf3025` | yes | 49.66926315789474 / EXIT |

Additional checks:

- `risk_sources(config)` does not register `mstr_mnav` while `data_mstr_mnav=false`.
- `B6_VALUATION_HEAT` ignores `SOFT.MSTR_valuation_pctl` while `use_b6_mnav_valuation=false`, preserving the current B6 missing-weight path.
- Current repo history lacks `market_cap_usd` or `shares_outstanding` in `MSTR.csv`; with `data_mstr_mnav=true`, the source safely returns missing rather than inventing market cap from price alone.

Gate status: queued only after the回测 window is explicitly free and the MSTR market-cap input exists.
