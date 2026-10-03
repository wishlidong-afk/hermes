"""Restore authenticated v2 before images only into a new offline directory."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import UUID

from ..data.sqlite_snapshot import sqlite_state_hash
from ..data.store import LocalStore
from ..data.transaction_evidence import SCHEMA_V2, checked_path, validate_input_evidence, validate_inventory
from .decision_inputs import _check_state_json, _destination, _json_bytes, _write


def restore_committed_before_images(
    *, store: LocalStore, run_id: str, expected_journal_sha256: str,
    decision_id: str, input_hash: str, destination: Path,
) -> Path:
    """Verify an external COMMITTED anchor before restoring seven before images.

    The caller must provide the journal SHA from outside the bundle. No source
    state, active pointer or transaction is modified. This is not a replay or
    proof that production consumed the exported files.
    """
    if not isinstance(run_id, str) or len(run_id) != 32 or UUID(hex=run_id).hex != run_id:
        raise ValueError("invalid restore run identity")
    archive = store.archive_dir.resolve()
    data = archive.parent
    journal = checked_path(archive, f".score_run_transactions/runs/{run_id}/manifest.json")
    raw = journal.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_journal_sha256:
        raise ValueError("restore journal digest mismatch")
    record = json.loads(raw)
    if (record.get("schema_version") != SCHEMA_V2 or record.get("status") != "COMMITTED"
            or record.get("run_id") != run_id):
        raise ValueError("restore requires a matching COMMITTED v2 transaction")
    business, evidence = validate_inventory(record)
    binding = record.get("input_binding") or {}
    if binding.get("decision_id") != decision_id or binding.get("input_hash") != input_hash:
        raise ValueError("restore decision binding mismatch")
    validate_input_evidence(record, data)
    prefix = f"archive/decision_inputs/{record['capture_id']}/"
    descriptor = prefix + "pre_state.json"
    if descriptor not in evidence:
        raise ValueError("registered before-image descriptor missing")
    state = json.loads(checked_path(data, descriptor).read_bytes())
    expected_binding = {"run_id": run_id, "capture_id": record["capture_id"],
                        "as_of": record["metadata"]["as_of"]}
    if (set(state) != {"schema_version", "capture_mode", "binding", "artifacts"}
            or state.get("schema_version") != "hermes-score-before-images-v1"
            or state.get("capture_mode") != "V2_PREPARED_BEFORE_IMAGES"
            or state.get("binding") != expected_binding or set(state["artifacts"]) != business):
        raise ValueError("restore before-image descriptor binding mismatch")
    rows = {row["path"]: row for row in record["artifacts"] if row["role"] == "BUSINESS"}
    verified: dict[str, bytes] = {}
    for relative in sorted(business):
        row = rows[relative]
        kind = "SQLITE_BACKUP" if relative.endswith(".sqlite") else "BYTES"
        mode = row.get("before_mode")
        if (row.get("snapshot_format") != kind
                or (row["existed"] and (type(mode) is not int or not 0 <= mode <= 0o777))
                or (not row["existed"] and (mode is not None or row.get("before_sha256") is not None))):
            raise ValueError("restore backup metadata mismatch")
        entry: dict[str, Any] = {"availability": "ABSENT", "path": None, "sha256": None,
                                 "snapshot_format": kind, "before_mode": mode}
        if row["existed"]:
            exported = prefix + "pre_state/" + relative
            entry.update(availability="PRESENT", path=exported, sha256=row.get("before_sha256"))
            if exported not in evidence:
                raise ValueError("unregistered restore before image")
            source = checked_path(data, exported)
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != row.get("before_sha256"):
                raise ValueError("restore before-image digest mismatch")
            if kind == "SQLITE_BACKUP":
                with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True)) as db:
                    sqlite_state_hash(db)
            else:
                _check_state_json(content, "JSONL_BYTES" if relative.endswith(".jsonl") else "JSON_BYTES")
            verified[relative] = content
        if state["artifacts"][relative] != entry:
            raise ValueError("restore before-image metadata mismatch")
    registered = {path for path in evidence if path.startswith(prefix + "pre_state/")}
    if registered != {prefix + "pre_state/" + relative for relative in verified}:
        raise ValueError("restore before-image inventory mismatch")
    destination = _destination(destination, [data, store.history_dir, store.legacy_history_dir])
    stage = Path(tempfile.mkdtemp(prefix=".transaction-restore-", dir=destination.parent))
    try:
        for relative, content in verified.items():
            _write(stage, relative, content)
            (stage / relative).chmod(0o600)
        _write(stage, "source_transaction.json", raw)
        _write(stage, "restoration.json", _json_bytes({
            "schema_version": "hermes-offline-before-state-restore-v1",
            "evidence_role": "OFFLINE_BEFORE_STATE_NOT_FULL_REPLAY",
            "source_journal_sha256": expected_journal_sha256,
            "binding": {**expected_binding, "decision_id": decision_id, "input_hash": input_hash},
            "artifacts": state["artifacts"],
        }))
        os.rename(stage, destination)
        return destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)
