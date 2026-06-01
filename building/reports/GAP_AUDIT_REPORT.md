# Gap Audit Report - Spec vs Greenfield Implementation

Date: 2026-06-01

Source spec: `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## Completed In This Pass

- Implemented revised-spec NEXT-0 data foundation:
  - `scripts/backfill_history.py`
  - `core/routing/leg_proxy.py`
  - `core/data/pit.py`
  - `core/data/manifest.py`
  - CLI commands: `backfill-history`, `freeze-manifest`, `verify-manifest`
  - `reports/NEXT0_REPORT.md`
  - `reports/N0_history_coverage.md`
- Backfill now repairs both head gaps and tail gaps, not only appending after the current max date.
- Backtest and parameter-sweep payloads now include `data_manifest_id`.
- Latest manifest verification succeeded with 38 entries.
- Implemented NEXT-1 first pass:
  - FRED net liquidity backfill/cache.
  - `SOFT` pseudo snapshot for scoring.
  - `A5_NET_LIQUIDITY` now reads `SOFT.net_liq_chg10_pctl`.
  - `reports/NEXT1_REPORT.md`
  - `reports/N1_missing_rebaseline.md`
- Re-read `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md` as the active specification source and patched remaining price-core placeholders.
- Added AVWAP/platform support and money-flow fields to the deterministic OHLCV indicator layer:
  - `vwap20`
  - `avwap_60d`
  - `support_60d_low`
  - `support_distance_60d_pct`
  - `cmf20`
  - `mfi14`
  - `ad_line`
  - `ad_slope20`
- Wired A6 fund-flow pressure to QQQ CMF/MFI/AD instead of a missing placeholder.
- Wired C7 AVWAP/platform support to local OHLCV features instead of a missing placeholder.
- Wired FNGU/SOXL D-module component flow:
  - FNGU basket: NVDA, AAPL, MSFT, AMZN, META, GOOGL, TSLA, NFLX, AVGO.
  - SOXL basket: NVDA, AVGO, AMD, TSM, ASML, AMAT, LRCX, KLAC, QCOM, MU.
- Expanded score snapshots to include component-proxy symbols so component flow is available in replay.
- Wired current market regime into the main score pipeline and dashboard:
  - radar: QQQ trend stack
  - stress: VIX percentile and VIX/VIX3M term ratio
- Expanded the read-only WebUI with current regime, module scores, vol scaler, missing weight, blind spot, data quality, and route explanation.
- Added transaction-level local backtest scaffold:
  - `core/backtest/simulator.py`
  - `cli backtest`
- Added parameter-sweep scaffold:
  - `core/backtest/param_sweep.py`
  - `cli param-sweep`
- Added calibration primitives:
  - `core/backtest/labeling.py`
  - `core/backtest/validation.py`
  - `core/backtest/reports.py`
- Added soft-data contract modules required by the spec:
  - `core/data/breadth.py`
  - `core/data/valuation.py`
  - `core/data/macro.py`
  - `core/data/options.py`
  - `core/data/crypto.py`
- Added DEFCON2 BRK.B degradation monitor:
  - BRK.B close <= MA200 routes DEFCON2 proceeds to configured fallback.
  - BRK.B/SPY high correlation can also degrade BRK.B.
- Added structured audit log:
  - `core/data/audit.py`
  - `data/archive/audit_log.jsonl`
  - audit replay hash check.
- Added persistent signal journal:
  - `core/decision/signal_journal.py`
  - reentry now reads trading days since last prior sell from journal instead of hardcoding zero.
- Added config flags named in the spec:
  - `use_rolling_quantile`
  - `use_regime_weights`
  - `use_portfolio_risk_budget`
  - `routing_v2`

## Still Blocked Or Intentionally Not Done

- Real GEX/SKEW/VVIX/net-liquidity/BTC micro values:
  - Contract and cache paths exist.
  - Live providers/credentials are not configured.
  - Missing data remains explicit; no fake zeros are emitted.
- Meta model:
  - Remains `LOCKED`.
  - Unlock gate requires enough completed labeled signals.
- Production WebUI replacement:
  - Greenfield read-only HTTP server exists.
  - Existing production UI has not been switched over.
- IBKR reconciliation:
  - Not implemented in greenfield.
  - No order write path was added.
- Human-controlled feature activation:
  - Spec says Codex must not flip runtime feature flags to affect production behavior.

## Verification

- `PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m unittest discover -s hermes_escape_top/tests`: 78 tests passing.
- `freeze-manifest` / `verify-manifest`: manifest id `594e08958dde96fd6ce97c3c04fb91c0a0deb2480f94ec2f765f7d7cb89f524d`, verification OK.
- `backfill-history --start 2018-01-01`: 34/38 tracked symbols have history at or before 2018-01-02; FNGU remains late at 2025-02-20 from current yfinance source.
- `soft-data --as-of 2026-05-29`: FRED net liquidity available, `net_liq_chg10_pctl=44.8413`.
- Missing-weight rebaseline: FNGU/SOXL moved from 31.0 to 27.0; MSTR moved from 42.0 to 38.0.
- `cli backtest --start 2026-05-28 --end 2026-05-29 --limit 2`: deterministic local backtest payload produced.
- `cli param-sweep --start 2026-05-28 --end 2026-05-29 --limit 2`: 54 local sweep rows produced.
- `score_pipeline("2026-05-29")` now reports regime `LOW_VOL_TREND`; A6/C7/D-F4/D-S4 are populated from real local fields with no missing placeholders for FNGU/SOXL.

## Risk Notes

- Current backtest and sweep are scaffolds, not final optimization. The sweep uses static target weights as a calibration shell; full rule-replay optimization should replace that target generator before treating values as final.
- Local history does not include BRK.B, BOXX, or DBMF in the greenfield history directory. BRK.B degradation logic is implemented and unit-tested with synthetic snapshots, but live degradation requires local BRK.B history or a configured market data adapter.
