from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict

from .strategy import MirrorLegDecision


def write_mirror_snapshot(path: Path, as_of: str, decisions: Dict[str, MirrorLegDecision]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mirror_snapshots (
                as_of TEXT NOT NULL,
                sleeve TEXT NOT NULL,
                selected_symbol TEXT NOT NULL,
                target_weight REAL NOT NULL,
                cycle TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (as_of, sleeve)
            )
            """
        )
        for sleeve, decision in decisions.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO mirror_snapshots
                (as_of, sleeve, selected_symbol, target_weight, cycle, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    as_of,
                    sleeve,
                    decision.selected_symbol,
                    decision.target_weight,
                    decision.cycle,
                    json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True),
                ),
            )
    return path
