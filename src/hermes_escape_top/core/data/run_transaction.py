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
import hashlib
import stat
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Literal, Mapping, Optional

from ..safe_io import assert_pipeline_lease
from .transaction_evidence import SCHEMA_V2, checked_path, validate_input_evidence, validate_inventory
from .sqlite_snapshot import copy_sqlite_snapshot


SCHEMA_VERSION = "hermes-score-run-transaction-v1"
_JOURNAL_DIR = ".score_run_transactions"
_ACTIVE_FILE = "active.json"
_TERMINAL_STATUSES = {"COMMITTED", "ROLLED_BACK", "RECOVERED_ROLLBACK"}
_V2_LEGACY_GUARD = "V2_REQUIRES_UPGRADED_WRITER"


class PersistenceRecoveryError(RuntimeError):
    """Raised when an incomplete score run cannot be restored deterministically."""


@dataclass(frozen=True)
class ScoreRunTransaction:
    run_id: str
    archive_dir: Path
    capture_id: Optional[str] = None


def pending_score_run_transaction(archive_dir: Path) -> Optional[Dict[str, Any]]:
    """Return the active transaction record, or ``None`` when no run is pending."""
    active_path = _checked_journal_path(archive_dir, Path(_JOURNAL_DIR) / _ACTIVE_FILE)
    if not active_path.exists():
        return None
    active = _read_json(active_path, label="active score transaction")
    run_id = str(active.get("run_id") or "")
    if active.get("schema_version") == SCHEMA_V2:
        if run_id != _V2_LEGACY_GUARD:
            raise PersistenceRecoveryError("invalid v2 active pointer guard")
        run_id = str(active.get("v2_run_id") or "")
    elif active.get("schema_version") not in {None, SCHEMA_VERSION}:
        raise PersistenceRecoveryError("unknown active score transaction schema")
    if not run_id:
        raise PersistenceRecoveryError(f"active score transaction has no run_id: {active_path}")
    record = load_score_run_transaction(archive_dir, run_id)
    if active.get("schema_version") == SCHEMA_V2 and record.get("schema_version") != SCHEMA_V2:
        raise PersistenceRecoveryError("v2 active pointer/manifest schema mismatch")
    return record


def load_score_run_transaction(archive_dir: Path, run_id: str) -> Dict[str, Any]:
    path = _manifest_path(archive_dir, run_id)
    record = _read_json(path, label=f"score transaction {run_id}")
    if str(record.get("run_id") or "") != str(run_id):
        raise PersistenceRecoveryError(f"score transaction run_id mismatch: {path}")
    if record.get("schema_version") not in {None, SCHEMA_VERSION, SCHEMA_V2}:
        raise PersistenceRecoveryError("unknown score transaction schema")
    if record.get("schema_version") == SCHEMA_V2:
        try:
            validate_inventory(record)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise PersistenceRecoveryError(f"invalid v2 transaction inventory: {exc}") from exc
    return record


def recover_incomplete_score_run(archive_dir: Path, *, _lease: Any) -> Optional[Dict[str, Any]]:
    """Restore a non-terminal active run before a new score run reads state.

    The caller must hold the pipeline mutex. If a committed transaction left only
    a stale active pointer, the pointer is cleared without rolling data back.
    """
    archive_dir = Path(archive_dir).resolve()
    assert_pipeline_lease(_lease, path=archive_dir / ".pipeline.lock")
    active_path = _checked_journal_path(archive_dir, Path(_JOURNAL_DIR) / _ACTIVE_FILE)
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
    evidence_artifacts: Optional[Iterable[Path]] = None,
    capture_id: Optional[str] = None,
) -> "_ScoreRunTransactionContext":
    """Snapshot ``artifacts`` and commit or restore them as one score-run unit.

    Recovery is intentionally separate: the pipeline invokes it immediately after
    validating its lock lease and before reading any state. This avoids hiding an
    unsafe recovery call inside code that cannot prove lock ownership.
    """
    return _ScoreRunTransactionContext(archive_dir, artifacts, metadata, _lease, evidence_artifacts, capture_id)


def bind_score_run_inputs(
    transaction: ScoreRunTransaction, *, manifest_path: Path, expected_manifest_sha256: str,
    decision_id: str, input_hash: str, _lease: Any,
) -> None:
    """Bind an explicit v2 capture to the pending journal; not a scoring hook."""
    archive = transaction.archive_dir
    assert_pipeline_lease(_lease, path=archive / ".pipeline.lock")
    record = pending_score_run_transaction(archive)
    if (record is None or record.get("schema_version") != SCHEMA_V2 or record["status"] != "PENDING"
            or record["run_id"] != transaction.run_id or record["capture_id"] != transaction.capture_id):
        raise ValueError("input binding requires the matching pending v2 transaction")
    if record.get("input_binding"):
        raise ValueError("transaction inputs are already bound")
    relative = Path(manifest_path).resolve().relative_to(archive.parent).as_posix()
    if Path(manifest_path).is_symlink():
        raise ValueError("transaction evidence symlink is not allowed")
    record["input_binding"] = {"manifest_path": relative, "manifest_sha256": expected_manifest_sha256,
                               "decision_id": decision_id, "input_hash": input_hash}
    for row in record["artifacts"]:
        if row["role"] == "DECISION_INPUT_EVIDENCE":
            path = checked_path(archive.parent, row["path"])
            row["after_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    validate_input_evidence(record, archive.parent)
    _write_manifest(archive, record)


def export_score_run_before_images(transaction: ScoreRunTransaction, *, _lease: Any) -> Dict[str, Any]:
    """Copy frozen v2 before images to explicitly registered capture files.

    The caller registers ``pre_state/<business path>`` for each previously
    present business file before entering the transaction. This inventory is
    not a decision-input binding or proof that the scorer consumed these files.
    """
    archive = transaction.archive_dir
    assert_pipeline_lease(_lease, path=archive / ".pipeline.lock")
    record = pending_score_run_transaction(archive)
    if (record is None or record.get("schema_version") != SCHEMA_V2 or record["status"] != "PENDING"
            or record["run_id"] != transaction.run_id or record["capture_id"] != transaction.capture_id):
        raise ValueError("before-image export requires the matching pending v2 transaction")
    prefix = f"archive/decision_inputs/{record['capture_id']}/pre_state/"
    rows = [row for row in record["artifacts"] if row["role"] == "BUSINESS"]
    registered = {row["path"] for row in record["artifacts"]
                  if row["role"] == "DECISION_INPUT_EVIDENCE" and row["path"].startswith(prefix)}
    expected = {prefix + row["path"] for row in rows if row["existed"]}
    if registered != expected:
        raise ValueError("before-image evidence registration mismatch")
    artifacts: Dict[str, Any] = {}
    copies = []
    for row in rows:
        expected_format = "SQLITE_BACKUP" if Path(row["path"]).suffix == ".sqlite" else "BYTES"
        mode = row.get("before_mode")
        if (row.get("snapshot_format") != expected_format
                or (row["existed"] and (type(mode) is not int or not 0 <= mode <= 0o777))
                or (not row["existed"] and (mode is not None or row.get("before_sha256") is not None))):
            raise ValueError("invalid transaction backup metadata")
        entry = {"availability": "ABSENT", "path": None, "sha256": None,
                 "snapshot_format": expected_format, "before_mode": mode}
        if row["existed"]:
            source = checked_path(_backup_root(archive, transaction.run_id), row["path"])
            if hashlib.sha256(source.read_bytes()).hexdigest() != row.get("before_sha256"):
                raise PersistenceRecoveryError("transaction backup digest mismatch")
            target = checked_path(archive.parent, prefix + row["path"])
            if target.exists():
                raise ValueError("before-image evidence already exists")
            copies.append((source, target, row["before_sha256"]))
            entry.update(availability="PRESENT", path=prefix + row["path"], sha256=row["before_sha256"])
        artifacts[row["path"]] = entry
    created = []
    try:
        for source, target, expected_digest in copies:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with target.open("xb") as output:
                created.append(target)
                with source.open("rb") as original:
                    shutil.copyfileobj(original, output)
                output.flush()
                os.fsync(output.fileno())
            target.chmod(0o400)
            if hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
                raise PersistenceRecoveryError("exported before-image digest mismatch")
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return {"schema_version": "hermes-score-before-images-v1", "capture_mode": "V2_PREPARED_BEFORE_IMAGES",
            "binding": {"run_id": record["run_id"], "capture_id": record["capture_id"],
                        "as_of": record["metadata"]["as_of"]}, "artifacts": artifacts}


class _ScoreRunTransactionContext:
    def __init__(
        self,
        archive_dir: Path,
        artifacts: Iterable[Path],
        metadata: Mapping[str, Any],
        lease: Any,
        evidence_artifacts: Optional[Iterable[Path]],
        capture_id: Optional[str],
    ) -> None:
        self.archive_dir = Path(archive_dir).resolve()
        self.artifacts = tuple(Path(path) for path in artifacts)
        self.metadata = dict(metadata)
        self.lease = lease
        self.evidence_artifacts = None if evidence_artifacts is None else tuple(evidence_artifacts)
        self.capture_id = capture_id
        if (capture_id is None) != (evidence_artifacts is None):
            raise ValueError("capture_id and evidence_artifacts must be provided together")
        self.record: Optional[Dict[str, Any]] = None
        self.transaction: Optional[ScoreRunTransaction] = None

    def __enter__(self) -> ScoreRunTransaction:
        assert_pipeline_lease(self.lease, path=self.archive_dir / ".pipeline.lock")
        if pending_score_run_transaction(self.archive_dir) is not None:
            raise PersistenceRecoveryError("an incomplete score transaction must be recovered first")
        self.record = _prepare_transaction(
            self.archive_dir, self.artifacts, self.metadata,
            evidence_artifacts=self.evidence_artifacts, capture_id=self.capture_id,
        )
        self.transaction = ScoreRunTransaction(
            run_id=str(self.record["run_id"]), archive_dir=self.archive_dir, capture_id=self.capture_id,
        )
        return self.transaction

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> Literal[False]:
        assert_pipeline_lease(self.lease, path=self.archive_dir / ".pipeline.lock")
        if self.record is None or self.transaction is None:
            raise PersistenceRecoveryError("score transaction context was not entered")
        if exc is not None:
            self._rollback(exc)
            return False
        if self.capture_id is not None:
            try:
                latest = load_score_run_transaction(self.archive_dir, self.transaction.run_id)
                validate_input_evidence(latest, self.archive_dir.parent)
                for row in latest["artifacts"]:
                    path = checked_path(self.archive_dir.parent, row["path"])
                    if row["role"] == "DECISION_INPUT_EVIDENCE":
                        path.chmod(0o400)
                    _sync_file(path)
                    if path.suffix == ".sqlite":
                        for suffix in ("-wal", "-journal"):
                            sidecar = checked_path(self.archive_dir.parent, row["path"] + suffix)
                            if sidecar.exists():
                                _sync_file(sidecar)
                self.record = latest
            except BaseException as validation_exc:
                self._rollback(validation_exc)
                raise
        committed = dict(self.record)
        committed.update({"status": "COMMITTED", "committed_at": _now()})
        try:
            _write_manifest(self.archive_dir, committed)
        except BaseException as commit_exc:
            if self.capture_id is not None:
                try:
                    observed = load_score_run_transaction(self.archive_dir, self.transaction.run_id)
                except BaseException as read_exc:
                    raise PersistenceRecoveryError("commit outcome unknown; journal retained for inspection") from read_exc
                if observed["status"] != "COMMITTED":
                    self._rollback(commit_exc)
            raise
        _clear_active(_journal_root(self.archive_dir) / _ACTIVE_FILE)
        _remove_backups(self.archive_dir, self.transaction.run_id)
        return False

    def _rollback(self, exc: BaseException) -> None:
        transaction = self.transaction
        if transaction is None:
            raise PersistenceRecoveryError("score transaction context was not entered")
        try:
            assert self.record is not None
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
            _remove_backups(self.archive_dir, transaction.run_id)
        except BaseException as rollback_exc:
            raise PersistenceRecoveryError(
                f"score transaction {transaction.run_id} failed and rollback failed: {rollback_exc}"
            ) from exc


def _prepare_transaction(
    archive_dir: Path,
    artifacts: Iterable[Path],
    metadata: Mapping[str, Any],
    *, evidence_artifacts: Optional[Iterable[Path]] = None, capture_id: Optional[str] = None,
) -> Dict[str, Any]:
    root = _journal_root(archive_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    data_root = archive_dir.parent.resolve()
    rows = []
    seen = set()
    inventory = [(path, "BUSINESS") for path in artifacts]
    inventory.extend((path, "DECISION_INPUT_EVIDENCE") for path in evidence_artifacts or ())
    for raw_path, role in inventory:
        if capture_id is not None:
            _reject_symlinks(Path(raw_path).absolute(), data_root)
        target = Path(raw_path).resolve()
        try:
            relative = target.relative_to(data_root)
        except ValueError as exc:
            raise ValueError(f"transaction artifact is outside data root: {target}") from exc
        key = relative.as_posix()
        if key in seen:
            if capture_id is not None:
                raise ValueError("duplicate transaction artifact")
            continue
        seen.add(key)
        if target.exists() and not target.is_file():
            raise ValueError(f"transaction artifact is not a regular file: {target}")
        row: Dict[str, Any] = {"path": key, "existed": target.exists()}
        if capture_id is not None:
            row["role"] = role
            row["before_mode"] = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
            row["snapshot_format"] = "SQLITE_BACKUP" if target.suffix == ".sqlite" else "BYTES"
            if target.suffix == ".sqlite":
                sidecars = [Path(f"{target}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
                if any(path.is_symlink() for path in sidecars):
                    raise ValueError("transaction SQLite sidecar symlink is not allowed")
                if not target.exists() and any(path.exists() for path in sidecars):
                    raise ValueError("transaction orphan SQLite sidecar")
        rows.append(row)

    record: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION if capture_id is None else SCHEMA_V2,
        "run_id": run_id,
        "status": "PREPARING",
        "started_at": _now(),
        "metadata": dict(metadata),
        "artifacts": rows,
    }
    if capture_id is not None:
        record["capture_id"] = capture_id
        validate_inventory(record)
        capture_root = checked_path(data_root, f"archive/decision_inputs/{capture_id}")
        if capture_root.exists():
            raise ValueError("capture directory already exists")
        _run_root(archive_dir, run_id).mkdir(parents=True, mode=0o700)
    _write_manifest(archive_dir, record)
    try:
        for row in rows:
            if row["existed"]:
                source = data_root / row["path"]
                backup = _backup_root(archive_dir, run_id) / row["path"]
                if capture_id is not None and row["snapshot_format"] == "SQLITE_BACKUP":
                    row["before_sha256"] = copy_sqlite_snapshot(source, backup)["sha256"]
                else:
                    _clone_or_copy(source, backup)
                if capture_id is not None and "before_sha256" not in row:
                    row["before_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
                if capture_id is not None:
                    backup.chmod(0o400)
                    _sync_file(backup)
        record["status"] = "PREPARED"
        _write_manifest(archive_dir, record)
        pointer = {"run_id": run_id, "started_at": record["started_at"]}
        if capture_id is not None:
            pointer.update({"schema_version": SCHEMA_V2, "run_id": _V2_LEGACY_GUARD, "v2_run_id": run_id})
        _atomic_write_json(root / _ACTIVE_FILE, pointer)
        record["status"] = "PENDING"
        _write_manifest(archive_dir, record)
        if capture_id is not None:
            capture_root.mkdir(parents=True, mode=0o700)
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
    if record.get("schema_version") == SCHEMA_V2:
        validate_inventory(record)
        for row in record["artifacts"]:
            checked_path(data_root, row["path"])
            if row["existed"]:
                expected_format = "SQLITE_BACKUP" if Path(row["path"]).suffix == ".sqlite" else "BYTES"
                if (not isinstance(row.get("before_mode"), int) or not 0 <= row["before_mode"] <= 0o777
                        or row.get("snapshot_format") != expected_format):
                    raise PersistenceRecoveryError("invalid transaction backup metadata")
                backup = checked_path(_backup_root(archive_dir, run_id), row["path"])
                if hashlib.sha256(backup.read_bytes()).hexdigest() != row.get("before_sha256"):
                    raise PersistenceRecoveryError("transaction backup digest mismatch")
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
            if record.get("schema_version") == SCHEMA_V2:
                target.chmod(row["before_mode"])
        else:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        _fsync_dir(target.parent)
    if record.get("schema_version") == SCHEMA_V2:
        capture_root = checked_path(data_root, f"archive/decision_inputs/{record['capture_id']}")
        if capture_root.exists():
            shutil.rmtree(capture_root)
            _fsync_dir(capture_root.parent)


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    _fsync_dir(path.parent)


def _reject_symlinks(path: Path, root: Path) -> None:
    alias = root if path.is_relative_to(root) else next(
        (parent for parent in reversed(path.parents) if parent.resolve() == root), None,
    )
    if alias is None:
        raise ValueError(f"transaction artifact is outside data root: {path}")
    relative = path.relative_to(alias)
    if ".." in relative.parts:
        raise ValueError("invalid transaction artifact path")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"transaction artifact symlink is not allowed: {current}")


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
    if path.is_symlink():
        raise PersistenceRecoveryError(f"score transaction journal symlink is not allowed: {path}")
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
    return _checked_journal_path(archive_dir, Path(_JOURNAL_DIR))


def _checked_journal_path(archive_dir: Path, relative: Path) -> Path:
    try:
        return checked_path(Path(archive_dir).resolve(), relative.as_posix())
    except ValueError as exc:
        raise PersistenceRecoveryError(f"score transaction journal symlink or path invalid: {relative}") from exc


def _run_root(archive_dir: Path, run_id: str) -> Path:
    if (not isinstance(run_id, str) or not run_id
            or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in run_id)):
        raise PersistenceRecoveryError("invalid score transaction run_id")
    return _checked_journal_path(archive_dir, Path(_JOURNAL_DIR) / "runs" / run_id)


def _manifest_path(archive_dir: Path, run_id: str) -> Path:
    relative = _run_root(archive_dir, run_id).relative_to(Path(archive_dir).resolve())
    return _checked_journal_path(archive_dir, relative / "manifest.json")


def _backup_root(archive_dir: Path, run_id: str) -> Path:
    relative = _run_root(archive_dir, run_id).relative_to(Path(archive_dir).resolve())
    return _checked_journal_path(archive_dir, relative / "backups")


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
