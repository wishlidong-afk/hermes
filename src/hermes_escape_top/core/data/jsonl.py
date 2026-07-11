"""Durable JSONL append with deterministic repair of an interrupted tail."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


MAX_TAIL_SCAN_BYTES = 8 * 1024 * 1024


class JsonlTailError(RuntimeError):
    pass


def repair_jsonl_tail(path: Path, *, max_scan_bytes: int = MAX_TAIL_SCAN_BYTES) -> dict[str, Any]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {"status": "EMPTY", "removed_bytes": 0}
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(size - 1)
        if handle.read(1) == b"\n":
            return {"status": "CLEAN", "removed_bytes": 0}
        start = max(0, size - max(1, int(max_scan_bytes)))
        handle.seek(start)
        tail = handle.read()

    newline = tail.rfind(b"\n")
    fragment_start = start + newline + 1
    fragment = tail[newline + 1:]
    if start > 0 and newline < 0:
        raise JsonlTailError(
            f"last JSONL record exceeds {max_scan_bytes} bytes; refusing ambiguous repair: {path}"
        )
    try:
        parsed = json.loads(fragment)
        valid = isinstance(parsed, (dict, list))
    except Exception:
        valid = False
    if valid:
        with path.open("ab") as handle:
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {"status": "ADDED_NEWLINE", "removed_bytes": 0}

    removed = size - fragment_start
    with path.open("r+b") as handle:
        handle.truncate(fragment_start)
        handle.flush()
        os.fsync(handle.fileno())
    return {"status": "TRUNCATED_PARTIAL", "removed_bytes": removed}


def append_jsonl_records(path: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    repair = repair_jsonl_tail(path)
    encoded = [
        (json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str) + "\n").encode("utf-8")
        for row in rows
    ]
    if encoded:
        with path.open("ab") as handle:
            for row in encoded:
                handle.write(row)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    return {
        "path": str(path),
        "appended": len(encoded),
        "tail_repair": repair,
    }


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
