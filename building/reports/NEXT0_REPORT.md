# NEXT-0 Report - Data Foundation

Date: 2026-06-01

Source spec: `/Users/liweishi/Desktop/逃顶与镜像系统逻辑说明.md`

## Scope

NEXT-0 is the new hard prerequisite before soft-data scoring and full calibration:

- N0-T01: price history backfill to 2018+.
- N0-T02: route-leg proxy series for BOXX/DBMF.
- N0-T03: point-in-time as-of picker.
- N0-T04: data manifest freeze/verify.

## Implemented

- `scripts/backfill_history.py`
  - `backfill(symbols, start="2018-01-01", end=None, store_dir="data/history")`
  - Idempotent head-gap and tail-gap repair.
  - yfinance symbol alias: `BRK.B -> BRK-B`.
  - Fixed CSV schema: `date,open,high,low,close,adj_close,volume`.
  - Coverage report writer.
- `core/routing/leg_proxy.py`
  - `BOXX` pre-inception proxy to `BIL`.
  - `DBMF` pre-inception proxy to `trend_synth`.
  - Continuous splice at proxy switch.
  - Proxy metadata with `is_proxy`.
- `core/data/pit.py`
  - `asof_pick(records, as_of, publish_lag_days=0)` returns only records available at or before `as_of`.
- `core/data/manifest.py`
  - `freeze_manifest(store_dir)`.
  - `write_manifest(store_dir, output_path)`.
  - `verify_manifest(store_dir, manifest_path)`.
  - CSV row count and date coverage metadata.
- CLI commands:
  - `backfill-history`
  - `freeze-manifest`
  - `verify-manifest`
- Backtest and parameter-sweep payloads now include `data_manifest_id`.

## Live Coverage Run

Command:

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m hermes_escape_top.cli backfill-history \
  --start 2018-01-01 \
  --report hermes_escape_top/reports/N0_history_coverage.md
```

Coverage report:

- `reports/N0_history_coverage.md`

Summary:

- Total tracked symbols: 38.
- Symbols at or before 2018-01-02: 34.
- Later real inceptions / source gaps:
  - `BOXX`: 2022-12-28, covered before inception by route proxy `BIL`.
  - `DBMF`: 2019-05-08, covered before inception by `trend_synth`.
  - `FNGS`: 2019-11-13, source does not provide 2018 start.
  - `FNGU`: 2025-02-20 in current yfinance source; source did not provide 2018-2025 rows.

## Data Manifest

Command:

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m hermes_escape_top.cli freeze-manifest \
  --store-dir hermes_escape_top/data/history \
  --output hermes_escape_top/data/archive/data_manifest_latest.json
```

Latest manifest:

- Path: `data/archive/data_manifest_latest.json`
- Entries: 38
- Manifest id: `594e08958dde96fd6ce97c3c04fb91c0a0deb2480f94ec2f765f7d7cb89f524d`

Verification:

```text
verify-manifest -> ok: true
```

## Data Repair Addendum

After NEXT-1 scoring exposed bad terminal rows, the price history was repaired and the manifest was frozen again:

- `BTC-USD 2026-05-29 close`: repaired from `474.48` to `73372.5234375`.
- `^VVIX 2026-05-29 close`: repaired from `12.59` to `86.05999755859375`.
- `scripts/backfill_history.py` now supports `--repair-overlap-days` for future overlap refreshes.

## Tests

Command:

```bash
PYTHONPATH=/Users/liweishi/.hermes/skills/investment/escape-top \
python3 -m unittest discover -s hermes_escape_top/tests
```

Result:

```text
Ran 78 tests in 19.375s
OK
```

## Known Gaps

- `FNGU` remains the key data blocker for full 2018+ FNGU-specific backtests. Current yfinance source returns only 2025-02-20 onward for this symbol.
- `FNGS` begins 2019-11-13 in the current source.
- Missing weekday counts include exchange holidays because no exchange calendar dependency has been added yet.
- Route legs are covered by proxy series, but proxy segments must be explicitly labeled in any performance report.

## Status

NEXT-0 is `DONE-CODE / PARTIAL-DATA`:

- Code and tests are complete.
- Most symbols have 2018+ data.
- FNGU historical source coverage remains unresolved and must be handled before claiming full 2018+ FNGU calibration.
