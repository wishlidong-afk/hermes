from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict


def write_flow_snapshot(path: Path, flow_payload: Dict[str, Any]) -> Path:
    """Persist money-flow rows so WebUI refreshes have an auditable data trail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    as_of = str(flow_payload.get("as_of", ""))[:10]
    rows = []
    for symbol, payload in (flow_payload.get("symbols") or {}).items():
        rows.append(("symbol", symbol, payload.get("severity"), json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    for symbol, payload in (flow_payload.get("component_baskets") or {}).items():
        rows.append(("basket", symbol, payload.get("severity"), json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_snapshots (
                as_of TEXT NOT NULL,
                kind TEXT NOT NULL,
                symbol TEXT NOT NULL,
                severity TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (as_of, kind, symbol)
            )
            """
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO flow_snapshots
            (as_of, kind, symbol, severity, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(as_of, kind, symbol, severity, payload_json) for kind, symbol, severity, payload_json in rows],
        )
    return path

