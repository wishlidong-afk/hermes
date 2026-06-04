from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Any, Dict, Iterable

from ...config import CONFIG_PATH, load_config
from ..data.manifest import freeze_manifest
from ..data.store import LocalStore
from .replay import available_replay_dates
from .simulator import simulate_rebalanced_weights


@dataclass(frozen=True)
class SweepRow:
    vol_budget_annual: float
    corr_window: int
    extreme_corr_penalty: float
    final_value: float
    max_drawdown: float
    cagr: float | None
    turnover: float
    note: str

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ["vol_budget_annual", "extreme_corr_penalty", "final_value", "max_drawdown", "cagr", "turnover"]:
            if payload[key] is not None:
                payload[key] = round(float(payload[key]), 6)
        return payload


def run_param_sweep(
    start: str,
    end: str,
    config_path=CONFIG_PATH,
    vol_budgets: Iterable[float] = (0.25, 0.30, 0.35, 0.40, 0.45, 0.50),
    corr_windows: Iterable[int] = (40, 60, 90),
    penalties: Iterable[float] = (0.6, 0.7, 0.8),
    limit: int | None = 60,
) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    manifest = freeze_manifest(store.history_dir)
    dates = available_replay_dates(start, end, config_path)
    if limit is not None:
        dates = dates[:limit]
    histories = {symbol: store.load_history(symbol) for symbol in ["MSTR", "FNGU", "SOXL"]}
    # This sweep intentionally uses static sleeve weights as a cheap calibration
    # harness. Full rule replay remains in simulator/replay and can replace this
    # target generator once trade-level backtest is expanded.
    base_targets = {date: {"MSTR": 0.15, "FNGU": 0.20, "SOXL": 0.30} for date in dates}
    rows = []
    for vol_budget, corr_window, penalty in product(vol_budgets, corr_windows, penalties):
        result = simulate_rebalanced_weights(histories, base_targets)
        metrics = result.metrics
        rows.append(
            SweepRow(
                vol_budget_annual=float(vol_budget),
                corr_window=int(corr_window),
                extreme_corr_penalty=float(penalty),
                final_value=float(metrics.get("final_value", 0.0)),
                max_drawdown=float(metrics.get("max_drawdown", 0.0)),
                cagr=metrics.get("cagr"),
                turnover=float(result.turnover),
                note="static-target calibration scaffold; full rule replay pending",
            ).to_dict()
        )
    return {
        "schema_version": "escape-top-greenfield-param-sweep-v1",
        "data_manifest_id": manifest.manifest_id,
        "start": start,
        "end": end,
        "dates": dates,
        "rows": rows,
    }
