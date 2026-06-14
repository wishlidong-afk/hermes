from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class AuditRecord:
    schema_version: str
    as_of: str
    input_hash: str
    config_version: str
    payload_hash: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def write_audit_record(payload: Dict[str, Any], archive_dir: Path) -> Path:
    from ...pipeline import stable_hash

    archive_dir.mkdir(parents=True, exist_ok=True)
    record = AuditRecord(
        schema_version="escape-top-greenfield-audit-v1",
        as_of=str(payload.get("as_of")),
        input_hash=str(payload.get("input_hash")),
        config_version=str(payload.get("config_version")),
        payload_hash=stable_hash(payload),
        payload=payload,
    )
    path = archive_dir / "audit_log.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path


def load_last_audit(path: Path) -> AuditRecord | None:
    """Last record without reading the whole append-only log. audit_log.jsonl is
    150MB+ and grows; read only the tail and take the last complete line. One
    record is ~650KB, so a 4MB tail comfortably holds the final line intact."""
    if not path.exists():
        return None
    chunk = 4 * 1024 * 1024
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - chunk))
        data = fh.read()
    lines = [line for line in data.split(b"\n") if line.strip()]
    if not lines:
        return None
    payload = json.loads(lines[-1])
    return AuditRecord(**payload)


def audit_replay_matches(record: AuditRecord) -> bool:
    from ...pipeline import stable_hash

    return stable_hash(record.payload) == record.payload_hash
