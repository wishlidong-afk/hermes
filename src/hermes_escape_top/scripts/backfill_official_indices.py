from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..config import load_config, resolve_path
from ..core.data.store import safe_symbol
from ..core.data.wso_index import available_wso_indices, fetch_wso_index
from ..core.safe_io import atomic_write_csv


@dataclass(frozen=True)
class OfficialIndexBackfillResult:
    symbol: str
    path: str
    start_date: Optional[str]
    end_date: Optional[str]
    rows: int
    updated: bool
    source: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def backfill_official_indices(store_dir: Optional[str | Path] = None) -> Dict[str, OfficialIndexBackfillResult]:
    cfg = load_config()
    history_dir = Path(store_dir) if store_dir else resolve_path(cfg, "history_dir")
    history_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, OfficialIndexBackfillResult] = {}
    for symbol in available_wso_indices():
        fetched = fetch_wso_index(symbol)
        path = history_dir / f"{safe_symbol(symbol)}.csv"
        updated = False
        if not fetched.frame.empty:
            _write_history(path, fetched.frame)
            updated = True
        results[symbol] = _result(symbol, path, fetched.frame, updated, fetched.source)
    return results


def _write_history(path: Path, frame: pd.DataFrame) -> None:
    out = frame.copy().sort_index()
    out.index.name = "date"
    out = out.reset_index().rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
    )
    for column in ["source", "symbol"]:
        if column not in out:
            out[column] = None
    atomic_write_csv(out[["date", "open", "high", "low", "close", "adj_close", "volume", "source", "symbol"]], path, index=False)


def _result(symbol: str, path: Path, frame: pd.DataFrame, updated: bool, source: str) -> OfficialIndexBackfillResult:
    if frame.empty:
        return OfficialIndexBackfillResult(symbol, str(path), None, None, 0, updated, source)
    return OfficialIndexBackfillResult(
        symbol=symbol,
        path=str(path),
        start_date=frame.index.min().date().isoformat(),
        end_date=frame.index.max().date().isoformat(),
        rows=int(len(frame)),
        updated=updated,
        source=source,
    )


if __name__ == "__main__":
    for item in backfill_official_indices().values():
        print(item)
