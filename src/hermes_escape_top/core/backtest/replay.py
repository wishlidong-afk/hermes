from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd

from ...config import CONFIG_PATH, load_config
from ..data.manifest import freeze_manifest
from ..data.store import LocalStore
from ...pipeline import score_pipeline
from .simulator import simulate_rebalanced_weights


@dataclass(frozen=True)
class ReplayRow:
    as_of: str
    symbol: str
    status: str
    sell_fraction: float
    final_score: float
    target_weight: float
    hard_valves: list[str]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["sell_fraction"] = round(float(payload["sell_fraction"]), 6)
        payload["final_score"] = round(float(payload["final_score"]), 6)
        payload["target_weight"] = round(float(payload["target_weight"]), 6)
        return payload


def available_replay_dates(start: str, end: str, config_path: Path = CONFIG_PATH) -> list[str]:
    config = load_config(config_path)
    store = LocalStore(config)
    qqq = store.load_history("QQQ")
    if qqq.empty:
        return []
    idx = qqq.loc[(qqq.index >= pd.Timestamp(start)) & (qqq.index <= pd.Timestamp(end))].index
    return [ts.date().isoformat() for ts in idx]


def run_score_replay(
    dates: Iterable[str],
    config_path: Path = CONFIG_PATH,
    limit: int | None = None,
) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    manifest = freeze_manifest(store.history_dir)
    rows: List[ReplayRow] = []
    used_dates = list(dates)
    if limit is not None:
        used_dates = used_dates[:limit]
    for as_of in used_dates:
        payload = score_pipeline(as_of, config_path=config_path, include_ibkr=False)
        for symbol, score in sorted(payload["scores"].items()):
            rows.append(
                ReplayRow(
                    as_of=as_of,
                    symbol=symbol,
                    status=score["status"],
                    sell_fraction=float(score["sell_fraction"]),
                    final_score=float(score["final_score"]),
                    target_weight=float(payload["sizing"][symbol]["target_weight"]),
                    hard_valves=list(score["hard_valve_hits"]),
                )
            )
    return {
        "schema_version": "escape-top-greenfield-replay-v1",
        "data_manifest_id": manifest.manifest_id,
        "dates": used_dates,
        "rows": [row.to_dict() for row in rows],
    }


def run_strategy_backtest(
    start: str,
    end: str,
    config_path: Path = CONFIG_PATH,
    limit: int | None = None,
) -> Dict[str, Any]:
    config = load_config(config_path)
    store = LocalStore(config)
    manifest = freeze_manifest(store.history_dir)
    dates = available_replay_dates(start, end, config_path)
    if limit is not None:
        dates = dates[:limit]
    targets: Dict[str, Dict[str, float]] = {}
    for as_of in dates:
        payload = score_pipeline(as_of, config_path=config_path, include_ibkr=False)
        targets[as_of] = {symbol: float(row["target_weight"]) for symbol, row in payload["sizing"].items()}
    histories = {symbol: store.load_history(symbol) for symbol in config.get("symbols", {})}
    sim = simulate_rebalanced_weights(histories, targets)
    return {
        "schema_version": "escape-top-greenfield-strategy-backtest-v1",
        "data_manifest_id": manifest.manifest_id,
        "start": start,
        "end": end,
        "dates": dates,
        "simulation": sim.to_dict(),
    }
