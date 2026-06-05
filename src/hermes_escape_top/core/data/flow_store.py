from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def write_flow_snapshot(path: Path, flow_payload: Dict[str, Any]) -> Path:
    """Persist money-flow rows so WebUI refreshes have an auditable data trail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    as_of = str(flow_payload.get("as_of", ""))[:10]
    created_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for symbol, payload in (flow_payload.get("symbols") or {}).items():
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        rows.append((
            "symbol",
            symbol,
            payload.get("severity"),
            payload.get("as_of"),
            0,
            _hash_payload(payload_json),
            created_at,
            payload_json,
        ))
    for symbol, payload in (flow_payload.get("component_baskets") or {}).items():
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        rows.append((
            "basket",
            symbol,
            payload.get("severity"),
            payload.get("component_min_as_of"),
            payload.get("component_max_stale_days"),
            _hash_payload(payload_json),
            created_at,
            payload_json,
        ))
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_snapshots (
                as_of TEXT NOT NULL,
                kind TEXT NOT NULL,
                symbol TEXT NOT NULL,
                severity TEXT,
                component_min_as_of TEXT,
                component_max_stale_days INTEGER,
                input_hash TEXT,
                created_at TEXT,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (as_of, kind, symbol)
            )
            """
        )
        _ensure_columns(conn)
        conn.executemany(
            """
            INSERT OR REPLACE INTO flow_snapshots
            (as_of, kind, symbol, severity, component_min_as_of, component_max_stale_days, input_hash, created_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (as_of, kind, symbol, severity, component_min_as_of, component_max_stale_days, input_hash, created_at, payload_json)
                for kind, symbol, severity, component_min_as_of, component_max_stale_days, input_hash, created_at, payload_json in rows
            ],
        )
    return path


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(flow_snapshots)").fetchall()}
    for name, ddl_type in [
        ("component_min_as_of", "TEXT"),
        ("component_max_stale_days", "INTEGER"),
        ("input_hash", "TEXT"),
        ("created_at", "TEXT"),
    ]:
        if name not in existing:
            conn.execute(f"ALTER TABLE flow_snapshots ADD COLUMN {name} {ddl_type}")


def _hash_payload(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
