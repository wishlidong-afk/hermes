from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .config import CONFIG_PATH, load_config, trade_symbols
from .core.data.base import Field, SymbolSnapshot
from .core.data.flow import basket_flow, money_flow_metrics
from .core.data.market import MarketData
from .core.data.audit import write_audit_record
from .core.data.quality import analyze_missing_fields, quality_from_snapshots
from .core.data.store import LocalStore, bootstrap_history
from .core.data.adapters import collect_soft_data
from .core.backtest.posterior import escape_posterior_pnl, mirror_posterior_pnl
from .core.features.regime import Regime, RegimeInput, classify_regime
from .core.portfolio.risk_budget import compute_portfolio_risk
from .core.portfolio.sizing import size_portfolio  # kept for fallback / legacy compat
from .core.portfolio.risk_engine import build_risk_state
from .core.portfolio.sizing_optimizer import optimize_targets
from .core.confidence.spine import compute_confidence
from .core.contracts import Verdict, ConfidenceState
from .core.routing.capital_routing import route_capital
from .core.reentry.plan import build_reentry_plan
from .core.decision.signal_journal import SignalJournalEntry, append_signal_journal, trading_days_since_last_sell
from .mirror.strategy import build_mirror_plan
from .mirror.store import write_mirror_snapshot
from .core.scoring.scorer import score_symbol
from .core.scoring.result import ScoreResult


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
        score.blind_spot = missing.blind_spot
        score.final_score = missing.adjusted_score
        scores[symbol] = score
    quality = quality_from_snapshots(snapshots.values())
    payload = {
        "schema_version": "escape-top-greenfield-phase0-empty-v1",
        "as_of": as_of,
        "config_version": config["version"],
        "snapshots": {symbol: snap.to_dict() for symbol, snap in snapshots.items()},
        "scores": {symbol: score.to_dict() for symbol, score in scores.items()},
        "data_quality": quality.to_dict(),
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
    rows: Dict[str, Any] = {}
    for symbol in trade_symbols(config):
        rows[symbol] = money_flow_metrics(symbol, store.load_history(symbol), as_of).to_dict()
    component_rows = {}
    for symbol, components in config.get("component_proxies", {}).items():
        histories = {component: store.load_history(component) for component in components}
        component_rows[symbol] = basket_flow(components, histories, as_of)
    return {
        "schema_version": "escape-top-greenfield-flow-v2-v1",
        "as_of": as_of,
        "symbols": rows,
        "component_baskets": component_rows,
    }


def score_pipeline(as_of: str, config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    market = MarketData(config=config, store=store)
    symbols = _snapshot_universe(config)
    snapshots = {symbol: market.snapshot(symbol, as_of) for symbol in symbols}
    histories = {symbol: market.load_history(symbol) for symbol in symbols}
    soft_data = collect_soft_data(as_of, config, store)
    snapshots["SOFT"] = _soft_snapshot(soft_data, as_of)
    regime, regime_meta = _current_regime(snapshots, histories, as_of)
    bundles = {symbol: score_symbol(symbol, snapshots, config, regime=regime, histories=histories) for symbol in trade_symbols(config)}
    target_weights = _target_weights_after_verdict(config, bundles)
    hard_excluded = {symbol for symbol, bundle in bundles.items() if bundle.result.hard_valve_hits or bundle.result.sell_fraction >= 1.0}
    portfolio_risk = compute_portfolio_risk(histories, target_weights, config, excluded_symbols=hard_excluded)
    sizing = _optimize_sizing(bundles, histories, portfolio_risk, config)
    routing = {symbol: route_capital(symbol, bundle.result, config, snapshots=snapshots, histories=histories) for symbol, bundle in bundles.items()}
    signal_journal_path = store.archive_dir / "signal_journal.jsonl"
    reentry = {
        symbol: build_reentry_plan(
            symbol,
            bundle.result,
            snapshots,
            histories,
            config,
            days_since_last_sell=trading_days_since_last_sell(signal_journal_path, symbol, as_of),
        )
        for symbol, bundle in bundles.items()
    }
    mirror = build_mirror_plan(snapshots, config)
    mirror_db = write_mirror_snapshot(store.archive_dir / "mirror_reference.sqlite", str(as_of)[:10], mirror)
    escape_pnl = escape_posterior_pnl(
        {symbol: decision.to_dict() for symbol, decision in sizing.items()},
        histories,
        as_of,
    )
    mirror_pnl = mirror_posterior_pnl(mirror, histories, as_of)
    payload = {
        "schema_version": "escape-top-greenfield-phase3-score-v1",
        "as_of": as_of,
        "config_version": config["version"],
        "snapshots": {symbol: snap.to_dict() for symbol, snap in sorted(snapshots.items())},
        "scores": {symbol: bundle.result.to_dict() for symbol, bundle in sorted(bundles.items())},
        "regime": regime_meta,
        "portfolio_risk": portfolio_risk.to_dict(),
        "sizing": {symbol: decision.to_dict() for symbol, decision in sorted(sizing.items())},
        "routing": {symbol: decision.to_dict() for symbol, decision in sorted(routing.items())},
        "reentry": {symbol: plan.to_dict() for symbol, plan in sorted(reentry.items())},
        "soft_data": soft_data,
        "mirror": {
            "db_path": str(mirror_db),
            "decisions": {sleeve: decision.to_dict() for sleeve, decision in sorted(mirror.items())},
        },
        "posterior_pnl": {
            "portfolio_value": 100000.0,
            "escape": {symbol: row.to_dict() for symbol, row in sorted(escape_pnl.items())},
            "mirror": {sleeve: row.to_dict() for sleeve, row in sorted(mirror_pnl.items())},
        },
        "data_quality": quality_from_snapshots(snapshots.values()).to_dict(),
    }
    payload["input_hash"] = stable_hash(payload["snapshots"])
    audit_path = write_audit_record(payload, store.archive_dir)
    signal_path = append_signal_journal(
        signal_journal_path,
        [
            SignalJournalEntry(
                as_of=str(as_of)[:10],
                symbol=symbol,
                status=bundle.result.status,
                final_score=bundle.result.final_score,
                hard_valves=bundle.result.hard_valve_hits,
            )
            for symbol, bundle in sorted(bundles.items())
        ],
    )
    payload["audit_log_path"] = str(audit_path)
    payload["signal_journal_path"] = str(signal_path)
    return payload


def _optimize_sizing(
    bundles: Dict[str, Any],
    histories: Dict[str, Any],
    portfolio_risk: Any,
    config: Dict[str, Any],
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
            leg_returns[symbol] = close.pct_change().dropna()

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
            adv20 = float(vol_series.mean() * price) if len(vol_series) >= 5 else float("inf")
        else:
            adv20 = float("inf")  # no volume data → liquidity_cap will not bind
        liquidity_data[symbol] = {"adv20": adv20, "price": price, "netliq": netliq}

    optimizer_cfg = {
        "risk_engine": config.get("portfolio", {}),
        "sizing": {
            "dd_aversion": 3.0,
            "leverage_L": {"FNGU": 3, "SOXL": 3, "MSTR": 1},
            "solver": "slsqp_or_grid",
            "exec_slices": 3,
        },
    }
    # Inherit vol_budget from portfolio config
    port_cfg = config.get("portfolio", {})
    optimizer_cfg["risk_engine"]["vol_budget_annual"] = float(
        port_cfg.get("vol_budget_annual", 0.35)
    )
    optimizer_cfg["risk_engine"]["min_periods"] = int(port_cfg.get("min_periods", 40))
    optimizer_cfg["risk_engine"]["ewma_lambda"] = float(port_cfg.get("ewma_lambda", 0.94))

    risk_state = build_risk_state(
        {s: leg_returns[s] for s in verdicts if s in leg_returns},
        {s: v.rule_target_weight for s, v in verdicts.items()},
        None,
        optimizer_cfg,
    )

    # ── Build ConfidenceState via ConfidenceSpine (Gate ④) ───────────────────
    # Use getattr so missing attributes (data_quality_score, failover_state,
    # staleness_days, drift_state) degrade gracefully to neutral 0.5 in the
    # spine rather than hard-erroring. Fragility and disagreement remain wired
    # as None (pending E7/E22 integration) and receive the same neutral treatment.
    confidence = compute_confidence(
        data_conf=getattr(portfolio_risk, "data_quality_score", None),
        failover_state=getattr(portfolio_risk, "failover_state", None),
        staleness_days=getattr(portfolio_risk, "staleness_days", None),
        drift_state=getattr(portfolio_risk, "drift_state", None),
        fragility=None,      # TODO: wire E7 fragility score
        disagreement=None,   # TODO: wire E22 model disagreement
        cfg=config.get("confidence", {}),
    )

    # ── Run optimizer ─────────────────────────────────────────────────────────
    try:
        opt_decision = optimize_targets(
            verdicts, risk_state, confidence, optimizer_cfg,
            leg_returns=leg_returns,
            liquidity_data=liquidity_data,
        )
    except Exception as exc:
        # Safety fallback: revert to old scaler chain if optimizer fails
        return size_portfolio(
            histories,
            {symbol: bundle.result for symbol, bundle in bundles.items()},
            config,
            gross_scaler=portfolio_risk.effective_gross_scaler,
        )

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
            vol_scaler=float(portfolio_risk.effective_gross_scaler),
            gross_scaler=float(portfolio_risk.effective_gross_scaler),
            target_weight=new_target,
            clamp_applied=new_target < old_ref - 1e-9,
            binding_constraint=binding,
            execution_mode=exec_mode,
            optimizer_confidence=float(opt_decision.confidence_applied),
            explain=opt_decision.notes + [f"optimizer binding={binding}"],
        )
    return result


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
            fields[field_name] = Field(
                name=field_name,
                value=value,
                source=source,
                as_of=record_date,
                is_proxy=bool(record.get("is_proxy", False)),
                latency_days=int(record.get("latency_days", 0) or 0),
                quality_penalty=float(record.get("quality_penalty", 0.0) or 0.0),
            )
    return SymbolSnapshot("SOFT", day, fields)


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
