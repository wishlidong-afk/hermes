"""Recoverable transaction journal for one multi-store score run.

SQLite can make each database atomic, but Hermes writes four databases, two
JSONL ledgers, and one dated soft-input snapshot per score run. This module
records one run id, snapshots all seven files before the first write, and
publishes ``COMMITTED`` only after every write
returns. A normal exception restores immediately; after a process kill, the next
lock-owning run calls :func:`recover_incomplete_score_run` before reading state.

The pipeline mutex remains the concurrency boundary. This journal supplies crash
recovery across files; it is not a replacement for the mutex.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ..safe_io import assert_pipeline_lease


SCHEMA_VERSION = "hermes-score-run-transaction-v1"
_JOURNAL_DIR = ".score_run_transactions"
_ACTIVE_FILE = "active.json"
_TERMINAL_STATUSES = {"COMMITTED", "ROLLED_BACK", "RECOVERED_ROLLBACK"}


class PersistenceRecoveryError(RuntimeError):
    """Raised when an incomplete score run cannot be restored deterministically."""


@dataclass(frozen=True)
class ScoreRunTransaction:
    run_id: str
    archive_dir: Path


def pending_score_run_transaction(archive_dir: Path) -> Optional[Dict[str, Any]]:
    """Return the active transaction record, or ``None`` when no run is pending."""
    active_path = _journal_root(archive_dir) / _ACTIVE_FILE
    if not active_path.exists():
        return None
    active = _read_json(active_path, label="active score transaction")
    run_id = str(active.get("run_id") or "")
    if not run_id:
        raise PersistenceRecoveryError(f"active score transaction has no run_id: {active_path}")
    return load_score_run_transaction(archive_dir, run_id)


def load_score_run_transaction(archive_dir: Path, run_id: str) -> Dict[str, Any]:
    path = _manifest_path(archive_dir, run_id)
    record = _read_json(path, label=f"score transaction {run_id}")
    if str(record.get("run_id") or "") != str(run_id):
        raise PersistenceRecoveryError(f"score transaction run_id mismatch: {path}")
    return record


def recover_incomplete_score_run(archive_dir: Path, *, _lease: Any) -> Optional[Dict[str, Any]]:
    """Restore a non-terminal active run before a new score run reads state.

    The caller must hold the pipeline mutex. If a committed transaction left only
    a stale active pointer, the pointer is cleared without rolling data back.
    """
    archive_dir = Path(archive_dir).resolve()
    assert_pipeline_lease(_lease, path=archive_dir / ".pipeline.lock")
    active_path = _journal_root(archive_dir) / _ACTIVE_FILE
    if not active_path.exists():
        return None
    record = pending_score_run_transaction(archive_dir)
    if record is None:
        return None
    status = str(record.get("status") or "")
    if status in _TERMINAL_STATUSES:
        _clear_active(active_path)
        _remove_backups(archive_dir, str(record["run_id"]))
        return None
    try:
        _restore_artifacts(archive_dir, record)
        record = dict(record)
        record.update(
            {
                "status": "RECOVERED_ROLLBACK",
                "recovered_at": _now(),
            }
        )
        _write_manifest(archive_dir, record)
        _clear_active(active_path)
        _remove_backups(archive_dir, str(record["run_id"]))
        return record
    except BaseException as exc:
        raise PersistenceRecoveryError(
            f"cannot recover incomplete score transaction {record.get('run_id')}: {exc}"
        ) from exc


def score_run_transaction(
    archive_dir: Path,
    artifacts: Iterable[Path],
    *,
    metadata: Mapping[str, Any],
    _lease: Any,
) -> "_ScoreRunTransactionContext":
    """Snapshot ``artifacts`` and commit or restore them as one score-run unit.

    Recovery is intentionally separate: the pipeline invokes it immediately after
    validating its lock lease and before reading any state. This avoids hiding an
    unsafe recovery call inside code that cannot prove lock ownership.
    """
    return _ScoreRunTransactionContext(archive_dir, artifacts, metadata, _lease)


class _ScoreRunTransactionContext:
    def __init__(
        self,
        archive_dir: Path,
        artifacts: Iterable[Path],
        metadata: Mapping[str, Any],
        lease: Any,
    ) -> None:
        self.archive_dir = Path(archive_dir).resolve()
        self.artifacts = tuple(Path(path) for path in artifacts)
        self.metadata = dict(metadata)
        self.lease = lease
        self.record: Optional[Dict[str, Any]] = None
        self.transaction: Optional[ScoreRunTransaction] = None

    def __enter__(self) -> ScoreRunTransaction:
        assert_pipeline_lease(self.lease, path=self.archive_dir / ".pipeline.lock")
        if pending_score_run_transaction(self.archive_dir) is not None:
            raise PersistenceRecoveryError("an incomplete score transaction must be recovered first")
        self.record = _prepare_transaction(self.archive_dir, self.artifacts, self.metadata)
        self.transaction = ScoreRunTransaction(
            run_id=str(self.record["run_id"]), archive_dir=self.archive_dir
        )
        return self.transaction

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if self.record is None or self.transaction is None:
            raise PersistenceRecoveryError("score transaction context was not entered")
        if exc is not None:
            self._rollback(exc)
            return False
        committed = dict(self.record)
        committed.update({"status": "COMMITTED", "committed_at": _now()})
        _write_manifest(self.archive_dir, committed)
        _clear_active(_journal_root(self.archive_dir) / _ACTIVE_FILE)
        _remove_backups(self.archive_dir, self.transaction.run_id)
        return False

    def _rollback(self, exc: BaseException) -> None:
        try:
            assert self.record is not None
            assert self.transaction is not None
            _restore_artifacts(self.archive_dir, self.record)
            failed = dict(self.record)
            failed.update(
                {
                    "status": "ROLLED_BACK",
                    "rolled_back_at": _now(),
                    "failure_type": type(exc).__name__,
                    "failure": str(exc)[:2000],
                }
            )
            _write_manifest(self.archive_dir, failed)
            _clear_active(_journal_root(self.archive_dir) / _ACTIVE_FILE)
            _remove_backups(self.archive_dir, self.transaction.run_id)
        except BaseException as rollback_exc:
            raise PersistenceRecoveryError(
                f"score transaction {self.transaction.run_id} failed and rollback failed: {rollback_exc}"
            ) from exc


def _prepare_transaction(
    archive_dir: Path,
    artifacts: Iterable[Path],
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    root = _journal_root(archive_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    data_root = archive_dir.parent.resolve()
    rows = []
    seen = set()
    for raw_path in artifacts:
        target = Path(raw_path).resolve()
        try:
            relative = target.relative_to(data_root)
        except ValueError as exc:
            raise ValueError(f"transaction artifact is outside data root: {target}") from exc
        key = relative.as_posix()
        if key in seen:
            continue
        seen.add(key)
        if target.exists() and not target.is_file():
            raise ValueError(f"transaction artifact is not a regular file: {target}")
        rows.append({"path": key, "existed": target.exists()})

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "status": "PREPARING",
        "started_at": _now(),
        "metadata": dict(metadata),
        "artifacts": rows,
    }
    _write_manifest(archive_dir, record)
    try:
        for row in rows:
            if row["existed"]:
                source = data_root / row["path"]
                backup = _backup_root(archive_dir, run_id) / row["path"]
                _clone_or_copy(source, backup)
        record["status"] = "PREPARED"
        _write_manifest(archive_dir, record)
        _atomic_write_json(root / _ACTIVE_FILE, {"run_id": run_id, "started_at": record["started_at"]})
        record["status"] = "PENDING"
        _write_manifest(archive_dir, record)
        return record
    except BaseException:
        active_path = root / _ACTIVE_FILE
        if active_path.exists():
            _clear_active(active_path)
        _remove_backups(archive_dir, run_id)
        raise


def _restore_artifacts(archive_dir: Path, record: Mapping[str, Any]) -> None:
    data_root = Path(archive_dir).resolve().parent
    run_id = str(record.get("run_id") or "")
    if not run_id:
        raise PersistenceRecoveryError("transaction record has no run_id")
    for row in record.get("artifacts") or []:
        relative = Path(str(row.get("path") or ""))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise PersistenceRecoveryError(f"invalid transaction artifact path: {relative}")
        target = data_root / relative
        _remove_sqlite_sidecars(target)
        if bool(row.get("existed")):
            backup = _backup_root(archive_dir, run_id) / relative
            if not backup.is_file():
                raise PersistenceRecoveryError(f"missing transaction backup: {backup}")
            _replace_from_backup(backup, target)
        else:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        _fsync_dir(target.parent)


def _replace_from_backup(backup: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".restore"
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        shutil.copy2(backup, temp)
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _clone_or_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    clonefile = getattr(os, "clonefile", None)
    if clonefile is not None:
        try:
            clonefile(source, target)
            return
        except OSError:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
    clone = subprocess.run(
        ["/bin/cp", "-c", str(source), str(target)],
        capture_output=True,
        check=False,
    )
    if clone.returncode == 0:
        return
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    shutil.copy2(source, target)


def _remove_sqlite_sidecars(path: Path) -> None:
    if path.suffix != ".sqlite":
        return
    for suffix in ("-journal", "-wal", "-shm"):
        try:
            Path(f"{path}{suffix}").unlink()
        except FileNotFoundError:
            pass


def _write_manifest(archive_dir: Path, record: Mapping[str, Any]) -> None:
    _atomic_write_json(_manifest_path(archive_dir, str(record["run_id"])), dict(record))


def _read_json(path: Path, *, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PersistenceRecoveryError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PersistenceRecoveryError(f"{label} is not a JSON object: {path}")
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_dir(path.parent)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def _clear_active(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_dir(path.parent)


def _remove_backups(archive_dir: Path, run_id: str) -> None:
    backup = _backup_root(archive_dir, run_id)
    if backup.exists():
        shutil.rmtree(backup)


def _journal_root(archive_dir: Path) -> Path:
    return Path(archive_dir).resolve() / _JOURNAL_DIR


def _run_root(archive_dir: Path, run_id: str) -> Path:
    return _journal_root(archive_dir) / "runs" / str(run_id)


def _manifest_path(archive_dir: Path, run_id: str) -> Path:
    return _run_root(archive_dir, run_id) / "manifest.json"


def _backup_root(archive_dir: Path, run_id: str) -> Path:
    return _run_root(archive_dir, run_id) / "backups"


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
