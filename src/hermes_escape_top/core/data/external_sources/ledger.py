from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


LEDGER_NAME = "external_source_runs.jsonl"


def ledger_path(archive_dir: Path) -> Path:
    return Path(archive_dir) / "external_sources" / LEDGER_NAME


def append_source_run(archive_dir: Path, record: dict[str, Any]) -> Path:
    path = ledger_path(archive_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path


def iter_source_runs(archive_dir: Path) -> Iterable[dict[str, Any]]:
    path = ledger_path(archive_dir)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def latest_source_run(archive_dir: Path, source_id: str) -> dict[str, Any] | None:
    latest = None
    for row in iter_source_runs(archive_dir):
        if row.get("source_id") == source_id:
            latest = row
    return latest


def source_status(archive_dir: Path, specs: Iterable[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for spec in specs:
        row = latest_source_run(archive_dir, spec.source_id)
        out[spec.source_id] = row or {"source_id": spec.source_id, "status": "MISSING"}
    return out
