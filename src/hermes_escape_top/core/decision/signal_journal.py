from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class SignalJournalEntry:
    as_of: str
    symbol: str
    status: str
    final_score: float
    hard_valves: list[str]
    regime: str = ""  # regime at signal time — lets the NEXT-5 unlock scan count
    # regime coverage forward (the old static backtest map ends 2026-05-29, so
    # forward signals had no regime source and the gate could never satisfy it).

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["final_score"] = round(float(payload["final_score"]), 6)
        return payload


def append_signal_journal(path: Path, entries: list[SignalJournalEntry]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_latest_status(path: Path, symbol: str, before_as_of: Optional[str] = None) -> Optional[str]:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("symbol") != symbol:
            continue
        if before_as_of is not None and str(row.get("as_of")) >= before_as_of:
            continue
        latest = str(row.get("status"))
    return latest


def trading_days_since_last_sell(path: Path, symbol: str, as_of: str) -> int:
    sell_states = {"TRIM", "REDUCE", "DEFENSIVE_EXIT", "EXIT"}
    if not path.exists():
        return 1_000_000
    target = date.fromisoformat(str(as_of)[:10])
    latest_sell: Optional[date] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("symbol") != symbol or row.get("status") not in sell_states:
            continue
        row_date = date.fromisoformat(str(row.get("as_of"))[:10])
        if row_date < target and (latest_sell is None or row_date > latest_sell):
            latest_sell = row_date
    if latest_sell is None:
        return 1_000_000
    return max(0, len(pd_bdays(latest_sell.isoformat(), target.isoformat())) - 1)


def pd_bdays(start: str, end: str) -> list[date]:
    import pandas as pd

    return [ts.date() for ts in pd.bdate_range(start, end)]
