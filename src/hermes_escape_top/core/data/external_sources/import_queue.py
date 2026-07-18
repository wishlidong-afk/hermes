from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


QUEUE_STATES = ("inbox", "processed", "rejected")


def queue_import_candidates(
    source_id: str,
    archive_dir: Path,
    candidates: Iterable[Path],
    *,
    processed_hashes: set[str],
) -> list[Path]:
    """Stage unseen official files without mutating their discovery location."""
    root = _queue_root(archive_dir, source_id)
    for state in QUEUE_STATES:
        (root / state).mkdir(parents=True, exist_ok=True)

    terminal_hashes = _state_hashes(root / "processed") | _state_hashes(root / "rejected")
    seen = set(processed_hashes) | terminal_hashes
    queued: list[Path] = []
    for path in _content_files(root / "inbox"):
        digest = _content_hash_from_name(path)
        if digest and digest not in seen:
            queued.append(path)
            seen.add(digest)

    for candidate in candidates:
        source = Path(candidate).expanduser()
        try:
            content = source.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen:
            continue
        suffix = source.suffix.lower() or ".bin"
        destination = root / "inbox" / f"{digest}{suffix}"
        _atomic_write_bytes(destination, content)
        _write_metadata(
            destination,
            {
                "source_id": source_id,
                "sha256": digest,
                "original_path": str(source),
                "staged_at": _now(),
                "status": "INBOX",
            },
        )
        queued.append(destination)
        seen.add(digest)
    return queued


def verified_import_content(path: Path) -> bytes:
    """Read one queue artifact once and bind its bytes to its filename hash."""
    source = Path(path)
    expected = _expected_hash_from_name(source)
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ValueError(f"import artifact is unreadable: {source}") from exc
    if expected is None or hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"import artifact content hash does not match filename: {source}")
    return content


def finalize_import(
    path: Path,
    *,
    status: str,
    expected_content: bytes | None = None,
) -> Path:
    """Move one inbox artifact to its terminal content-addressed state."""
    source = Path(path)
    if source.parent.name != "inbox":
        raise ValueError(f"import artifact is not in a queue inbox: {source}")
    content = (
        verified_import_content(source)
        if expected_content is None
        else bytes(expected_content)
    )
    expected = _expected_hash_from_name(source)
    if expected is None or hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"verified import content does not match filename: {source}")
    state = "processed" if str(status).upper() == "OK" else "rejected"
    destination = source.parent.parent / state / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)

    source_meta = _metadata_path(source)
    metadata: dict[str, object] = {}
    if source_meta.exists():
        try:
            metadata = json.loads(source_meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metadata = {}
    if expected_content is None:
        os.replace(source, destination)
    else:
        _atomic_write_bytes(destination, content)
        source.unlink(missing_ok=True)
    source_meta.unlink(missing_ok=True)
    metadata.update(status=str(status).upper(), finalized_at=_now())
    _write_metadata(destination, metadata)
    return destination


def import_origin(path: Path) -> Path | None:
    metadata_path = _metadata_path(Path(path))
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = str(metadata.get("original_path") or "").strip()
    return Path(value) if value else None


def queued_import_files(source_id: str, archive_dir: Path) -> list[Path]:
    return _content_files(_queue_root(archive_dir, source_id) / "inbox")


def terminal_import_hashes(source_id: str, archive_dir: Path) -> set[str]:
    root = _queue_root(archive_dir, source_id)
    return _state_hashes(root / "processed") | _state_hashes(root / "rejected")


def _queue_root(archive_dir: Path, source_id: str) -> Path:
    return Path(archive_dir) / "external_import_queue" / str(source_id)


def _content_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and not path.name.endswith(".meta.json")),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )


def _state_hashes(directory: Path) -> set[str]:
    return {
        digest
        for path in _content_files(directory)
        if (digest := _content_hash_from_name(path))
    }


def _content_hash_from_name(path: Path) -> str | None:
    digest = _expected_hash_from_name(path)
    if digest is None:
        return None
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return digest if actual == digest else None


def _expected_hash_from_name(path: Path) -> str | None:
    digest = Path(path).name.split(".", 1)[0]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    return digest


def _metadata_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _write_metadata(path: Path, payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    _atomic_write_bytes(_metadata_path(path), text.encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
