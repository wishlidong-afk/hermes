# src/ Canonical Package — Migration Status

> **Created: 2026-06-02**
> This directory is the single canonical home for `hermes_escape_top`.
> All fixes from `review/CODE_REVIEW_FOLLOWUP.md` + `review/FIX_LOG_ROUND2.md` are applied here.
> `building/source_snapshots/` is now **archive only** — do not edit snapshots
> directly; edit `src/` and update snapshots only when cutting a new milestone.
>
> **Runnable truth & test status (2026-06-02):** the executable package (with data,
> 316 tests, phase scripts) lives at `~/.hermes/skills/investment/escape-top/`.
> The round-2 fixes were applied AND tested there: **315 passed / 1 failed**, where the
> single failure is a pre-existing module-B golden scoring drift unrelated to these fixes
> (see `review/RUN_LOG_TESTS_ROUND2.md`). `pipeline.py` / `risk_engine.py` /
> `sizing_optimizer.py` here mirror exactly what was tested. Phase II–IV backtests were
> NOT rerun (deferred) — old Sharpe/MaxDD/PBO numbers remain stale until then.

---

## Installed (canonical, with all fixes applied)

| Module | Source snapshot | Fixes applied |
|---|---|---|
| `core/contracts.py` | P4_confidence_spine | — (stable) |
| `core/confidence/spine.py` | P4_confidence_spine | — (correct as-is) |
| `core/portfolio/risk_engine.py` | P5_phase2_shadow | §1.4 sklearn bug, §三 EXTREME_CORR denominator, §4.1 rc_named ordering, 2026-06-04 `NormalDist.inv_cdf` Cornish-Fisher fix |
| `core/portfolio/sizing_optimizer.py` | P5_phase2_shadow + local `.hermes` | Kelly opt-in only, historical tilt guarded, E12 share/notional ADV split, redundant normal-CVaR solver removed |
| `pipeline.py` | P12_gate2_optimizer + local `.hermes` | ConfidenceSpine wired to real missing/staleness/drift signals, leg_returns+liquidity_data threaded, optimizer fallback warns |
| `core/data/failover.py` | P4_input_guardrails | — |
| `core/data/sanitize.py` | P4_input_guardrails | — |
| `core/data/adapters.py` | P3_soft_data_proxy | — |
| `core/data/crypto.py` | P3_soft_data_proxy | — |
| `core/factors/lab.py` | P4_factor_lab | — |
| `core/features/context.py` | P4_market_context | — |
| `core/audit/exporter.py` | P4_audit_exporter | — |
| `core/monitor/drift.py` | P4_drift_monitor | — |
| `core/governance/governance.py` | P4_governance | — |
| `core/reentry/tracker.py` | P4_reentry_tracker | — |
| `core/routing/leg_proxy.py` | NEXT3_calibration | — |
| `core/backtest/harness.py` | P4_validation_harness | — |
| `core/portfolio/tax.py` | P4_tax_awareness | — |
| `integration_config.py` | P4_phase_ii_config | — |

---

## 2026-06-04 Migration Closure

The missing local `.hermes` modules have been migrated into `src/`:

- `.config` and packaged `config/config.json`
- data layer: `base`, `flow`, `market`, `audit`, `quality`, `store`, adapters, options, sentiment, valuation, WSO index, PIT helpers
- scoring layer: A/B/C/D modules, registry, hard valves, scorer/result
- decision/routing/reentry/mirror/IBKR modules
- backtest/replay/posterior/reporting modules
- package tests and required offline history fixtures under `data/history`
- soft-data offline fixtures under `data/soft_history`

`src/` now imports without the local package:

```bash
PYTHONPATH=src python3 -c "from hermes_escape_top.pipeline import score_pipeline; print('pipeline OK')"
```

Full package verification:

```bash
PYTHONPATH=src python3 -m unittest discover -s src/hermes_escape_top/tests -p 'test_*.py'
# Ran 311 tests ... OK
```

---

## How to use src/ as the installed package

```bash
# From repo root
pip install -e src/

# Verify imports work
python -c "from hermes_escape_top.core.portfolio.risk_engine import build_risk_state; print('OK')"
python -c "from hermes_escape_top.core.portfolio.sizing_optimizer import optimize_targets; print('OK')"
python -c "from hermes_escape_top.core.confidence.spine import compute_confidence; print('OK')"
```

Once all missing modules are migrated, the full pipeline can be tested with:
```bash
python -c "from hermes_escape_top.pipeline import score_pipeline; print('pipeline OK')"
```
