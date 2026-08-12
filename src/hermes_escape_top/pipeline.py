from __future__ import annotations

import hashlib
import json
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .config import CONFIG_PATH, load_config, resolve_path, trade_symbols
from .core.data.base import Field, SymbolSnapshot
from .core.data.decision_as_of import resolve_decision_as_of
from .core.data.flow import basket_flow, money_flow_metrics
from .core.data.flow_store import write_flow_snapshot
from .core.data.run_transaction import recover_incomplete_score_run, score_run_transaction
from .core.data.market import MarketData
from .core.data.audit import write_audit_record
from .core.data.quality import analyze_missing_fields, quality_from_snapshots
from .core.data.source_relevance import soft_record_decision_role
from .core.data.state_store import (
    latest_decision_statuses,
    latest_execution_confirmations,
    latest_score_payload_before,
    sync_execution_confirmations,
    write_state_snapshot,
)
from .core.data.store import LocalStore, bootstrap_history
from .core.data.adapters import build_soft_data, collect_soft_data, persist_soft_data_snapshot
from .core.data.sanitize import is_suspect_on
from .core.backtest.posterior import escape_posterior_pnl, mirror_posterior_pnl
from .core.features.regime import Regime, RegimeInput, classify_regime
from .core.portfolio.risk_budget import compute_portfolio_risk
from .core.portfolio.risk_engine import build_risk_state
from .core.portfolio.sizing_optimizer import optimize_targets
from .core.contracts import Verdict, ConfidenceState
from .core.confidence.spine import compute_confidence
from .core.routing.capital_routing import route_capital
from .core.routing.portfolio_routes import (
    apply_route_set_transition_buffer,
    route_leg_weights,
)
from .core.reentry.plan import build_reentry_plan
from .core.reentry.auto_confirm import infer_execution_confirmations
from .core.reentry.store import read_reentry_states, write_reentry_snapshot
from .core.decision.action_intents import build_action_context
from .core.decision.signal_journal import SignalJournalEntry, append_signal_journal, trading_days_since_last_sell
from .mirror.strategy import build_mirror_plan
from .mirror.store import write_mirror_snapshot
from .core.scoring.scorer import score_symbol
from .core.scoring.result import ScoreResult
from .core.safe_io import assert_pipeline_lease, pipeline_lock


PERSISTENCE_CHECKPOINTS = (
    "soft_adapter_snapshot",
    "reentry_state",
    "mirror_reference",
    "flow_reference",
    "execution_confirmations",
    "unified_state",
    "audit_log",
    "signal_journal",
)


def bootstrap() -> Dict[str, Any]:
    config = load_config()
    copied = bootstrap_history(config)
    return {"config_path": str(CONFIG_PATH), "copied_history": copied}


def empty_score_pipeline(as_of: str, config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    market = MarketData(config=config, store=store)
    snapshots: Dict[str, SymbolSnapshot] = {}
    scores: Dict[str, ScoreResult] = {}
    for symbol in trade_symbols(config):
        snap = market.snapshot(symbol, as_of)
        snapshots[symbol] = snap
        missing = analyze_missing_fields(snap.missing_fields(), 0.0, config)
        score = ScoreResult.empty(symbol, snap.as_of)
        score.missing_weight = missing.missing_weight
        score.confidence_missing_weight = missing.missing_weight
        score.confidence_missing_fields = missing.missing_fields
        score.blind_spot = missing.blind_spot
        score.final_score = missing.adjusted_score
        scores[symbol] = score
    quality = quality_from_snapshots(snapshots.values())
    portfolio_value = float(config.get("portfolio", {}).get("netliq", config.get("initial_capital", 100000.0)))
    payload = {
        "schema_version": "escape-top-greenfield-phase0-empty-v1",
        "as_of": as_of,
        "config_version": config["version"],
        "snapshots": {symbol: snap.to_dict() for symbol, snap in snapshots.items()},
        "scores": {symbol: score.to_dict() for symbol, score in scores.items()},
        "data_quality": quality.to_dict(),
        "all_source_data_quality": quality.to_dict(),
    }
    payload["input_hash"] = stable_hash(payload["snapshots"])
    return payload


def archive_soft_inputs(as_of: str, config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    store.ensure_dirs()
    day = date.fromisoformat(str(as_of)[:10])
    archives: Dict[str, str] = {}
    for name in ["enrichment_cache", "valuation_snapshot", "cboe_pcr"]:
        payload = {
            "schema_version": "escape-top-greenfield-dated-archive-v1",
            "name": name,
            "as_of": day.isoformat(),
            "source": "greenfield_seed",
            "data_available": False,
            "note": "Phase 1 starts dated archive accumulation; source adapter not yet wired.",
        }
        archives[name] = str(store.write_dated_snapshot(name, day, payload))
    return {"as_of": day.isoformat(), "archives": archives}


def soft_data_snapshot(as_of: str, config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    store.ensure_dirs()
    return collect_soft_data(as_of, config, store)


def flow_snapshot(as_of: str, config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    symbols = set(trade_symbols(config))
    for components in config.get("component_proxies", {}).values():
        symbols.update(components)
    histories = {symbol: store.load_history(symbol) for symbol in sorted(symbols)}
    return _flow_payload(config, histories, as_of)


def score_pipeline(
    as_of: str,
    config_path: Path = CONFIG_PATH,
    shadow: bool = False,
    include_ibkr: bool = True,
    run_type: str = "manual_rerun",
    market_admission_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one complete score transaction under the per-data-dir mutex."""
    config = load_config(config_path)
    lock_path = resolve_path(config, "archive_dir") / ".pipeline.lock"
    with pipeline_lock(blocking=True, timeout=600, path=lock_path) as lease:
        return _score_pipeline_locked(
            as_of,
            config_path=config_path,
            shadow=shadow,
            include_ibkr=include_ibkr,
            run_type=run_type,
            market_admission_status=market_admission_status,
            _lease=lease,
        )


def _score_pipeline_locked(
    as_of: str,
    config_path: Path = CONFIG_PATH,
    shadow: bool = False,
    include_ibkr: bool = True,
    run_type: str = "manual_rerun",
    market_admission_status: Optional[Dict[str, Any]] = None,
    *,
    _lease: Any,
) -> Dict[str, Any]:
    # run_type tags WHO triggered this run so the WebUI can tell the official
    # daily run ("scheduled") from an ad-hoc intraday re-run ("manual_rerun").
    # The 2026-06-11 incident: a verification re-run wrote a (contaminated)
    # EXIT into the audit log and the UI showed it as "today's advice" because
    # the UI just took the latest record. With this tag the UI pins the latest
    # SCHEDULED run as official and shows manual re-runs as non-official preview.
    config = load_config(config_path)
    as_of = resolve_decision_as_of(as_of, config)
    assert_pipeline_lease(
        _lease,
        path=resolve_path(config, "archive_dir") / ".pipeline.lock",
    )
    recovery = recover_incomplete_score_run(resolve_path(config, "archive_dir"), _lease=_lease)
    store = LocalStore(config)
    market = MarketData(config=config, store=store)
    symbols = _snapshot_universe(config)
    snapshots = {symbol: market.snapshot(symbol, as_of) for symbol in symbols}
    histories = {symbol: market.load_history(symbol) for symbol in symbols}
    # PIT guard: a backdated run (as_of < latest bar) must not see future bars
    # — same semantics as run_full._truncate_histories. No-op for live runs
    # where as_of is already the newest bar.
    _cutoff = pd.Timestamp(str(as_of)[:10])
    histories = {
        symbol: (frame.loc[frame.index <= _cutoff] if frame is not None and not getattr(frame, "empty", True) else frame)
        for symbol, frame in histories.items()
    }
    soft_data = build_soft_data(as_of, config, store)
    snapshots["SOFT"] = _soft_snapshot(soft_data, as_of)
    regime, regime_meta = _current_regime(snapshots, histories, as_of)
    sanitize_cfg = config.get("sanitize", {})
    # Suspect-bar hard-valve guard (F3): only run sanitize / pass suspect when the
    # flag is on, so the default path is byte-identical and never delays a valve.
    suspect_guard_on = bool(config.get("features", {}).get("use_suspect_valve_guard", False))
    suspect_flags = (
        {symbol: is_suspect_on(histories.get(symbol), as_of, sanitize_cfg) for symbol in trade_symbols(config)}
        if suspect_guard_on
        else {}
    )
    # Decision stabilizer (F1+F2): only read prior statuses when enabled, so the
    # default path takes no extra DB read and is byte-identical. Either sub-flag
    # (hysteresis / confirmation) also needs the prior status.
    _sf = config.get("features", {})
    stabilizer_on = bool(_sf.get("use_decision_stabilizer", False) or _sf.get("use_status_hysteresis", False) or _sf.get("use_close_confirmation", False))
    previous_statuses = (
        latest_decision_statuses(store.archive_dir / "hermes_state.sqlite") if stabilizer_on else {}
    )
    bundles = {
        symbol: score_symbol(
            symbol,
            snapshots,
            config,
            regime=regime,
            histories=histories,
            suspect=suspect_flags.get(symbol, False),
            previous_status=previous_statuses.get(symbol),
        )
        for symbol in trade_symbols(config)
    }
    target_weights = _target_weights_after_verdict(config, bundles)
    hard_excluded = {symbol for symbol, bundle in bundles.items() if bundle.result.hard_valve_hits or bundle.result.sell_fraction >= 1.0}
    portfolio_risk = compute_portfolio_risk(histories, target_weights, config, excluded_symbols=hard_excluded)
    signal_journal_path = store.archive_dir / "signal_journal.jsonl"
    signal_journal_write_path = _signal_journal_write_path(store, shadow)
    state_db_path = store.archive_dir / "hermes_state.sqlite"
    sizing, sizing_extras = _optimize_sizing(bundles, histories, portfolio_risk, config, as_of=as_of,
                                             signal_journal_path=signal_journal_path)
    routing = {symbol: route_capital(symbol, bundle.result, config, snapshots=snapshots, histories=histories) for symbol, bundle in bundles.items()}
    route_transition = None
    portfolio_target_weights = None
    if bool(config.get("features", {}).get("use_route_set_transition_buffer", False)):
        sizing_dict = {symbol: decision.to_dict() for symbol, decision in sizing.items()}
        routing_dict = {symbol: decision.to_dict() for symbol, decision in routing.items()}
        raw_route_weights = route_leg_weights(config, sizing_dict, routing_dict)
        previous_payload = latest_score_payload_before(state_db_path, as_of)
        previous_route_weights = None
        if previous_payload:
            previous_route_weights = previous_payload.get("portfolio_target_weights")
            if not previous_route_weights:
                previous_route_weights = route_leg_weights(
                    config,
                    previous_payload.get("sizing") or {},
                    previous_payload.get("routing") or {},
                )
        route_transition = apply_route_set_transition_buffer(
            config,
            raw_route_weights,
            previous_route_weights,
        )
        portfolio_target_weights = route_transition.weights
    reentry_db_path = store.archive_dir / "reentry_state.sqlite"
    reentry_states = read_reentry_states(reentry_db_path)
    execution_confirmations = latest_execution_confirmations(state_db_path)
    reentry = {
        symbol: build_reentry_plan(
            symbol,
            bundle.result,
            snapshots,
            histories,
            config,
            days_since_last_sell=trading_days_since_last_sell(signal_journal_path, symbol, as_of),
            t1_active=bool(reentry_states.get(symbol).t1_active) if reentry_states.get(symbol) else False,
            t2_active=bool(reentry_states.get(symbol).t2_active) if reentry_states.get(symbol) else False,
        )
        for symbol, bundle in bundles.items()
    }
    artifacts = _score_persistence_artifacts(store, shadow, as_of)
    with score_run_transaction(
        store.archive_dir,
        artifacts,
        metadata={
            "as_of": str(as_of)[:10],
            "run_type": str(run_type),
            "shadow": bool(shadow),
            "include_ibkr": bool(include_ibkr),
        },
        _lease=_lease,
    ) as persistence:
        persist_soft_data_snapshot(soft_data, store)
        _persistence_checkpoint("soft_adapter_snapshot")
        reentry_db = write_reentry_snapshot(reentry_db_path, str(as_of)[:10], reentry, reentry_states)
        _persistence_checkpoint("reentry_state")
        mirror = build_mirror_plan(snapshots, config, histories=histories, as_of=as_of)
        mirror_db = write_mirror_snapshot(store.archive_dir / "mirror_reference.sqlite", str(as_of)[:10], mirror)
        _persistence_checkpoint("mirror_reference")
        flow = _flow_payload(config, histories, as_of)
        flow_db = write_flow_snapshot(store.archive_dir / "flow_reference.sqlite", flow)
        flow["db_path"] = str(flow_db)
        _persistence_checkpoint("flow_reference")
        ibkr_payload = _ibkr_payload(
            config,
            sizing,
            routing,
            portfolio_target_weights=portfolio_target_weights,
        ) if include_ibkr else {
            "source": "disabled",
            "note": "IBKR disabled for offline replay/backtest.",
        }
        execution_sync = _execution_sync(config, state_db_path, reentry, ibkr_payload, as_of, include_ibkr)
        _persistence_checkpoint("execution_confirmations")
        execution_confirmations = execution_sync.get("latest_confirmations") or execution_confirmations
        portfolio_value = _portfolio_value(config, ibkr_payload)
        escape_pnl = escape_posterior_pnl(
            {symbol: decision.to_dict() for symbol, decision in sizing.items()},
            histories,
            as_of,
            portfolio_value=portfolio_value,
        )
        mirror_pnl = mirror_posterior_pnl(mirror, histories, as_of, portfolio_value=portfolio_value)
        decision_quality, all_source_quality = _quality_payloads(snapshots, soft_data, config)
        payload = {
            "schema_version": "escape-top-greenfield-phase3-score-v1",
            "as_of": as_of,
            "run_type": str(run_type),
            "run_ts": datetime.now(timezone.utc).isoformat(),
            "config_version": config["version"],
            "persistence": {
                "run_id": persistence.run_id,
                "protocol": "recoverable-journal-v1",
                "recovered_run_id": (recovery or {}).get("run_id"),
            },
            "snapshots": {symbol: snap.to_dict() for symbol, snap in sorted(snapshots.items())},
            "scores": {symbol: bundle.result.to_dict() for symbol, bundle in sorted(bundles.items())},
            "regime": regime_meta,
            "portfolio_risk": portfolio_risk.to_dict(),
            "confidence_spine": sizing_extras.get("confidence_spine") or {},
            "risk_contributions": sizing_extras.get("risk_contributions") or {},
            "stress_scenarios": sizing_extras.get("stress_scenarios") or [],
            "routing_context": _routing_context(bundles, snapshots, histories, config),
            "sizing": {symbol: decision.to_dict() for symbol, decision in sorted(sizing.items())},
            "routing": {symbol: decision.to_dict() for symbol, decision in sorted(routing.items())},
            "reentry": {symbol: plan.to_dict() for symbol, plan in sorted(reentry.items())},
            "reentry_state": {
                "db_path": str(reentry_db),
                "states": {symbol: state.to_dict() for symbol, state in sorted(reentry_states.items())},
                "execution_confirmations": execution_confirmations,
                "execution_sync": execution_sync,
            },
            "execution_sync": execution_sync,
            "soft_data": soft_data,
            "flow": flow,
            "mirror": {
                "db_path": str(mirror_db),
                "decisions": {sleeve: decision.to_dict() for sleeve, decision in sorted(mirror.items())},
            },
            "posterior_pnl": {
                "portfolio_value": portfolio_value,
                "escape": {symbol: row.to_dict() for symbol, row in sorted(escape_pnl.items())},
                "mirror": {sleeve: row.to_dict() for sleeve, row in sorted(mirror_pnl.items())},
            },
            "data_quality": decision_quality,
            "all_source_data_quality": all_source_quality,
            "ibkr": ibkr_payload,
        }
        if market_admission_status is not None:
            payload["market_admission_status"] = dict(market_admission_status)
        if portfolio_target_weights is not None and route_transition is not None:
            payload["portfolio_target_weights"] = portfolio_target_weights
            payload["route_transition"] = route_transition.to_dict()
        payload["input_hash"] = stable_hash(payload["snapshots"])
        payload["data_quality_breakdown"] = _quality_breakdown(payload, snapshots, flow, config)
        payload.update(build_action_context(payload, snapshots))
        payload["state"] = write_state_snapshot(state_db_path, payload, retention=config.get("state_retention"))
        _persistence_checkpoint("unified_state")

        audit_path = write_audit_record(payload, _audit_write_dir(store, shadow))
        _persistence_checkpoint("audit_log")
        signal_path = append_signal_journal(
            signal_journal_write_path,
            [
                SignalJournalEntry(
                    as_of=str(as_of)[:10],
                    symbol=symbol,
                    status=bundle.result.status,
                    final_score=bundle.result.final_score,
                    hard_valves=bundle.result.hard_valve_hits,
                    regime=regime.value,
                )
                for symbol, bundle in sorted(bundles.items())
            ],
        )
        _persistence_checkpoint("signal_journal")
        payload["audit_log_path"] = str(audit_path)
        payload["signal_journal_path"] = str(signal_path)

    return payload


def _signal_journal_write_path(store: LocalStore, shadow: bool) -> Path:
    if not shadow:
        return store.archive_dir / "signal_journal.jsonl"
    path = store.archive_dir.parent / "shadow" / "signal_journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _audit_write_dir(store: LocalStore, shadow: bool) -> Path:
    if not shadow:
        return store.archive_dir
    path = store.archive_dir.parent / "shadow" / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _score_persistence_artifacts(
    store: LocalStore,
    shadow: bool,
    as_of: str,
) -> tuple[Path, ...]:
    return (
        store.archive_path("soft_adapter_snapshot", str(as_of)[:10]),
        store.archive_dir / "reentry_state.sqlite",
        store.archive_dir / "mirror_reference.sqlite",
        store.archive_dir / "flow_reference.sqlite",
        store.archive_dir / "hermes_state.sqlite",
        _audit_write_dir(store, shadow) / "audit_log.jsonl",
        _signal_journal_write_path(store, shadow),
    )


def _persistence_checkpoint(name: str) -> None:
    """Internal fault-injection seam; production execution is intentionally a no-op."""
    if name not in PERSISTENCE_CHECKPOINTS:
        raise ValueError(f"unknown persistence checkpoint: {name}")


def _flow_payload(config: Dict[str, Any], histories: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    symbol_rows = {
        symbol: money_flow_metrics(symbol, histories.get(symbol, pd.DataFrame()), as_of).to_dict()
        for symbol in trade_symbols(config)
    }
    component_rows = {}
    for symbol, components in config.get("component_proxies", {}).items():
        component_rows[symbol] = basket_flow(
            components,
            {component: histories.get(component, pd.DataFrame()) for component in components},
            as_of,
        )
    return {
        "schema_version": "escape-top-greenfield-flow-v2-v1",
        "as_of": as_of,
        "symbols": symbol_rows,
        "component_baskets": component_rows,
    }


def _ibkr_payload(
    config: Dict[str, Any],
    sizing: Dict[str, Any],
    routing: Dict[str, Any],
    *,
    portfolio_target_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    if not config.get("ibkr", {}).get("enabled", False):
        return {"source": "disabled", "note": "set ibkr.enabled=true to activate"}
    try:
        from hermes_escape_top.ibkr.positions import read_positions
        from hermes_escape_top.ibkr.reconcile import reconcile as ibkr_reconcile

        snap = read_positions(config)
        sizing_for_recon = {s: d.to_dict() for s, d in sizing.items()}
        routing_for_recon = {s: d.to_dict() for s, d in routing.items()}
        return ibkr_reconcile(
            snap,
            sizing_for_recon,
            routing_for_recon,
            portfolio_target_weights=portfolio_target_weights,
        ).to_dict()
    except Exception as exc:
        return {"error": str(exc), "source": "unavailable"}


def _execution_sync(
    config: Dict[str, Any],
    state_db_path: Path,
    reentry: Dict[str, Any],
    ibkr_payload: Dict[str, Any],
    as_of: str,
    include_ibkr: bool,
) -> Dict[str, Any]:
    latest = latest_execution_confirmations(state_db_path)
    exec_cfg = config.get("ibkr", {}).get("executions", {})
    if not include_ibkr:
        return {"status": "SKIPPED", "reason": "include_ibkr=false", "latest_confirmations": latest}
    if not config.get("ibkr", {}).get("enabled", False):
        return {"status": "DISABLED", "reason": "ibkr.enabled=false", "latest_confirmations": latest}
    if isinstance(exec_cfg, dict) and not bool(exec_cfg.get("enabled", True)):
        return {"status": "DISABLED", "reason": "ibkr.executions.enabled=false", "latest_confirmations": latest}
    if ibkr_payload.get("source") != "tws":
        return {
            "status": "DEGRADED",
            "reason": f"IBKR positions source is {ibkr_payload.get('source', 'unknown')}; executions not trusted for auto-confirm.",
            "latest_confirmations": latest,
        }
    if not ibkr_payload.get("sync_time"):
        return {
            "status": "SKIPPED",
            "reason": "IBKR live payload lacks sync_time; likely a mocked or incomplete live snapshot.",
            "latest_confirmations": latest,
        }
    try:
        from hermes_escape_top.ibkr.executions import read_executions

        snapshot = read_executions(config).to_dict()
        allowed_sources = set((exec_cfg or {}).get("auto_confirm_sources", ["tws"]) if isinstance(exec_cfg, dict) else ["tws"])
        plan_payload = {symbol: plan.to_dict() for symbol, plan in reentry.items()}
        inferred = infer_execution_confirmations(
            snapshot,
            plan_payload,
            as_of=as_of,
            lookback_days=int((exec_cfg or {}).get("auto_confirm_lookback_days", 7)) if isinstance(exec_cfg, dict) else 7,
        )
        if snapshot.get("source") not in allowed_sources:
            return {
                "status": "DEGRADED",
                "reason": f"executions source {snapshot.get('source')} not in auto_confirm_sources",
                "executions": _execution_snapshot_summary(snapshot),
                "inferred": inferred,
                "latest_confirmations": latest,
            }
        sync = sync_execution_confirmations(
            state_db_path,
            inferred,
            retention=config.get("state_retention"),
        )
        latest = latest_execution_confirmations(state_db_path)
        return {
            "status": "OK" if inferred else "NO_MATCH",
            "executions": _execution_snapshot_summary(snapshot),
            "inferred": inferred,
            "inserted": sync.get("inserted", []),
            "skipped": sync.get("skipped", []),
            "inserted_count": sync.get("inserted_count", 0),
            "skipped_count": sync.get("skipped_count", 0),
            "latest_confirmations": latest,
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "reason": str(exc),
            "latest_confirmations": latest,
        }


def _execution_snapshot_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": snapshot.get("source"),
        "sync_time": snapshot.get("sync_time"),
        "record_count": len(snapshot.get("records") or []),
        "lookback_days": snapshot.get("lookback_days"),
        "snapshot_stale": bool(snapshot.get("snapshot_stale")),
        "snapshot_age_seconds": snapshot.get("snapshot_age_seconds"),
        "client_id": snapshot.get("client_id"),
        "error": snapshot.get("error"),
    }


def _portfolio_value(config: Dict[str, Any], ibkr_payload: Dict[str, Any]) -> float:
    try:
        net_liq = float(ibkr_payload.get("net_liq", 0.0) or 0.0)
    except (TypeError, ValueError):
        net_liq = 0.0
    if net_liq > 0:
        return net_liq
    return float(config.get("portfolio", {}).get("netliq", config.get("initial_capital", 100000.0)))


def _quality_breakdown(
    payload: Dict[str, Any],
    snapshots: Dict[str, SymbolSnapshot],
    flow: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    dq = payload.get("data_quality") or {}
    all_source_dq = payload.get("all_source_data_quality") or dq
    sources = []
    price_stale = []
    for symbol in ["MSTR", "FNGU", "SOXL", "QQQ", "SOXX", "SPY", "^VIX"]:
        snap = snapshots.get(symbol)
        if not snap:
            continue
        close = snap.fields.get("close")
        as_of = close.as_of.isoformat() if close and close.as_of else snap.as_of.isoformat()
        latency = close.latency_days if close else 0
        status = "FRESH" if latency == 0 else "STALE"
        if latency:
            price_stale.append(symbol)
        sources.append({
            "name": symbol,
            "category": "price",
            "as_of": as_of,
            "status": status,
            "is_proxy": False,
            "latency_days": latency,
            "quality_penalty": 0.0,
        })
    soft_proxy = 0
    soft_latency = 0
    for name, record in sorted(((payload.get("soft_data") or {}).get("records") or {}).items()):
        is_proxy = bool(record.get("is_proxy"))
        latency = int(record.get("latency_days") or 0)
        available = bool(record.get("data_available"))
        decision_role = soft_record_decision_role(config, name)
        soft_proxy += int(is_proxy)
        soft_latency += int(latency > 0)
        sources.append({
            "name": name,
            "category": "soft",
            "as_of": record.get("as_of"),
            "status": "AVAILABLE" if available else "MISSING",
            "is_proxy": is_proxy,
            "latency_days": latency,
            "quality_penalty": record.get("quality_penalty", 0.0),
            "reason": record.get("reason", ""),
            "decision_role": decision_role,
            "decision_bearing": decision_role in {"strategy", "hard_gate"},
        })
    flow_stale = []
    for sleeve, row in sorted((flow.get("component_baskets") or {}).items()):
        stale_days = row.get("component_max_stale_days")
        if stale_days:
            flow_stale.append(sleeve)
        sources.append({
            "name": f"{sleeve}_component_flow",
            "category": "flow",
            "as_of": row.get("component_min_as_of") or flow.get("as_of"),
            "status": row.get("severity", "MISSING"),
            "is_proxy": True,
            "latency_days": stale_days,
            "quality_penalty": 2.0 if row.get("available") else 5.0,
            "stale_components": row.get("stale_components") or [],
        })
    ibkr = payload.get("ibkr") or {}
    sources.append({
        "name": "IBKR",
        "category": "broker",
        "as_of": ibkr.get("sync_time"),
        "status": ibkr.get("source", "disabled"),
        "is_proxy": ibkr.get("source") == "snapshot",
        "latency_days": None,
        "quality_penalty": 5.0 if ibkr.get("snapshot_stale") else 0.0,
        "error": ibkr.get("error"),
    })
    upgrade = []
    if soft_proxy:
        upgrade.append(f"替换 {soft_proxy} 个软数据代理源")
    if soft_latency:
        upgrade.append(f"降低 {soft_latency} 个软数据延迟源")
    if flow_stale:
        upgrade.append("刷新底层资金流: " + ", ".join(flow_stale))
    if ibkr.get("snapshot_stale") or ibkr.get("source") == "snapshot":
        upgrade.append("恢复 IBKR live 快照，避免 stale snapshot")
    if price_stale:
        upgrade.append("刷新价格历史: " + ", ".join(price_stale))
    return {
        "level": all_source_dq.get("level"),
        "overall_score": all_source_dq.get("overall_score"),
        "strategy_level": dq.get("level"),
        "strategy_overall_score": dq.get("overall_score"),
        "components": {
            "price_fresh": not price_stale,
            "soft_proxy_count": soft_proxy,
            "soft_latency_count": soft_latency,
            "flow_fresh": not flow_stale,
            "ibkr_source": ibkr.get("source", "disabled"),
            "ibkr_stale": bool(ibkr.get("snapshot_stale")),
        },
        "upgrade_to_high": upgrade or ["当前无明显数据质量阻塞"],
        "sources": sources,
    }


def _data_confidence(bundles: Dict[str, Any], config: Dict[str, Any]) -> float:
    """Data-quality confidence in [floor, 1.0] from the scores' missing_weight.

    This is where the "缺数据 ≠ 安全" red line is enforced for the confidence
    spine: more missing soft data → lower confidence → smaller positions.
    """
    gate = float(config.get("scoring", {}).get("blind_spot_gate", 30.0))
    floor = float(config.get("confidence", {}).get("data_conf_floor", 0.3))
    weights = []
    for bundle in bundles.values():
        mw = getattr(bundle.result, "confidence_missing_weight", None)
        if mw is None:
            mw = getattr(bundle.result, "missing_weight", None)
        if mw is not None:
            weights.append(float(mw))
    if not weights or gate <= 0:
        return 1.0
    mean_missing = sum(weights) / len(weights)
    return max(floor, min(1.0, 1.0 - mean_missing / gate))


def _max_staleness_days(
    histories: Dict[str, Any],
    config: Dict[str, Any],
    as_of: Optional[str],
) -> Optional[float]:
    """Worst (largest) staleness across trade symbols: as_of minus newest bar."""
    if as_of is None:
        return None
    try:
        ref = pd.Timestamp(str(as_of)[:10])
    except Exception:
        return None
    trade = set(trade_symbols(config))
    worst: Optional[float] = None
    for symbol, hist in histories.items():
        if symbol not in trade or hist is None or getattr(hist, "empty", True):
            continue
        idx = hist.index
        if len(idx) == 0:
            continue
        try:
            last = pd.Timestamp(idx[-1])
        except Exception:
            continue
        days = max(0.0, (ref - last).days)
        worst = days if worst is None else max(worst, days)
    return worst


def _drift_state(signal_journal_path: Any, config: Dict[str, Any]) -> Dict[str, Any]:
    """Real score-distribution drift (PSI) from the signal journal.

    Compares the recent score distribution (last `live_days` distinct dates) to
    the historical baseline (everything before that window). This is the genuine
    drift signal the ConfidenceSpine expects — not a placeholder. Falls back to a
    no-alert state when there is not enough history to compute a stable PSI
    (compute_psi needs >=10 samples per side), which is the truthful "cannot
    assess drift yet" outcome rather than a fabricated alert.
    """
    healthy = {"psi": 0.0, "alert": False}
    try:
        from .core.monitor.drift import DriftMonitor
        import json as _json
        from pathlib import Path as _Path

        path = _Path(str(signal_journal_path))
        if not path.exists():
            return healthy
        live_days = int(config.get("confidence", {}).get("drift_live_days", 10))
        by_date: Dict[str, list] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
                score = float(rec["final_score"])
            except (ValueError, KeyError, TypeError):
                continue
            by_date.setdefault(str(rec.get("as_of", "")), []).append(score)
        dates = sorted(d for d in by_date if d)
        if len(dates) < 4:
            return healthy
        live_dates = set(dates[-live_days:])
        live = [s for d in live_dates for s in by_date[d]]
        train = [s for d in dates if d not in live_dates for s in by_date[d]]
        if len(train) < 10 or len(live) < 10:
            return healthy
        cfg = {
            "psi_threshold": float(config.get("confidence", {}).get("drift_psi_threshold", 0.25)),
        }
        state = DriftMonitor(cfg).evaluate(np.asarray(train, dtype=float), np.asarray(live, dtype=float))
        return {"psi": float(state.get("psi", 0.0)), "alert": bool(state.get("alert", False))}
    except Exception:
        return healthy


def _risk_engine_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy portfolio keys into RiskEngine's current schema."""
    port_cfg = dict(config.get("portfolio", {}))
    risk_cfg = dict(config.get("risk_engine", {}))
    risk_cfg.update(port_cfg)

    corr_pct = port_cfg.get("corr_regime_pct", {})
    if "corr_regime_extreme_ratio" not in risk_cfg:
        risk_cfg["corr_regime_extreme_ratio"] = risk_cfg.get(
            "corr_regime_extreme_pctl",
            corr_pct.get("extreme", 110),
        )
    if "corr_regime_elevated_ratio" not in risk_cfg:
        risk_cfg["corr_regime_elevated_ratio"] = risk_cfg.get(
            "corr_regime_elevated_pctl",
            corr_pct.get("elevated", 80),
        )
    risk_cfg.setdefault("extreme_corr_penalty", 0.90)
    risk_cfg.setdefault("vol_budget_annual", 0.35)
    risk_cfg.setdefault("min_periods", 40)
    risk_cfg.setdefault("ewma_lambda", 0.94)
    risk_cfg.setdefault("cvar_alpha", 0.95)
    risk_cfg.setdefault("cvar_budget", 0.08)
    return risk_cfg


def _sizing_optimizer_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize SizingOptimizer config, including legacy flat fields."""
    raw = dict(config.get("sizing", {}))
    sizing_cfg = {
        "dd_aversion": float(raw.get("dd_aversion", 3.0)),
        "leverage_L": raw.get("leverage_L", {"FNGU": 3, "SOXL": 3, "MSTR": 1}),
        "solver": raw.get("solver", "slsqp_or_grid"),
        "exec_slices": int(raw.get("exec_slices", 3)),
        "mu_mode": raw.get("mu_mode", "proxy"),
    }

    kelly = dict(raw.get("kelly", {}))
    kelly.setdefault("enabled", False)
    if "kelly_fraction" in raw:
        kelly.setdefault("frac", raw["kelly_fraction"])
    sizing_cfg["kelly"] = kelly

    liquidity = dict(raw.get("liquidity", {}))
    liquidity.setdefault("max_liquidation_days", raw.get("max_liquidation_days", 3))
    liquidity.setdefault("participation_rate", raw.get("participation_rate", 0.10))
    sizing_cfg["liquidity"] = liquidity

    if "cppi" in raw:
        sizing_cfg["cppi"] = raw["cppi"]
    return sizing_cfg


def _optimize_sizing(
    bundles: Dict[str, Any],
    histories: Dict[str, Any],
    portfolio_risk: Any,
    config: Dict[str, Any],
    as_of: Optional[str] = None,
    signal_journal_path: Any = None,
) -> Dict[str, Any]:
    """Replace the old scaler multiplication chain with SizingOptimizer (Gate 2).

    Maps ScoreResult bundles → Verdict contracts → optimize_targets → sizing dict.
    Output is a dict keyed by symbol, each value has a to_dict() method for
    backward compatibility with posterior_pnl and audit serialization.
    """
    from .core.portfolio.sizing import size_portfolio  # fallback reference

    # ── Build Verdicts from ScoreResults ──────────────────────────────────────
    verdicts: Dict[str, Verdict] = {}
    for symbol, bundle in bundles.items():
        result = bundle.result
        cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        sell_frac = float(result.sell_fraction)
        verdicts[symbol] = Verdict(
            symbol=symbol,
            status=str(result.status),
            rule_target_weight=max(0.0, cap * (1.0 - sell_frac)),
            sell_fraction=sell_frac,
            hard_valve_hits=list(result.hard_valve_hits),
        )

    # ── Build RiskState from RiskEngine ───────────────────────────────────────
    leg_returns = {}
    for symbol, hist in histories.items():
        if hist is not None and not hist.empty:
            close = hist["Close"] if "Close" in hist.columns else hist.iloc[:, 0]
            leg_returns[symbol] = close.pct_change(fill_method=None).dropna()

    # ── E12 liquidity data from histories ─────────────────────────────────────
    netliq = float(config.get("portfolio", {}).get("netliq", 100_000.0))
    liquidity_data: dict = {}
    for symbol, hist in histories.items():
        if hist is None or hist.empty:
            continue
        close_col = "Close" if "Close" in hist.columns else hist.columns[0]
        price_series = hist[close_col].dropna()
        if price_series.empty:
            continue
        price = float(price_series.iloc[-1])
        if "Volume" in hist.columns:
            vol_series = hist["Volume"].dropna().tail(20)
            adv20_shares = float(vol_series.mean()) if len(vol_series) >= 5 else float("inf")
            adv20_notional = adv20_shares * price if len(vol_series) >= 5 else float("inf")
        else:
            adv20_shares = float("inf")
            adv20_notional = float("inf")
        liquidity_data[symbol] = {
            "adv20_shares": adv20_shares,
            "adv20_notional": adv20_notional,
            "price": price,
            "netliq": netliq,
        }

    optimizer_cfg = {
        "risk_engine": _risk_engine_config(config),
        "sizing": _sizing_optimizer_config(config),
    }

    risk_state = build_risk_state(
        {s: leg_returns[s] for s in verdicts if s in leg_returns},
        {s: v.rule_target_weight for s, v in verdicts.items()},
        None,
        optimizer_cfg,
    )

    # ── Build ConfidenceState via ConfidenceSpine (Gate ④) ───────────────────
    # Inputs MUST come from real signal sources, not from portfolio_risk (which
    # has none of these attributes — reading them via getattr silently yields
    # None → spine collapses to 0.5 → permanent DEGRADED). Compute what we have;
    # pass truthful "healthy" states for monitors that ran clean.
    confidence = compute_confidence(
        data_conf=_data_confidence(bundles, config),
        # No multi-source failover is wired into the data adapters (collect_soft_data
        # does not use FailoverSource), so there is no degradation signal to read —
        # "not degraded" is the truthful state, not a placeholder. Wire this once the
        # data layer routes through FailoverSource and exposes is_degraded.
        failover_state={"is_degraded": False},
        staleness_days=_max_staleness_days(histories, config, as_of),
        drift_state=_drift_state(signal_journal_path, config),   # real PSI from signal journal
        fragility=_spine_fragility(bundles, config) if _spine_full(config) else 0.0,
        disagreement=_spine_disagreement(verdicts, config) if _spine_full(config) else 0.0,
        cfg=config.get("confidence", {}),
    )

    # ── Run optimizer ─────────────────────────────────────────────────────────
    try:
        opt_decision = optimize_targets(
            verdicts,
            risk_state,
            confidence,
            optimizer_cfg,
            leg_returns=leg_returns,
            liquidity_data=liquidity_data,
        )
    except Exception as exc:
        warnings.warn(
            f"SizingOptimizer failed; falling back to legacy size_portfolio: {exc!r}",
            RuntimeWarning,
            stacklevel=2,
        )
        fallback = size_portfolio(
            histories,
            {symbol: bundle.result for symbol, bundle in bundles.items()},
            config,
            gross_scaler=portfolio_risk.effective_gross_scaler,
        )
        for decision in fallback.values():
            explain = getattr(decision, "explain", None)
            if isinstance(explain, list):
                explain.append(f"optimizer_fallback={exc!r}")
        return fallback, {"confidence_spine": _confidence_spine_dict(confidence)}

    # ── Wrap into backward-compatible SizingProxy dicts ───────────────────────
    result: Dict[str, Any] = {}
    for symbol, bundle in bundles.items():
        result_obj = bundle.result
        cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        old_ref = max(0.0, cap * (1.0 - float(result_obj.sell_fraction)))
        new_target = float(opt_decision.target_weights.get(symbol, 0.0))
        binding = opt_decision.binding_constraint.get(symbol, "NONE")

        exec_plan = [p for p in opt_decision.execution_plan if p.get("symbol") == symbol]
        exec_mode = exec_plan[0].get("mode", "twap_3_slices") if exec_plan else "twap_3_slices"

        result[symbol] = _SizingProxy(
            symbol=symbol,
            sleeve_cap=cap,
            sell_fraction=float(result_obj.sell_fraction),
            reference_target_weight=old_ref,
            # Report the RiskEngine gross (single risk source, Gate ①).
            vol_scaler=float(risk_state.gross_scaler),
            gross_scaler=float(risk_state.gross_scaler),
            target_weight=new_target,
            clamp_applied=new_target < old_ref - 1e-9,
            binding_constraint=binding,
            execution_mode=exec_mode,
            optimizer_confidence=float(opt_decision.confidence_applied),
            explain=opt_decision.notes + [f"optimizer binding={binding}"],
        )
    extras = {
        "confidence_spine": _confidence_spine_dict(confidence),
        "risk_contributions": _risk_contribution_block(risk_state, dict(opt_decision.target_weights or {})),
        "stress_scenarios": _stress_block(risk_state, dict(opt_decision.target_weights or {}), histories),
    }
    return result, extras


class _SizingProxy:
    """Backward-compatible wrapper around optimizer output.

    Preserves target_weight and to_dict() keys used by posterior_pnl and audit.
    """

    def __init__(
        self,
        symbol: str,
        sleeve_cap: float,
        sell_fraction: float,
        reference_target_weight: float,
        vol_scaler: float,
        gross_scaler: float,
        target_weight: float,
        clamp_applied: bool,
        binding_constraint: str,
        execution_mode: str,
        optimizer_confidence: float,
        explain: list,
    ) -> None:
        self.symbol = symbol
        self.sleeve_cap = sleeve_cap
        self.sell_fraction = sell_fraction
        self.reference_target_weight = reference_target_weight
        self.vol_scaler = vol_scaler
        self.gross_scaler = gross_scaler
        self.target_weight = target_weight
        self.clamp_applied = clamp_applied
        self.binding_constraint = binding_constraint
        self.execution_mode = execution_mode
        self.optimizer_confidence = optimizer_confidence
        self.explain = explain

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sleeve_cap": round(self.sleeve_cap, 6),
            "sell_fraction": round(self.sell_fraction, 6),
            "reference_target_weight": round(self.reference_target_weight, 6),
            "vol_scaler": round(self.vol_scaler, 6),
            "gross_scaler": round(self.gross_scaler, 6),
            "target_weight": round(self.target_weight, 6),
            "clamp_applied": self.clamp_applied,
            "binding_constraint": self.binding_constraint,
            "execution_mode": self.execution_mode,
            "optimizer_confidence": round(self.optimizer_confidence, 6),
            "explain": self.explain,
            # Gate 2 marker — single sizing entry point
            "sizing_engine": "optimize_targets_v1",
        }


def _snapshot_universe(config: Dict[str, Any]) -> list[str]:
    symbols = set(trade_symbols(config))
    symbols.update(config.get("market_symbols", []))
    for values in config.get("radars", {}).values():
        symbols.update(values)
    for values in config.get("component_proxies", {}).values():
        symbols.update(values)
    routing = config.get("routing", {})
    defcon1 = routing.get("defcon1") or {}
    for symbol, weight in defcon1.items():
        if symbol != "TREND" and symbol != "trend_symbol" and isinstance(weight, (int, float)):
            symbols.add(symbol)
    trend_symbol = defcon1.get("trend_symbol")
    if trend_symbol:
        symbols.add(trend_symbol)
    for key in ["primary", "fallback"]:
        value = (routing.get("defcon2") or {}).get(key)
        if value:
            symbols.add(value)
    symbols.update((routing.get("defcon3") or {}).values())
    return sorted(symbols)


def _current_regime(
    snapshots: Dict[str, SymbolSnapshot],
    histories: Dict[str, Any],
    as_of: str,
) -> tuple[Regime, Dict[str, Any]]:
    vix_pct = _history_percentile(histories.get("^VIX"), as_of)
    vix = _snapshot_value(snapshots, "^VIX", "close")
    vix3m = _snapshot_value(snapshots, "^VIX3M", "close")
    term_ratio = vix / vix3m if vix is not None and vix3m not in (None, 0.0) else None
    inputs = RegimeInput(
        close=_snapshot_value(snapshots, "QQQ", "close"),
        ema20=_snapshot_value(snapshots, "QQQ", "ema20"),
        ema50=_snapshot_value(snapshots, "QQQ", "ema50"),
        ma200=_snapshot_value(snapshots, "QQQ", "ma200"),
        vix_percentile=vix_pct,
        vix_term_ratio=term_ratio,
    )
    regime = classify_regime(inputs)
    return regime, {
        "current": regime.value,
        "radar": "QQQ",
        "vix_percentile": round(vix_pct, 4) if vix_pct is not None else None,
        "vix_term_ratio": round(term_ratio, 6) if term_ratio is not None else None,
        "inputs": {
            "QQQ.close": inputs.close,
            "QQQ.ema20": inputs.ema20,
            "QQQ.ema50": inputs.ema50,
            "QQQ.ma200": inputs.ma200,
            "^VIX.close": vix,
            "^VIX3M.close": vix3m,
        },
    }


def _snapshot_value(snapshots: Dict[str, SymbolSnapshot], symbol: str, field: str) -> float | None:
    snap = snapshots.get(symbol)
    return None if snap is None else snap.get(field)


def _history_percentile(history: Any, as_of: str, window: int = 252, min_periods: int = 60) -> float | None:
    if history is None or history.empty or "Close" not in history:
        return None
    frame = history.loc[history.index <= pd.Timestamp(str(as_of)[:10])].tail(window)
    if len(frame) < min_periods:
        return None
    close = frame["Close"].dropna()
    if len(close) < min_periods:
        return None
    current = float(close.iloc[-1])
    return float((close <= current).mean() * 100.0)


def _target_weights_after_verdict(config: Dict[str, Any], bundles: Dict[str, Any]) -> Dict[str, float]:
    weights = {}
    for symbol, bundle in sorted(bundles.items()):
        cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        weights[symbol] = round(max(0.0, cap * (1.0 - float(bundle.result.sell_fraction))), 8)
    return weights


def _soft_snapshot(soft_data: Dict[str, Any], as_of: str) -> SymbolSnapshot:
    fields: Dict[str, Field] = {}
    day = date.fromisoformat(str(as_of)[:10])
    for name, record in soft_data.get("records", {}).items():
        source = str(record.get("source", "soft_data"))
        record_date = date.fromisoformat(str(record.get("as_of", day.isoformat()))[:10])
        fields[name] = Field(
            name=name,
            value=record.get("value"),
            source=source,
            as_of=record_date,
            is_proxy=bool(record.get("is_proxy", False)),
            latency_days=int(record.get("latency_days", 0) or 0),
            quality_penalty=float(record.get("quality_penalty", 0.0) or 0.0),
        )
        for field_name, value in record.get("fields", {}).items():
            provenance = (record.get("field_provenance") or {}).get(field_name) or {}
            fields[field_name] = Field(
                name=field_name,
                value=value,
                source=str(provenance.get("source") or source),
                as_of=record_date,
                is_proxy=bool(provenance.get("is_proxy", record.get("is_proxy", False))),
                latency_days=int(record.get("latency_days", 0) or 0),
                quality_penalty=float(
                    provenance.get("quality_penalty", record.get("quality_penalty", 0.0)) or 0.0
                ),
            )
    return SymbolSnapshot("SOFT", day, fields)


def _decision_quality_excluded_fields(
    soft_data: Dict[str, Any],
    config: Dict[str, Any],
) -> set[str]:
    excluded: set[str] = set()
    for name, record in (soft_data.get("records") or {}).items():
        if soft_record_decision_role(config, str(name)) not in {"auxiliary", "research"}:
            continue
        excluded.add(f"SOFT.{name}")
        if isinstance(record, dict):
            excluded.update(f"SOFT.{field_name}" for field_name in (record.get("fields") or {}))
    return excluded


def _quality_payloads(
    snapshots: Dict[str, SymbolSnapshot],
    soft_data: Dict[str, Any],
    config: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    all_source = quality_from_snapshots(snapshots.values())
    decision = quality_from_snapshots(
        snapshots.values(),
        excluded_fields=_decision_quality_excluded_fields(soft_data, config),
    )
    return decision.to_dict(), all_source.to_dict()


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _spine_full(config):
    """T10 flag: wire E7/E22 into the confidence spine (default OFF)."""
    return bool((config.get("features") or {}).get("use_full_confidence_spine"))


def _spine_fragility(bundles, config):
    """E7 (score-level wiring): threshold knife-edge fragility, worst symbol.

    Perturbs each final score +/-eps through the production status ladder and
    counts verdict flips. Input-level (per-factor) perturbation needs a
    re-scoring callable threaded through score_symbol — documented follow-up;
    score-level fragility already captures knife-edge decisions near thresholds.
    """
    from .core.governance.governance import decision_fragility
    from .core.decision.verdict import status_from_score

    eps = float((config.get("confidence") or {}).get("fragility_eps", 0.02))
    worst = 0.0
    for bundle in bundles.values():
        score = float(bundle.result.final_score or 0.0)
        if score <= 0.0:
            continue
        frag = decision_fragility(
            {"score": score},
            lambda snap: status_from_score(snap["score"], config),
            eps=eps,
        )
        worst = max(worst, frag)
    return worst


def _spine_disagreement(verdicts, config):
    """E22: rule vs meta vs mirror disagreement, worst symbol.

    meta_p_act and mirror_cycle are truthfully None today (meta-model OFF;
    the mirror plan is built later in the pipeline), so this contributes 0
    until a second opinion source is threaded — wired, not faked.
    """
    from .core.governance.governance import detect_disagreement

    cfg = config.get("confidence") or {}
    worst = 0.0
    for v in verdicts.values():
        worst = max(worst, float(detect_disagreement(v.status, None, None, cfg)))
    return worst


def _confidence_spine_dict(confidence) -> dict:
    """Export the global ConfidenceState into the payload (T20 dashboard).

    fragility/disagreement read 0.0 while use_full_confidence_spine is OFF —
    the dashboard labels them as un-wired rather than pretending they are
    healthy measurements.
    """
    return {
        "decision_confidence": round(float(confidence.decision_confidence), 6),
        "mode": str(confidence.mode),
        "components": {k: round(float(v), 6) for k, v in (confidence.components or {}).items()},
        "weakest_link": str(confidence.weakest_link),
        "notes": list(confidence.notes or []),
    }


def _risk_contribution_block(risk_state, target_weights: Dict[str, float]) -> Dict[str, Any]:
    """[T22] Per-leg ex-ante contribution to forecast portfolio vol.

    Reporting-only export of risk_engine.risk_contribution; never raises into
    the scoring path.
    """
    try:
        import numpy as np
        from .core.portfolio.risk_engine import risk_contribution

        legs = list(getattr(risk_state, "legs_used", []) or [])
        if not legs:
            return {}
        w = np.array([float(target_weights.get(sym, 0.0) or 0.0) for sym in legs])
        rc = risk_contribution(w, risk_state.cov)
        port_vol = float(sum(rc.values()))
        out: Dict[str, Any] = {}
        for i, sym in enumerate(legs):
            standalone = (risk_state.leg_vol or {}).get(sym)
            contrib = float(rc.get(f"leg_{i}", 0.0))
            out[sym] = {
                "target_weight": round(float(w[i]), 6),
                "standalone_vol": round(float(standalone), 6) if standalone == standalone and standalone is not None else None,
                "vol_contribution": round(contrib, 6),
                "vol_contribution_pct": round(contrib / port_vol, 6) if port_vol > 1e-9 else 0.0,
            }
        out["_portfolio"] = {"forecast_vol": round(port_vol, 6)}
        return out
    except Exception as exc:
        return {"_error": repr(exc)}


def _stress_block(risk_state, target_weights: Dict[str, float], histories) -> list:
    """[T23] Deterministic what-if estimates on the current target book.

    Shock scenarios use 60d betas to the shocked symbol; regime scenarios
    re-price forecast vol under corr->0.9 (and a 1.5x vol multiplier).
    """
    try:
        import math
        import numpy as np
        import pandas as pd
        from .core.portfolio.risk_engine import _finite_square_matrix

        legs = list(getattr(risk_state, "legs_used", []) or [])
        if not legs:
            return []
        w = np.array([float(target_weights.get(sym, 0.0) or 0.0) for sym in legs])
        out = []
        for name, shock_sym, shock in (("QQQ -5%", "QQQ", -0.05), ("BTC -10%", "BTC-USD", -0.10)):
            sh = histories.get(shock_sym)
            if sh is None or sh.empty or "Close" not in sh:
                continue
            r_shock = pd.to_numeric(sh["Close"], errors="coerce").pct_change(fill_method=None).dropna().tail(60)
            var_s = float(r_shock.var())
            pnl = 0.0
            for i, sym in enumerate(legs):
                if not w[i]:
                    continue
                if sym == shock_sym:
                    beta = 1.0
                else:
                    h = histories.get(sym)
                    if h is None or h.empty or "Close" not in h:
                        continue
                    r = pd.to_numeric(h["Close"], errors="coerce").pct_change(fill_method=None).dropna()
                    joined = pd.concat({"a": r, "s": r_shock}, axis=1, sort=True).dropna().tail(60)
                    beta = float(joined["a"].cov(joined["s"]) / var_s) if var_s > 0 and len(joined) >= 20 else 0.0
                pnl += float(w[i]) * beta * shock
            out.append({"name": name, "est_pnl_pct": round(pnl * 100.0, 3)})

        cov = _finite_square_matrix(risk_state.cov, size=len(w))
        d = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
        base_vol = math.sqrt(max(float(w @ cov @ w), 1e-12))
        corr9 = np.full_like(cov, 0.9)
        np.fill_diagonal(corr9, 1.0)
        vol9 = math.sqrt(max(float(w @ (corr9 * np.outer(d, d)) @ w), 1e-12))
        out.append({"name": "correlation -> 0.9",
                    "forecast_vol_before": round(base_vol, 6), "forecast_vol_after": round(vol9, 6)})
        out.append({"name": "VIX spike (vol x1.5 + corr 0.9)",
                    "forecast_vol_before": round(base_vol, 6), "forecast_vol_after": round(vol9 * 1.5, 6)})
        return out
    except Exception as exc:
        return [{"_error": repr(exc)}]


def _routing_context(bundles, snapshots, histories, config) -> Dict[str, Any]:
    """[T24] Why-this-DEFCON inputs: rule, observed QQQ trend state, module-A
    scores, and the BRK.B<->SPY correlation monitor behind the DEFCON2 fallback."""
    try:
        import pandas as pd
        from .core.routing.capital_routing import evaluate_brkb_defense

        # Rule strings must mirror capital_routing.py exactly — an operator
        # acting on a wrong explanation is worse than a code bug (2026-06-13
        # review finding: the old text claimed AND-with-QQQ-break; the code is
        # a pure OR chain).
        ctx: Dict[str, Any] = {
            "defcon1_rule": ("A>=12 OR core-A(A1+A5+A7+A8)>=8 OR any core-A factor maxed(4) "
                             "-> BOXX50/DBMF30/IAU20"),
            "defcon2_rule": ("D>=10 OR hard valve OR C8>=3 OR C6>=3 "
                             "-> BRK.B (fallback BOXX when BRK.B degraded/corr>threshold)"),
        }
        h = histories.get("QQQ")
        if h is not None and not h.empty and "Close" in h:
            c = pd.to_numeric(h["Close"], errors="coerce").dropna()
            close = float(c.iloc[-1])
            ma200 = float(c.rolling(200).mean().iloc[-1])
            ema20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            ctx["qqq"] = {
                "close": round(close, 2), "ma200": round(ma200, 2),
                "ema50": round(ema50, 2), "ema20": round(ema20, 2),
                "below_ma200": close < ma200, "below_ema50": close < ema50,
                "below_ema20": close < ema20,
            }
        ctx["module_a"] = {
            sym: float((bundle.result.module_scores or {}).get("A", 0.0))
            for sym, bundle in sorted(bundles.items())
        }
        brkb = evaluate_brkb_defense(snapshots, histories, config)
        ctx["brkb_defense"] = {
            "degraded": bool(brkb.degraded),
            "reason": brkb.reason,
            "corr_to_spy": round(float(brkb.corr_to_spy), 6) if brkb.corr_to_spy is not None else None,
            "threshold": float(config.get("routing", {}).get("defcon2", {}).get("brkb_corr_threshold", 0.85)),
        }
        bh, sph = histories.get("BRK.B"), histories.get("SPY")
        if bh is not None and sph is not None and not bh.empty and not sph.empty:
            joined = pd.concat(
                {"b": pd.to_numeric(bh["Close"], errors="coerce").pct_change(fill_method=None),
                 "s": pd.to_numeric(sph["Close"], errors="coerce").pct_change(fill_method=None)},
                axis=1,
                sort=True,
            ).dropna()
            roll = joined["b"].rolling(60).corr(joined["s"]).dropna().tail(252)
            ctx["brkb_correlation_series"] = [
                {"date": idx.strftime("%Y-%m-%d"), "corr": round(float(val), 4)}
                for idx, val in roll.items()
            ]
        return ctx
    except Exception as exc:
        return {"_error": repr(exc)}
