"""Complete canonical bytes retained separately from decision identity."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..data.history_transaction import HistoryPromotionTransaction, _durable_write


_SCHEMA = "hermes-history-versions-v1"
_ROLE = "CANONICAL_FILE_VERSIONS_NOT_DECISION_BINDING"


def history_versions_root(history_root: Path) -> Path:
    history = Path(history_root).resolve()
    root = _contained(history.parent, history.parent / ".history_versions" / history.name)
    if root.is_relative_to(history):
        raise ValueError("version archive cannot be the canonical history root or inside it")
    return root


def _contained(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("history version path escaped its root")
    return resolved


class HistoryVersionRecorder:
    """Stage blobs and an index in the existing promotion transaction."""

    def __init__(self, transaction: HistoryPromotionTransaction):
        self.transaction = transaction
        self.root = history_versions_root(transaction.history_root)
        self.batch_id = uuid4().hex
        self.path = self.root / "batches" / f"{self.batch_id}.json"
        self.files: list[dict[str, Any]] = []
        self._staged_hashes: set[str] = set()

    def capture(self, symbol: str, target: Path, after: bytes, *, source_symbol: str) -> None:
        target = _contained(self.transaction.history_root, target)
        before = target.read_bytes() if target.is_file() else None
        self.files.append({
            "symbol": symbol,
            "filename": target.name,
            "source_symbol": source_symbol,
            "before_sha256": self._blob(before) if before is not None else None,
            "after_sha256": self._blob(after),
            "change": "CREATED" if before is None else "UNCHANGED" if before == after else "CHANGED",
        })

    def _blob(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = _contained(self.root, self.root / "blobs" / f"{digest}.csv")
        if path.exists():
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"history version blob mismatch: {digest}")
        elif digest not in self._staged_hashes:
            self.transaction.stage_bytes(path, content)
            self._staged_hashes.add(digest)
        return digest

    def stage_index(self) -> None:
        if not self.files:
            return
        payload = {
            "schema_version": _SCHEMA,
            "evidence_role": _ROLE,
            "batch_id": self.batch_id,
            "operation_id": self.transaction.operation_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "published_at": None,
            "files": self.files,
        }
        self.transaction.stage_bytes(
            _contained(self.root, self.path),
            (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode(),
        )

    def seal(self) -> None:
        for digest in self._staged_hashes:
            blob = _contained(self.root, self.root / "blobs" / f"{digest}.csv")
            if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                raise RuntimeError("promoted history version blob digest mismatch")
            blob.chmod(0o444)
        if self.files:
            _contained(self.root, self.path).chmod(0o444)


def restore_history_version(
    history_root: Path, batch_id: str, symbol: str, version: str, destination: Path,
) -> None:
    """Verify bytes and restore to a new caller-selected offline file only."""
    history = Path(history_root).resolve()
    if re.fullmatch(r"[a-f0-9]{32}", batch_id) is None or version not in {"before", "after"}:
        raise ValueError("invalid history version request")
    root = history_versions_root(history)
    index = _contained(root, root / "batches" / f"{batch_id}.json")
    payload = json.loads(index.read_bytes())
    if (payload.get("schema_version") != _SCHEMA or payload.get("batch_id") != batch_id
            or payload.get("evidence_role") != _ROLE):
        raise ValueError("invalid history version index")
    operation = payload.get("operation_id")
    if not isinstance(operation, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", operation) is None:
        raise ValueError("invalid history version operation")
    journal = _contained(history, history / ".history_transactions" / operation / "manifest.json")
    if journal.exists():
        transaction = json.loads(journal.read_bytes())
        if (transaction.get("schema_version") != "hermes-history-promotion-v1"
                or transaction.get("history_root") != str(history)
                or transaction.get("operation_id") != operation
                or transaction.get("state") != "COMMITTED"):
            raise RuntimeError("history version batch is not committed")
    entries = payload.get("files")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("invalid history version entries")
    matches = [row for row in entries if row.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("history version symbol missing or ambiguous")
    digest = matches[0].get(f"{version}_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise ValueError("history version is unavailable")
    blob = _contained(root, root / "blobs" / f"{digest}.csv")
    content = blob.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError("history version blob digest mismatch")
    output = Path(destination)
    if (output.resolve().is_relative_to(history) or output.resolve().is_relative_to(root)
            or output.exists() or output.is_symlink()):
        raise ValueError("restore requires a new offline file outside canonical history")
    _durable_write(output, content, mode=0o600)
