# Spec Trace Report - Desktop Logic Guide Coverage

Date: 2026-06-01

Source spec: `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## Coverage Matrix

| Spec Section | Build Status | Implementation |
|---|---:|---|
| 0 Greenfield rules | DONE | New independent package, no order path, deterministic offline replay, explicit missing-data penalty, v2.5 untouched. |
| 1 Layered architecture | DONE | `data -> features -> scoring -> decision -> portfolio -> routing -> reentry/backtest/web`. |
| 2 Minimal stack | DONE | Python/pandas/numpy/sqlite/http/unittest; optional sklearn fallback path in portfolio covariance. |
| 3 Directory structure | DONE | Directory tree matches spec, including `core`, `mirror`, `web`, `config`, `data`, `tests`, `reports`, `STATUS.md`. |
| 4 Data contracts | DONE | `Field`, `SymbolSnapshot`, `ScoreResult`, `PortfolioRiskState`, `SizingDecision`, `RoutingDecision`. |
| 5 Config schema | DONE | Single `config/config.json` with symbols, caps, thresholds, missing weights, regime, vol target, portfolio, routing, reentry, ATR, feature gates. |
| 6 Safety guard 1: hard valves | DONE | H-series pure functions with synthetic/history trigger tests; hard valves override to EXIT. |
| 6 Safety guard 2: price-module backtest gate | PARTIAL | Backtest/simulator/param-sweep scaffolds exist; full optimization and pass/fail calibration report still pending. |
| 6 Safety guard 3: dated soft data archive | IN-PROGRESS | FRED, CBOE SKEW/VVIX, AAII, and component breadth now resolve point-in-time; PCR/NAAIM/BTC funding-basis-DVOL/GEX/social/valuation remain pending. |
| Phase 0 contracts | DONE | Empty score pipeline and serialization tests. |
| Phase 1 data/offline | DONE | Local CSV store, dated archives, offline-safe snapshot reading, CMF/MFI/AD in OHLCV-derived layer. |
| Phase 2 indicators/features | DONE | EMA/MA/RSI/MACD/ATR/Chandelier/60D drawdown/distribution/AVWAP/platform support/CMF/MFI/AD/regime/volatility. |
| Phase 3 A/B/C/D scoring | DONE | Registry, module caps, symbol weights, missing scaling, regime weights, A6 fund flow, C7 platform support, D component flow. |
| Phase 4 hard valves | DONE | H-series trigger layer with no implicit IO. |
| Phase 5 verdict | DONE | Status ladder, upgrades, blind-spot escalation, hard-valve bypass. Persistent stabilization remains journal-backed but not production stateful. |
| Phase 6 portfolio risk | DONE-CODE / PENDING-CALIBRATION | Covariance, correlation regime, gross scaler, hard-valve exclusion; feature flag keeps scaler shadow-only until calibration. |
| Phase 7 sizing | DONE-CODE / PENDING-CALIBRATION | Vol scaler, gross scaler, no-more-aggressive invariant. |
| Phase 8 routing | DONE | DEFCON 1/2/3 routing plus BRK.B degradation to fallback. |
| Phase 9 3-3-4 reentry | DONE | Time/score/C/D locks, T1/T2/T3 plan, sell/hard-valve lockout, signal-journal sell-date lookup. |
| Phase 10 soft adapters | IN-PROGRESS | Historical FRED/CBOE/AAII/breadth sources wired; live/forward-only GEX, PCR, NAAIM, BTC microstructure, valuation, and social feeds still pending. |
| Phase 11 backtest/validation | ACCEPTANCE-READY / COVERAGE-CONSTRAINED | Replay, simulator, snapshot builder, cost model, metrics, labeling, purged CV, walk-forward splits, DSR scaffold, full routed runner, markdown/json report, and hard-valve historical tests exist. Strict 2018 start remains blocked by FNGU source coverage. |
| Phase 12 mirror | DONE | QQQ/FNGU, SOXX/SOXL, MSTR/QQQ mirror sleeves, SQLite snapshots, posterior ideal P/L. |
| Phase 13 meta model | LOCKED | Unlock gate not met. |
| Phase 14 WebUI/observability | PARTIAL | Read-only HTML/HTTP, current regime, module scores, vol scaler, route explain, missing/blind/data-quality, audit logs. IBKR drilldown is outside greenfield. |
| Phase 15 dry-run/switch | PARTIAL | HTTP server and audit/signal logs exist; production switch and real dry-run governance remain human-controlled. |
| NEXT-0 data foundation | DONE-CODE / PARTIAL-DATA | History backfill script, route-leg proxy, point-in-time picker, data manifest freeze/verify, coverage report. FNGU source coverage remains late. |
| NEXT-1 historical soft data | IN-PROGRESS / BLIND-SPOT-GATE-PASS | FRED/A5, CBOE SKEW-VVIX/B4, AAII/A2, component breadth/A3, and MSTR BTC price proxy/D-M3 wired. FNGU/SOXL/MSTR missing weights are now 19/19/26. PCR/NAAIM/true BTC funding-basis-DVOL remain. |
| NEXT-2 backtest foundation | ACCEPTANCE-READY / COVERAGE-CONSTRAINED | `run_full_backtest` now connects snapshots, score, sizing, routing, route-leg simulation, benchmarks, labels, walk-forward metadata, and reports. `Backtest_FULL.md/json` generated. Strict 2018 start still blocked by FNGU history. |

## Latest Local Score Sanity Check

Run date: `2026-05-29`

- Regime: `LOW_VOL_TREND`
- A6/C7/D-F4/D-S4 now resolve from local fields, not silent zero or missing placeholders.
- Remaining blind-spot pressure is from true soft-data sources: CNN FGI, CBOE PCR, NAAIM, social/valuation, and MSTR balance-sheet/crypto sentiment.
- Data manifest id after NEXT-0: `594e08958dde96fd6ce97c3c04fb91c0a0deb2480f94ec2f765f7d7cb89f524d`
- A5 FRED net-liquidity percentile on 2026-05-29: `44.8413`.
- Current missing weights: FNGU `19.0`, SOXL `19.0`, MSTR `26.0`; blind-spot gate now passes.
- Full routed backtest report: effective window `2025-02-20` to `2026-05-29`, final `$148,626.34`, CAGR `36.87%`, MaxDD `-11.43%`, Sharpe `1.7050`.

## Verification

- `PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top python3 -m unittest discover -s hermes_escape_top/tests`
- Result: 78 tests passing after NEXT-2 routed runner and hard-valve history pass.

## Remaining Non-Coding Dependencies

- Real provider credentials/endpoints for GEX, CBOE PCR, NAAIM, BTC funding/basis/DVOL, social/news, and exact MSTR mNAV.
- Human approval to activate non-price soft data in live scoring.
- A real dry-run window before any production replacement.
