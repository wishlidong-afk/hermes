from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd

from ...config import CONFIG_PATH, load_config, trade_symbols
from ...pipeline import _optimize_sizing
from ..data.manifest import freeze_manifest
from ..data.store import LocalStore
from ..features.regime import Regime, RegimeInput, classify_regime
from ..portfolio.risk_budget import compute_portfolio_risk
from ..routing.capital_routing import route_capital
from ..routing.leg_proxy import leg_price_series, leg_proxy_metadata
from ..data.sanitize import is_suspect_on
from ..scoring.scorer import score_symbol
from .labeling import eval_labels
from .metrics import compute_metrics
from .simulator import DayDecision, SimulationResult, simulate
from .snapshot import build_snapshot
from .validation import deflated_sharpe, walk_forward_splits


@dataclass(frozen=True)
class FullBacktestReport:
    schema_version: str
    data_manifest_id: str
    requested_start: str
    requested_end: str
    effective_start: str
    effective_end: str
    dates: list[str]
    coverage: Dict[str, Any]
    simulation: Dict[str, Any]
    benchmarks: Dict[str, Any]
    signal_quality: Dict[str, Any]
    walk_forward: Dict[str, Any]
    rows: list[Dict[str, Any]]
    proxy_legs: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def run_full_backtest(
    start: str = "2018-01-01",
    end: str = "2026-05-29",
    cfg: Optional[Dict[str, Any]] = None,
    *,
    config_path: Path = CONFIG_PATH,
    enable: Optional[set[str]] = None,
    limit: Optional[int] = None,
) -> FullBacktestReport:
    config = copy.deepcopy(cfg or load_config(config_path))
    config.setdefault("runtime", {})["offline_replay_mode"] = True
    store = LocalStore(config)
    manifest = freeze_manifest(store.history_dir)
    histories = _load_histories(store, config)
    coverage = _coverage(histories, start, end, trade_symbols(config))
    effective_start = str(coverage["effective_start"])
    dates = _available_dates_from_history(histories.get("QQQ", pd.DataFrame()), effective_start, end)
    if limit is not None:
        dates = dates[:limit]
    if not dates:
        empty = simulate([], {}, config, enable=enable)
        return FullBacktestReport(
            "escape-top-greenfield-full-backtest-v1",
            manifest.manifest_id,
            start,
            end,
            effective_start,
            end,
            [],
            coverage,
            empty.to_dict(),
            {},
            {},
            {"folds": []},
            [],
            {},
        )

    # Stateful stabilizer (F1+F2) + suspect-bar guard (F3) must be threaded through
    # the replay loop to be exercised at all; both are flag-gated so the default
    # path is byte-identical to a flat, stateless backtest.
    _f = config.get("features", {})
    stabilizer_on = bool(_f.get("use_decision_stabilizer", False) or _f.get("use_status_hysteresis", False) or _f.get("use_close_confirmation", False))
    suspect_guard_on = bool(_f.get("use_suspect_valve_guard", False))
    sanitize_cfg = config.get("sanitize", {})
    previous_raw: Dict[str, str] = {}

    decisions: list[DayDecision] = []
    rows: list[Dict[str, Any]] = []
    for as_of in dates:
        day_histories = _truncate_histories(histories, as_of)
        snapshots = build_snapshot(as_of, store=store, cfg=config)
        regime, regime_meta = _current_regime(snapshots, day_histories, as_of)
        bundles = {
            symbol: score_symbol(
                symbol,
                snapshots,
                config,
                regime=regime,
                histories=day_histories,
                suspect=(is_suspect_on(day_histories.get(symbol), as_of, sanitize_cfg) if suspect_guard_on else False),
                previous_status=(previous_raw.get(symbol) if stabilizer_on else None),
            )
            for symbol in trade_symbols(config)
        }
        if stabilizer_on:
            # Feed back the RAW signal level (not the held status) so a persistent
            # upgrade confirms on the next close.
            for symbol, bundle in bundles.items():
                previous_raw[symbol] = bundle.result.raw_status
        cap_targets = {
            symbol: float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
            * (1.0 - float(bundle.result.sell_fraction))
            for symbol, bundle in bundles.items()
        }
        hard_excluded = {symbol for symbol, bundle in bundles.items() if bundle.result.hard_valve_hits or bundle.result.sell_fraction >= 1.0}
        risk = compute_portfolio_risk(day_histories, cap_targets, config, excluded_symbols=hard_excluded)
        sizing, _spine = _optimize_sizing(
            bundles,
            day_histories,
            risk,
            config,
            as_of=as_of,
            signal_journal_path=None,
        )
        routing = {symbol: route_capital(symbol, bundle.result, config, snapshots=snapshots, histories=day_histories) for symbol, bundle in bundles.items()}
        weights = route_leg_weights(config, {symbol: decision.to_dict() for symbol, decision in sizing.items()}, {symbol: decision.to_dict() for symbol, decision in routing.items()})
        decisions.append(DayDecision(as_of, weights))
        rows.append(
            {
                "date": as_of,
                "regime": regime_meta,
                "scores": {symbol: bundle.result.to_dict() for symbol, bundle in sorted(bundles.items())},
                "sizing": {symbol: decision.to_dict() for symbol, decision in sorted(sizing.items())},
                "routing": {symbol: decision.to_dict() for symbol, decision in sorted(routing.items())},
                "route_leg_weights": weights,
                "portfolio_risk_legacy_shadow": risk.to_dict(),
            }
        )

    legs = sorted({leg for decision in decisions for leg in decision.target_weights})
    panel = _price_panel(legs, dates, histories)
    simulation = simulate(decisions, panel, config, enable=enable or {"costs"}).to_dict()
    benchmarks = _benchmarks(dates, histories, simulation)
    signal_quality = _signal_quality(rows, histories)
    folds = walk_forward_splits(dates)
    walk = {
        "folds": [
            {
                "train_start": fold.train_start,
                "train_end": fold.train_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "train_n": int(len(fold.train_idx)),
                "test_n": int(len(fold.test_idx)),
            }
            for fold in folds
        ],
        "deflated_sharpe": _simulation_deflated_sharpe(simulation),
        "confidence_note": "Low-to-medium: sample is coverage-constrained by FNGU history and defensive events remain sparse.",
    }
    proxies = {
        leg: leg_proxy_metadata(leg, dates).to_dict("records")
        for leg in sorted(legs)
        if leg in {"BOXX", "DBMF"}
    }
    return FullBacktestReport(
        "escape-top-greenfield-full-backtest-v1",
        manifest.manifest_id,
        start,
        end,
        dates[0],
        dates[-1],
        dates,
        coverage,
        simulation,
        benchmarks,
        signal_quality,
        walk,
        rows,
        proxies,
    )


def route_leg_weights(config: Dict[str, Any], sizing: Dict[str, Dict[str, Any]], routing: Dict[str, Dict[str, Any]]) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    for symbol in trade_symbols(config):
        cap = float(config.get("symbols", {}).get(symbol, {}).get("sleeve_cap", 0.0))
        target = max(0.0, float(sizing.get(symbol, {}).get("target_weight", 0.0) or 0.0))
        if target:
            weights[symbol] = weights.get(symbol, 0.0) + target
        residual = max(0.0, cap - target)
        route = routing.get(symbol, {})
        route_weights = route.get("weights", {}) if route.get("applies") else {}
        if residual and route_weights:
            for leg, share in route_weights.items():
                weights[str(leg)] = weights.get(str(leg), 0.0) + residual * float(share)
        elif residual:
            weights["BOXX"] = weights.get("BOXX", 0.0) + residual
    gross = sum(weights.values())
    if gross < 1.0:
        weights["BOXX"] = weights.get("BOXX", 0.0) + (1.0 - gross)
    if gross > 1.0:
        weights = {leg: weight / gross for leg, weight in weights.items()}
    return {leg: round(float(weight), 8) for leg, weight in sorted(weights.items()) if weight > 1e-12}


def _load_histories(store: LocalStore, config: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    symbols = set(trade_symbols(config))
    symbols.update(config.get("market_symbols", []))
    symbols.update(["BOXX", "BIL", "SHV", "DBMF", "BRK.B", "QQQ", "SOXX", "SPY"])
    for values in config.get("radars", {}).values():
        symbols.update(values)
    for values in config.get("component_proxies", {}).values():
        symbols.update(values)
    return {symbol: store.load_history(symbol) for symbol in sorted(symbols)}


def _coverage(histories: Dict[str, pd.DataFrame], start: str, end: str, required: Iterable[str]) -> Dict[str, Any]:
    rows = {}
    first_dates = []
    for symbol in required:
        history = histories.get(symbol, pd.DataFrame())
        if history.empty:
            rows[symbol] = {"start": None, "end": None, "rows": 0, "blocks_requested_start": True}
            continue
        first = history.index.min().date().isoformat()
        last = history.index.max().date().isoformat()
        blocks = (pd.Timestamp(first) - pd.Timestamp(start)).days > 7
        rows[symbol] = {"start": first, "end": last, "rows": int(len(history)), "blocks_requested_start": bool(blocks)}
        first_dates.append(first)
    effective_start = max([start] + first_dates) if first_dates else start
    return {
        "requested_start": start,
        "requested_end": end,
        "effective_start": effective_start,
        "required_symbols": rows,
        "notes": [
            "Effective start is the latest available inception among required risk symbols.",
            "This avoids fabricating returns before FNGU history is available in the current data source.",
        ],
    }


def _available_dates_from_history(history: pd.DataFrame, start: str, end: str) -> list[str]:
    if history is None or history.empty:
        return []
    idx = history.loc[(history.index >= pd.Timestamp(start)) & (history.index <= pd.Timestamp(end))].index
    return [ts.date().isoformat() for ts in idx]


def _truncate_histories(histories: Dict[str, pd.DataFrame], as_of: str) -> Dict[str, pd.DataFrame]:
    day = pd.Timestamp(as_of)
    return {symbol: frame.loc[frame.index <= day].copy() if frame is not None and not frame.empty else pd.DataFrame() for symbol, frame in histories.items()}


def _price_panel(legs: list[str], dates: list[str], histories: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
    date_index = pd.DatetimeIndex(pd.to_datetime(dates))
    return {leg: leg_price_series(leg, date_index, histories=histories) for leg in legs}


def _benchmarks(dates: list[str], histories: Dict[str, pd.DataFrame], simulation: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    equity = pd.Series(simulation.get("equity_curve", {}), dtype=float)
    for symbol in ["SPY", "QQQ"]:
        bench = leg_price_series(symbol, pd.DatetimeIndex(pd.to_datetime(dates)), histories=histories)
        if bench.empty:
            continue
        bench_equity = bench / float(bench.iloc[0]) * 100000.0
        out[symbol] = compute_metrics(equity, benchmark=bench_equity, trades=[]).get("benchmark_cagr")
        out[f"{symbol}_metrics"] = compute_metrics(bench_equity, trades=[])
    return out


def _signal_quality(rows: list[Dict[str, Any]], histories: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for symbol in sorted({symbol for row in rows for symbol in row.get("scores", {})}):
        signals = [
            row["date"]
            for row in rows
            if row.get("scores", {}).get(symbol, {}).get("status") in {"TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"}
        ]
        history = histories.get(symbol, pd.DataFrame())
        if history.empty or "Close" not in history.columns:
            out[symbol] = {"signals": len(signals), "label_rows": 0}
            continue
        labels = eval_labels(signals, history["Close"], H=20, dd_threshold=-0.10)
        hit_rate = float(labels["label"].mean()) if not labels.empty else None
        out[symbol] = {
            "signals": len(signals),
            "label_rows": int(len(labels)),
            "hit_rate": round(hit_rate, 6) if hit_rate is not None else None,
            "avg_fwd_dd": round(float(labels["fwd_dd"].mean()), 6) if not labels.empty else None,
            "avg_fwd_ret": round(float(labels["fwd_ret"].mean()), 6) if not labels.empty else None,
        }
    return out


def _simulation_deflated_sharpe(simulation: Dict[str, Any]) -> float:
    equity = pd.Series(simulation.get("equity_curve", {}), dtype=float)
    returns = equity.pct_change(fill_method=None).dropna()
    if returns.empty:
        return 0.0
    return round(float(deflated_sharpe(returns, n_trials=1, skew=float(returns.skew()), kurt=float(returns.kurt() + 3))), 6)


def _current_regime(
    snapshots: Dict[str, Any],
    histories: Dict[str, pd.DataFrame],
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
    return regime, {"current": regime.value, "vix_percentile": vix_pct, "vix_term_ratio": term_ratio}


def _snapshot_value(snapshots: Dict[str, Any], symbol: str, field: str) -> float | None:
    snap = snapshots.get(symbol)
    return None if snap is None else snap.get(field)


def _history_percentile(history: pd.DataFrame | None, as_of: str, window: int = 252, min_periods: int = 60) -> float | None:
    if history is None or history.empty or "Close" not in history:
        return None
    frame = history.loc[history.index <= pd.Timestamp(as_of)].tail(window)
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna()
    if len(close) < min_periods:
        return None
    current = float(close.iloc[-1])
    return float((close <= current).mean() * 100.0)
