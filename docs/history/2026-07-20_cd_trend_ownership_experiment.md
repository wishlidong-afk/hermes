# C/D Trend Ownership Pre-Registration

## Ownership Decision

Module C owns broad price-trend damage:

- `C10_MACRO_TREND_STRUCTURE` owns EMA50, Minervini structure, and MA150/MA200
  break evidence.
- `C11_MA220_REBUILD_GAP` owns MA220 rebuild-line damage.

Module D retains symbol-specific confirmation that is not the same vote:

- `D3_TRAILING_PEAK_DAMAGE` (60-day peak drawdown plus EMA50);
- `D4_RADAR_CONFIRMATION` (BTC/QQQ/SOXX external radar); and
- the MSTR BTC-risk or FNGU/SOXL component-flow extras.

With `features.use_cd_trend_dedup=true`, D1 and D2 remain visible as zero-point
audit rows, have no dependencies or missing-data weight, and cannot add to the D
score. No points are reassigned, no module cap or status threshold changes, and
hard-valve logic is untouched. Repository and production default remain OFF.

## Fixed Acceptance

The single pre-registered gate uses next-open equity over the same 2018-01-01
through 2026-07-17 window for `cd_trend_baseline` and `cd_trend_dedup`.
Acceptance requires every standard alpha gate check: strictly positive
walk-forward and CPCV OOS deltas, PBO below 0.5 in both validations, MaxDD
worsening no greater than 1pp, and non-negative DSR.

Failure or neutrality means `Rejected`, no production flip, and no threshold,
weight, or factor-subset retuning.

## Evidence Paths

- Manifest: `research/experiments/cd-trend-ownership-v1.json`
- OFF equivalence: `building/reports/persistence/CD_TREND_DEDUP_OFF_EQUIVALENCE_2026_07_20.json`
- Flag artifacts: `building/reports/flag_sweep/cd_trend_baseline*.json` and
  `building/reports/flag_sweep/cd_trend_dedup*.json`
- Formal result: `building/reports/formal_gate/cd-trend-ownership-v1/`
