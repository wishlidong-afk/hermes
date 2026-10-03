"""Read-only logical SQLite snapshots shared by offline capture and v2 rollback."""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .decision_identity import stable_hash


def sqlite_state_hash(connection: sqlite3.Connection) -> str:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("pre-state SQLite integrity check failed")
    schema = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name",
    ).fetchall()
    without_rowid = {row[1]: bool(row[4]) for row in connection.execute("PRAGMA table_list") if row[0] == "main"}
    tables = {}
    for kind, name, _table_name, _sql in schema:
        if kind != "table":
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        columns = connection.execute(f"PRAGMA table_xinfo({quoted})").fetchall()
        projection = "*"
        if not without_rowid[name]:
            column_names = {str(row[1]).lower() for row in columns}
            rowid = next((alias for alias in ("rowid", "_rowid_", "oid") if alias not in column_names), None)
            if rowid is None:
                raise ValueError("pre-state SQLite implicit rowid cannot be inspected")
            projection = f"{rowid}, *"
        rows = connection.execute(f"SELECT {projection} FROM {quoted}")
        tables[name] = {"columns": columns, "projection": projection,
                        "rows": sorted(stable_hash([_sqlite_cell(value) for value in row]) for row in rows)}
    return stable_hash({
        "schema": schema, "tables": tables,
        "pragmas": {key: connection.execute(f"PRAGMA {key}").fetchone()[0]
                    for key in ("user_version", "application_id", "encoding")},
    })


def _sqlite_cell(value: Any) -> tuple[str, Any]:
    if isinstance(value, bytes):
        return "blob", value.hex()
    if isinstance(value, float):
        return "real", value.hex()
    return type(value).__name__, value


def copy_sqlite_snapshot(source: Path, target: Path) -> dict[str, str]:
    def reject_busy(status: int, _remaining: int, _total: int) -> None:
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise RuntimeError("pre-state SQLite is busy; capture refused")

    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=0)) as original:
        original.execute("BEGIN")
        expected = sqlite_state_hash(original)
        with closing(sqlite3.connect(target)) as frozen:
            original.backup(frozen, progress=reject_busy, sleep=0)
            if sqlite_state_hash(frozen) != expected:
                raise ValueError("pre-state SQLite backup does not match source")
    target.chmod(0o400)
    return {"sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "logical_sha256": expected}
