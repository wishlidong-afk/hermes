from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


_SCHEMA_VERSION = "hermes-history-promotion-v1"
_TRANSACTION_DIR = ".history_transactions"


class HistoryPromotionTransaction:
    """Recoverable multi-file promotion for canonical history updates."""

    def __init__(
        self,
        history_root: Path,
        *,
        allowed_roots: Iterable[Path],
        operation_id: str | None = None,
    ) -> None:
        self.history_root = Path(history_root).resolve()
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        if self.history_root not in self.allowed_roots:
            raise ValueError("history_root must be one of the allowed transaction roots")
        self.operation_id = str(operation_id or uuid4().hex)
        if not self.operation_id or Path(self.operation_id).name != self.operation_id:
            raise ValueError("invalid history transaction operation_id")
        self.transactions_root = self.history_root / _TRANSACTION_DIR
        self.transaction_dir = self.transactions_root / self.operation_id
        self.manifest_path = self.transaction_dir / "manifest.json"
        self._entries: list[dict[str, Any]] = []
        self._state = "STAGING"

    def stage_bytes(self, target: Path, content: bytes) -> None:
        self._require_state("STAGING")
        resolved = self._validated_target(target)
        if any(entry["target_path"] == str(resolved) for entry in self._entries):
            raise ValueError(f"history transaction target staged twice: {resolved}")
        self._ensure_dirs()
        index = len(self._entries)
        existed = resolved.is_file()
        mode = stat.S_IMODE(resolved.stat().st_mode) if existed else 0o644
        backup = self.transaction_dir / "backups" / f"{index:04d}.bak"
        if existed:
            _durable_write(backup, resolved.read_bytes(), mode=0o600)
        staged = self.transaction_dir / "staged" / f"{index:04d}.new"
        _durable_write(staged, bytes(content), mode=mode)
        self._entries.append(
            {
                "target_path": str(resolved),
                "staged_path": str(staged),
                "staged_sha256": _sha256_bytes(content),
                "backup_path": str(backup) if existed else None,
                "backup_sha256": _sha256_file(backup) if existed else None,
                "existed": existed,
                "mode": mode,
                "promote": True,
            }
        )

    def track_path(self, target: Path) -> None:
        """Include a directly-written sidecar in rollback without promoting it."""
        self._require_state("STAGING")
        resolved = self._validated_target(target)
        if any(entry["target_path"] == str(resolved) for entry in self._entries):
            return
        self._ensure_dirs()
        index = len(self._entries)
        existed = resolved.is_file()
        mode = stat.S_IMODE(resolved.stat().st_mode) if existed else 0o644
        backup = self.transaction_dir / "backups" / f"{index:04d}.bak"
        if existed:
            _durable_write(backup, resolved.read_bytes(), mode=0o600)
        self._entries.append(
            {
                "target_path": str(resolved),
                "staged_path": None,
                "staged_sha256": None,
                "backup_path": str(backup) if existed else None,
                "backup_sha256": _sha256_file(backup) if existed else None,
                "existed": existed,
                "mode": mode,
                "promote": False,
            }
        )

    def prepare(self) -> None:
        self._require_state("STAGING")
        self._ensure_dirs()
        self._state = "PREPARED"
        self.write_manifest(self._manifest_payload())

    def promote(self) -> None:
        self._require_state("PREPARED")
        self._state = "PROMOTING"
        self.write_manifest(self._manifest_payload())
        for entry in self._entries:
            if not entry["promote"]:
                continue
            staged = Path(str(entry["staged_path"]))
            if not staged.is_file() or _sha256_file(staged) != entry["staged_sha256"]:
                raise RuntimeError(f"staged history candidate changed: {staged}")
            target = self._validated_target(Path(entry["target_path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            os.chmod(target, int(entry["mode"]))
            _fsync_dir(target.parent)

    def mark_committed(self, *, cleanup: bool = True) -> None:
        self._require_state("PROMOTING")
        self._state = "COMMITTED"
        self.write_manifest(self._manifest_payload())
        if cleanup:
            self._cleanup()

    def rollback(self) -> None:
        manifest = self._manifest_payload()
        _restore_entries(manifest["entries"], self.allowed_roots)
        self._cleanup()
        self._state = "ROLLED_BACK"

    def abort(self) -> None:
        if self._state in {"PROMOTING", "COMMITTED"}:
            self.rollback()
        else:
            self._cleanup()
            self._state = "ABORTED"

    def write_manifest(self, payload: dict[str, Any]) -> None:
        self._ensure_dirs()
        _durable_write(
            self.manifest_path,
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
            mode=0o600,
        )
        self._state = str(payload.get("state") or self._state)

    def _manifest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "operation_id": self.operation_id,
            "state": self._state,
            "history_root": str(self.history_root),
            "allowed_roots": [str(root) for root in self.allowed_roots],
            "entries": list(self._entries),
        }

    def _validated_target(self, target: Path) -> Path:
        resolved = Path(target).resolve()
        if not any(_is_relative_to(resolved, root) for root in self.allowed_roots):
            raise ValueError(f"history transaction target outside allowed roots: {resolved}")
        if _is_relative_to(resolved, self.transactions_root):
            raise ValueError("history transaction cannot target its own journal")
        return resolved

    def _require_state(self, expected: str) -> None:
        if self._state != expected:
            raise RuntimeError(
                f"history transaction state {self._state}; expected {expected}"
            )

    def _ensure_dirs(self) -> None:
        (self.transaction_dir / "staged").mkdir(parents=True, exist_ok=True)
        (self.transaction_dir / "backups").mkdir(parents=True, exist_ok=True)

    def _cleanup(self) -> None:
        if self.transaction_dir.exists():
            shutil.rmtree(self.transaction_dir)
            _fsync_dir(self.transactions_root)


def recover_history_transactions(
    history_root: Path,
    *,
    allowed_roots: Iterable[Path],
) -> list[str]:
    root = Path(history_root).resolve()
    roots = tuple(Path(item).resolve() for item in allowed_roots)
    transactions_root = root / _TRANSACTION_DIR
    if not transactions_root.exists():
        return []
    recovered: list[str] = []
    for transaction_dir in sorted(path for path in transactions_root.iterdir() if path.is_dir()):
        manifest_path = transaction_dir / "manifest.json"
        if not manifest_path.exists():
            shutil.rmtree(transaction_dir)
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _validate_manifest(manifest, transaction_dir, roots)
        if manifest["state"] != "COMMITTED":
            _restore_entries(manifest["entries"], roots)
            recovered.append(str(manifest["operation_id"]))
        shutil.rmtree(transaction_dir)
    _fsync_dir(transactions_root)
    return recovered


def _validate_manifest(
    manifest: dict[str, Any],
    transaction_dir: Path,
    allowed_roots: tuple[Path, ...],
) -> None:
    if manifest.get("schema_version") != _SCHEMA_VERSION:
        raise RuntimeError(f"unsupported history transaction manifest: {transaction_dir}")
    if manifest.get("operation_id") != transaction_dir.name:
        raise RuntimeError(f"history transaction operation id mismatch: {transaction_dir}")
    if manifest.get("state") not in {"PREPARED", "PROMOTING", "COMMITTED"}:
        raise RuntimeError(f"invalid history transaction state: {transaction_dir}")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError(f"invalid history transaction entries: {transaction_dir}")
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError(f"invalid history transaction entry: {transaction_dir}")
        target = Path(str(entry.get("target_path") or "")).resolve()
        if not any(_is_relative_to(target, root) for root in allowed_roots):
            raise RuntimeError(f"history transaction target escaped allowed roots: {target}")
        backup = entry.get("backup_path")
        if backup and not _is_relative_to(Path(str(backup)).resolve(), transaction_dir.resolve()):
            raise RuntimeError(f"history transaction backup escaped journal: {backup}")


def _restore_entries(entries: list[dict[str, Any]], allowed_roots: Iterable[Path]) -> None:
    roots = tuple(Path(root).resolve() for root in allowed_roots)
    failures: list[str] = []
    for entry in entries:
        target = Path(str(entry.get("target_path") or "")).resolve()
        if not any(_is_relative_to(target, root) for root in roots):
            failures.append(f"target outside allowed roots: {target}")
            continue
        try:
            if entry.get("existed"):
                backup = Path(str(entry.get("backup_path") or ""))
                expected = str(entry.get("backup_sha256") or "")
                if not backup.is_file() or _sha256_file(backup) != expected:
                    raise RuntimeError(f"history transaction backup changed: {backup}")
                _atomic_replace_bytes(target, backup.read_bytes(), int(entry.get("mode") or 0o644))
            else:
                target.unlink(missing_ok=True)
                _fsync_dir(target.parent)
        except BaseException as exc:
            failures.append(f"{target}: {exc!r}")
    if failures:
        raise RuntimeError("history transaction rollback failed: " + "; ".join(failures))


def _atomic_replace_bytes(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.rollback.")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _durable_write(path: Path, content: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _fsync_dir(path: Path) -> None:
    if not Path(path).exists():
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(bytes(content)).hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
