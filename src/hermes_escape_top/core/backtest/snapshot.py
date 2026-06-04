from __future__ import annotations

import copy
from datetime import date
from typing import Any, Dict, Optional

from ...config import load_config
from ..data.adapters import collect_soft_data
from ..data.base import Field, SymbolSnapshot
from ..data.market import MarketData
from ..data.store import LocalStore


def build_snapshot(
    as_of: str,
    store: Optional[LocalStore] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, SymbolSnapshot]:
    config = copy.deepcopy(cfg or load_config())
    config.setdefault("runtime", {})["offline_replay_mode"] = True
    local_store = store or LocalStore(config)
    market = MarketData(config=config, store=local_store)
    symbols = _snapshot_universe(config)
    snapshots = {symbol: market.snapshot(symbol, as_of) for symbol in symbols}
    soft_data = collect_soft_data(as_of, config, local_store)
    snapshots["SOFT"] = _soft_snapshot(soft_data, as_of)
    return snapshots


def _snapshot_universe(config: Dict[str, Any]) -> list[str]:
    symbols = set(config.get("symbols", {}).keys())
    symbols.update(config.get("market_symbols", []))
    for values in config.get("radars", {}).values():
        symbols.update(values)
    for values in config.get("component_proxies", {}).values():
        symbols.update(values)
    return sorted(symbols)


def _soft_snapshot(soft_data: Dict[str, Any], as_of: str) -> SymbolSnapshot:
    fields: Dict[str, Field] = {}
    day = date.fromisoformat(str(as_of)[:10])
    for _name, record in soft_data.get("records", {}).items():
        source = str(record.get("source", "soft_data"))
        record_date = date.fromisoformat(str(record.get("as_of", day.isoformat()))[:10])
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
