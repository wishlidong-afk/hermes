# src/ Canonical Package — Migration Status

> **Created: 2026-06-02**
> This directory is the single canonical home for `hermes_escape_top`.
> All fixes from `review/CODE_REVIEW_FOLLOWUP.md` + `review/FIX_LOG_ROUND2.md` are applied here.
> `building/source_snapshots/` is now **archive only** — do not edit snapshots
> directly; edit `src/` and update snapshots only when cutting a new milestone.
>
> **Round-3 follow-up fixes (2026-06-03):** `src/` is now editable-installable
> (`pip install -e src/` was previously broken by an invalid `build-backend` —
> `setuptools.backends.legacy:build` does not exist; fixed to `setuptools.build_meta`).
> Migrated three real, self-contained modules so the shipped surface has no dead
> imports: `config.py`, `core/data/base.py`, `core/scoring/registry.py` (the last
> two unblock `core/scoring/module_a|b|c.py`). Also fixed two silently-dead
> governance signals — see `core/governance/governance.py` (disagreement threshold
> no-op) and `core/pipeline.py` (fragility wrapper ignored its perturbed input) —
> with regression tests in `tests/test_review_followups_round2.py`.
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
| `core/portfolio/risk_engine.py` | P5_phase2_shadow | §1.4 sklearn bug, §三 EXTREME_CORR denominator, §4.1 rc_named ordering |
| `core/portfolio/sizing_optimizer.py` | P5_phase2_shadow | §1.3 mu→rolling mean, §2.1 E26/E12/E15 wired, §2.2 CVaR explicit, §4.2 fallback vol check |
| `pipeline.py` | P12_gate2_optimizer | §1.1 ConfidenceSpine, §1.2 dual-gross, leg_returns+liquidity_data threaded |
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
| `config.py` | local `.hermes` | round-3: migrated (loads `config/config.json`) |
| `core/data/base.py` | local `.hermes` | round-3: migrated (Field, SymbolSnapshot) |
| `core/scoring/registry.py` | local `.hermes` | round-3: migrated (unblocks module_a/b/c) |

---

## Still missing — must migrate from local `.hermes`

These modules are imported by `pipeline.py` but are **not in any snapshot** in this
repo (they were built in earlier phases and only exist in the local `.hermes`
installation). They must be copied here before `src/` can be installed and run
without the local package.

> Migrating `core/data/store.py` (+ its closure) is the next domino: it currently
> blocks `core/data/{adapters,crypto,market}.py` and `core/routing/leg_proxy.py`
> from importing; `core/data/flow.py` then unblocks the top-level `pipeline.py`.

| Import path | Notes |
|---|---|
| `.core.data.store` (`LocalStore`, `bootstrap_history`) | **next domino** — blocks adapters/crypto/market/leg_proxy |
| `.core.data.flow` (`basket_flow`, `money_flow_metrics`) | Phase 1 flow metrics |
| `.core.data.market` (`MarketData`) | Phase 0/1 market data loader |
| `.core.data.audit` (`write_audit_record`) | Phase 2 audit writer |
| `.core.data.quality` (`analyze_missing_fields`, `quality_from_snapshots`) | Phase 1 quality |
| `.core.backtest.posterior` (`escape_posterior_pnl`, `mirror_posterior_pnl`) | Phase 2 posterior PnL |
| `.core.features.regime` (`Regime`, `RegimeInput`, `classify_regime`) | Phase 2 regime |
| `.core.portfolio.risk_budget` (`compute_portfolio_risk`) | Legacy; to be deleted after full migration |
| `.core.portfolio.sizing` (`size_portfolio`) | Legacy fallback; to be deleted |
| `.core.decision.signal_journal` | Phase 2 signal journal |
| `.core.scoring.scorer` (`score_symbol`) | Phase 2 scoring |
| `.core.scoring.result` (`ScoreResult`) | Phase 2 scoring |
| `.core.routing.capital_routing` (`route_capital`) | Phase 2 routing |
| `.mirror.strategy` (`build_mirror_plan`) | Phase 2 mirror |
| `.mirror.store` (`write_mirror_snapshot`) | Phase 2 mirror |

**How to migrate:** `cp -r ~/.hermes/hermes_escape_top/core/data/base.py src/hermes_escape_top/core/data/base.py` (repeat for each). Run `pip install -e src/` after all modules are present.

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
