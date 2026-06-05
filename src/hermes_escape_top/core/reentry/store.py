from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .plan import ReentryPlan


@dataclass(frozen=True)
class ReentryState:
    symbol: str
    t1_active: bool = False
    t2_active: bool = False
    last_tranche: str = "LOCKED"
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def read_reentry_states(path: Path) -> Dict[str, ReentryState]:
    if not path.exists():
        return {}
    with sqlite3.connect(path) as conn:
        _ensure_tables(conn)
        rows = conn.execute(
            "SELECT symbol, t1_active, t2_active, last_tranche, updated_at FROM reentry_state"
        ).fetchall()
    return {
        str(symbol): ReentryState(
            symbol=str(symbol),
            t1_active=bool(t1_active),
            t2_active=bool(t2_active),
            last_tranche=str(last_tranche or "LOCKED"),
            updated_at=str(updated_at or ""),
        )
        for symbol, t1_active, t2_active, last_tranche, updated_at in rows
    }


def write_reentry_snapshot(
    path: Path,
    as_of: str,
    plans: Dict[str, ReentryPlan],
    states: Dict[str, ReentryState],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as conn:
        _ensure_tables(conn)
        for symbol, plan in sorted(plans.items()):
            state = states.get(symbol) or ReentryState(symbol=symbol)
            conn.execute(
                """
                INSERT OR REPLACE INTO reentry_plans
                (as_of, symbol, eligible, tranche, allocation_fraction, locked_reason, state_json, plan_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(as_of)[:10],
                    symbol,
                    int(bool(plan.eligible)),
                    plan.tranche,
                    float(plan.allocation_fraction),
                    plan.locked_reason,
                    json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True),
                    json.dumps(plan.to_dict(), ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO reentry_state
                (symbol, t1_active, t2_active, last_tranche, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    int(bool(state.t1_active)),
                    int(bool(state.t2_active)),
                    state.last_tranche,
                    state.updated_at or now,
                ),
            )
    return path


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reentry_state (
            symbol TEXT PRIMARY KEY,
            t1_active INTEGER NOT NULL DEFAULT 0,
            t2_active INTEGER NOT NULL DEFAULT 0,
            last_tranche TEXT NOT NULL DEFAULT 'LOCKED',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reentry_plans (
            as_of TEXT NOT NULL,
            symbol TEXT NOT NULL,
            eligible INTEGER NOT NULL,
            tranche TEXT NOT NULL,
            allocation_fraction REAL NOT NULL,
            locked_reason TEXT NOT NULL,
            state_json TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (as_of, symbol)
        )
        """
    )
