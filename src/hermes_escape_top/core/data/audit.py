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


def rotate_audit_log(path: Path, keep_days: int = 90, min_size_mb: int = 100) -> Path | None:
    """Cap the append-only audit log so it cannot grow without bound.

    The full current log is FIRST archived to a timestamped gzip (lossless — no
    audit record is ever destroyed), then the main file is rewritten to keep only
    the latest record per (as_of, run_type) within the last ``keep_days`` — this
    collapses intraday re-run bloat and bounds date-range growth, preserving
    chronological order so the tail readers (latest payload, prev-entry diff,
    history strip) still resolve. Atomic replace: an interrupted rotation never
    loses the live log. No-op below ``min_size_mb``. Returns the archive path or
    None when nothing was rotated.
    """
    import gzip
    import os
    from datetime import date, datetime, timedelta

    try:
        if not path.exists() or path.stat().st_size < min_size_mb * 1024 * 1024:
            return None
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not lines:
            return None

        # 1. lossless full archive before any compaction
        archive = path.with_name(f"audit_log.archived_{datetime.now():%Y%m%dT%H%M%S}.jsonl.gz")
        with gzip.open(archive, "wt", encoding="utf-8") as az:
            az.write("\n".join(lines) + "\n")

        # 2. decide kept lines: latest per (as_of, run_type) within keep_days,
        #    in original chronological order; unparseable lines pass through.
        cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
        parsed = []          # (key | None, is_passthrough)
        last_idx: Dict[tuple, int] = {}
        for i, ln in enumerate(lines):
            try:
                rec = json.loads(ln)
                pl = rec.get("payload") if isinstance(rec, dict) else None
                pl = pl if isinstance(pl, dict) else rec
                ao = str(pl.get("as_of", ""))[:10]
                rt = str(pl.get("run_type", ""))
            except Exception:
                parsed.append((None, True))
                continue
            if not ao or ao < cutoff:
                parsed.append((None, False))     # older than window -> archived only
                continue
            key = (ao, rt)
            last_idx[key] = i
            parsed.append((key, False))
        kept = [lines[i] for i, (key, passthrough) in enumerate(parsed)
                if passthrough or (key is not None and last_idx[key] == i)]

        # 3. atomic replace
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return archive
    except Exception:
        return None   # rotation must never break a run


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
