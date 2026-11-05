"""Explicit offline bindings; never invoked by production scoring."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Collection
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..data.decision_identity import scoring_logic_hash, semantic_identity, stable_hash
from ..data.decision_revision import _allocate_revision
from ..data.run_transaction import pending_score_run_transaction
from ..data.store import LocalStore, safe_symbol
from ..data.sqlite_snapshot import copy_sqlite_snapshot as _copy_state_database, sqlite_state_hash as _sqlite_state_hash
from ..safe_io import assert_pipeline_lease

_SCHEMA = "hermes-decision-input-archive-v1"
_ROLE = "OFFLINE_INPUT_BINDING_NOT_FULL_STATE_REPLAY"


def _write(root: Path, relative: str, content: bytes) -> dict[str, str]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o400)
    return {"path": relative, "sha256": hashlib.sha256(content).hexdigest()}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode()


def _store_at(config: dict[str, Any], root: Path) -> LocalStore:
    return LocalStore({**config, "paths": {**config["paths"],
                       "history_dir": str(root / "history"),
                       "legacy_history_dir": str(root / "missing_legacy")}})


def _visible_hash(frame: pd.DataFrame, as_of: str) -> str:
    visible = frame.loc[frame.index <= pd.Timestamp(as_of)]
    return stable_hash(visible.reindex(sorted(visible.columns), axis=1).to_dict(orient="split"))


def _destination(path: Path, protected: list[Path]) -> Path:
    path = Path(path).absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("decision input destination already exists")
    if any(path.resolve().is_relative_to(root.resolve()) for root in protected):
        raise ValueError("decision input destination overlaps a source root")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _verified_bytes(root: Path, entry: dict[str, str], relative: str) -> bytes:
    if entry.get("path") != relative:
        raise ValueError("decision input archive path mismatch")
    path = root / relative
    if any(part.is_symlink() for part in (root, path.parent, path)):
        raise ValueError("decision input archive symlink is not allowed")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != entry.get("sha256"):
        raise ValueError("decision input archive digest mismatch")
    return content


def _check_evidence(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    evidence = payload.get("decision_evidence") or {}
    if (payload.get("run_type") != "scheduled"
            or evidence.get("identity_schema_version") != "hermes-decision-identity-v2"
            or evidence.get("as_of") != payload.get("as_of")
            or stable_hash(payload.get("snapshots")) != payload.get("input_hash")
            or evidence.get("snapshot_hash") != payload.get("input_hash")
            or evidence.get("config_hash") != stable_hash(config)
            or evidence.get("soft_input_evidence_hash") != stable_hash(
                (payload.get("soft_data") or {}).get("records") or {})):
        raise ValueError("decision input archive requires matching v2 certification")
    _allocate_revision(
        as_of=evidence["as_of"], decision_hash=evidence["semantic_hash"],
        finality=evidence["bar_finality"], previous={"payload": payload},
    )
    return evidence


def archive_decision_inputs(
    payload: dict[str, Any], config: dict[str, Any], *, store: LocalStore,
    package_root: Path, destination: Path,
) -> dict[str, str]:
    """Bind a certified payload to matching full files in a new offline bundle.

    This is retrospective verification, not a hook into the score transaction.
    Current files must still prove every as-of history hash or capture fails.
    """
    evidence = _check_evidence(payload, config)
    destination = _destination(destination, [store.history_dir, store.legacy_history_dir, package_root])
    stage = Path(tempfile.mkdtemp(prefix=".decision-inputs-", dir=destination.parent))
    try:
        entries = {}
        source_locations = {}
        names = set()
        for symbol in evidence["semantic_identity"]["history_hashes"]:
            filename = f"{safe_symbol(symbol)}.csv"
            if filename in names or Path(filename).name != filename:
                raise ValueError("decision history filename is ambiguous")
            names.add(filename)
            source = store.history_path(symbol)
            location = "primary"
            if not source.exists():
                source = store.history_path(symbol, legacy=True)
                location = "legacy"
            entries[symbol] = (_write(stage, f"history/{filename}", source.read_bytes())
                               if source.exists() else {"path": None, "sha256": None})
            source_locations[symbol] = {"path": str(source),
                                        "availability": location if source.exists() else "missing"}
        frozen = _store_at(config, stage)
        histories: dict[str, pd.DataFrame | None] = {}
        for symbol, entry in entries.items():
            if entry["path"] is None:
                if evidence["semantic_identity"]["history_hashes"][symbol] is not None:
                    raise ValueError("current files cannot prove certified decision inputs")
                histories[symbol] = None
            else:
                histories[symbol] = frozen.load_history(symbol)
        identity = semantic_identity(payload, config, histories, package_root)
        if identity != evidence["semantic_identity"]:
            raise ValueError("current files cannot prove certified decision inputs")
        manifest = {
            "schema_version": _SCHEMA, "evidence_role": _ROLE,
            "capture_mode": "RETROSPECTIVE_AS_OF_MATCH",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "decision_id": evidence["decision_id"], "as_of": evidence["as_of"],
            "semantic_hash": evidence["semantic_hash"], "histories": entries,
            "source_locations_at_capture": source_locations,
            "source_roots_at_capture": [str(store.history_dir.resolve()),
                                        str(store.legacy_history_dir.resolve())],
            "payload": _write(stage, "payload.json", _json_bytes(payload)),
            "config": _write(stage, "config.json", _json_bytes(config)),
            "code_fingerprint": identity["scoring_logic_hash"],
        }
        index = _write(stage, "manifest.json", _json_bytes(manifest))
        os.rename(stage, destination)
        return {"manifest_path": str(destination / "manifest.json"),
                "manifest_sha256": index["sha256"], "decision_id": evidence["decision_id"]}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def restore_decision_inputs(
    manifest_path: Path, *, expected_manifest_sha256: str, decision_id: str,
    destination: Path, package_root: Path,
) -> Path:
    """Restore only authenticated bundle bytes; no scoring or state writes.

    The caller supplies the external manifest digest, not a digest taken from
    the bundle itself. Raw config is evidence, not a runnable replay config.
    """
    manifest_path = Path(manifest_path).absolute()
    if manifest_path.is_symlink():
        raise ValueError("decision input archive symlink is not allowed")
    raw_manifest = manifest_path.read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest() != expected_manifest_sha256:
        raise ValueError("decision input manifest digest mismatch")
    manifest = json.loads(raw_manifest)
    if (manifest.get("schema_version") != _SCHEMA or manifest.get("evidence_role") != _ROLE
            or manifest.get("capture_mode") != "RETROSPECTIVE_AS_OF_MATCH"
            or manifest.get("decision_id") != decision_id):
        raise ValueError("decision input manifest binding mismatch")
    root = manifest_path.parent
    raw_payload = _verified_bytes(root, manifest["payload"], "payload.json")
    raw_config = _verified_bytes(root, manifest["config"], "config.json")
    payload, config = json.loads(raw_payload), json.loads(raw_config)
    evidence = _check_evidence(payload, config)
    if (evidence["decision_id"] != decision_id or evidence["as_of"] != manifest.get("as_of")
            or evidence["semantic_hash"] != manifest.get("semantic_hash")
            or evidence["semantic_identity"]["scoring_logic_hash"] != manifest.get("code_fingerprint")
            or scoring_logic_hash(package_root) != manifest.get("code_fingerprint")
            or set(manifest["histories"]) != set(evidence["semantic_identity"]["history_hashes"])):
        raise ValueError("decision input manifest binding mismatch")
    original = LocalStore(config)
    captured_roots = manifest.get("source_roots_at_capture")
    if (not isinstance(captured_roots, list) or len(captured_roots) != 2
            or any(not isinstance(item, str) or not Path(item).is_absolute() for item in captured_roots)):
        raise ValueError("decision input source roots are missing")
    destination = _destination(destination, [original.history_dir, original.legacy_history_dir,
                                             package_root, root, *map(Path, captured_roots)])
    stage = Path(tempfile.mkdtemp(prefix=".decision-inputs-", dir=destination.parent))
    try:
        for symbol, entry in manifest["histories"].items():
            relative = f"history/{safe_symbol(symbol)}.csv"
            if Path(relative).parent != Path("history"):
                raise ValueError("decision input archive path mismatch")
            if entry == {"path": None, "sha256": None}:
                continue
            _write(stage, relative, _verified_bytes(root, entry, relative))
        frozen = _store_at(config, stage)
        for symbol, expected in evidence["semantic_identity"]["history_hashes"].items():
            if manifest["histories"][symbol] == {"path": None, "sha256": None} and expected is None:
                continue
            if _visible_hash(frozen.load_history(symbol), evidence["as_of"]) != expected:
                raise ValueError("restored as-of history projection mismatch")
        _write(stage, "payload.json", raw_payload)
        _write(stage, "config.evidence.json", raw_config)
        _write(stage, "original_manifest.json", raw_manifest)
        os.rename(stage, destination)
        return destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)


_PRE_STATE_SCHEMA = "hermes-pre-run-state-archive-v1"
_PRE_STATE_ROLE = "OFFLINE_PRE_STATE_NOT_DECISION_BOUND"


def _state_formats(as_of: str) -> dict[str, str]:
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("pre-state requires an exact ISO decision date")
    return {
        **{name: "SQLITE_BACKUP" for name in (
            "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
        )},
        "audit_log.jsonl": "JSONL_BYTES", "signal_journal.jsonl": "JSONL_BYTES",
        f"soft_adapter_snapshot_{as_of}.json": "JSON_BYTES",
    }


def _check_state_json(content: bytes, kind: str) -> None:
    records = [line for line in content.splitlines() if line.strip()] if kind == "JSONL_BYTES" else [content]
    if any(not isinstance(json.loads(row), dict) for row in records):
        raise ValueError("pre-state JSON records must be objects")


def _absent_state_entry(kind: str) -> dict[str, Any]:
    return {"path": None, "sha256": None, "logical_sha256": None,
            "format": kind, "availability": "ABSENT"}


def capture_pre_run_state(
    as_of: str, *, store: LocalStore, destination: Path, _lease: Any,
    required_artifacts: Collection[str] = (),
) -> dict[str, str]:
    """Explicitly freeze seven state files, not a claim about a scored decision.

    The caller must acquire the matching lease and recover any pending score run
    first. SQLite backup includes committed WAL rows; sources are not repaired.
    Expected prior files must be declared in required_artifacts; ABSENT alone
    does not prove first installation or a valid certification chain.
    """
    archive = store.archive_dir.resolve()
    assert_pipeline_lease(_lease, path=archive / ".pipeline.lock")
    if pending_score_run_transaction(archive) is not None:
        raise ValueError("pre-state capture requires recovery of the pending score run")
    formats = _state_formats(as_of)
    required = set(required_artifacts)
    if not required.issubset(formats):
        raise ValueError("unknown required pre-state artifact")
    roots = {"data": str(archive.parent), "archive": str(archive),
             "history": str(store.history_dir.resolve()), "legacy": str(store.legacy_history_dir.resolve())}
    destination = _destination(destination, [Path(root) for root in roots.values()])
    stage = Path(tempfile.mkdtemp(prefix=".pre-run-state-", dir=destination.parent))
    try:
        artifacts = {}
        for name, kind in formats.items():
            source = archive / name
            sidecars = [archive / f"{name}{suffix}" for suffix in ("-wal", "-shm", "-journal")]
            if source.is_symlink() or (kind == "SQLITE_BACKUP" and any(path.is_symlink() for path in sidecars)):
                raise ValueError(f"pre-state source symlink is not allowed: {name}")
            if not source.exists():
                if kind == "SQLITE_BACKUP" and any(path.exists() for path in sidecars):
                    raise ValueError(f"pre-state orphan SQLite sidecar: {name}")
                if name in required:
                    raise ValueError(f"required pre-state artifact missing: {name}")
                artifacts[name] = _absent_state_entry(kind)
                continue
            if not source.is_file():
                raise ValueError(f"pre-state source is not a regular file: {name}")
            relative = f"archive/{name}"
            entry: dict[str, Any]
            if kind == "SQLITE_BACKUP":
                entry = {"path": relative, **_copy_state_database(source, stage / relative)}
            else:
                content = source.read_bytes()
                _check_state_json(content, kind)
                entry = {**_write(stage, relative, content), "logical_sha256": None}
            artifacts[name] = {**entry, "format": kind, "availability": "PRESENT"}
        capture_id = uuid.uuid4().hex
        manifest = {"schema_version": _PRE_STATE_SCHEMA, "evidence_role": _PRE_STATE_ROLE,
                    "capture_id": capture_id, "as_of": as_of,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "source_roots_at_capture": roots, "required_artifacts": sorted(required),
                    "artifacts": artifacts}
        index = _write(stage, "manifest.json", _json_bytes(manifest))
        os.rename(stage, destination)
        return {"manifest_path": str(destination / "manifest.json"),
                "manifest_sha256": index["sha256"], "capture_id": capture_id}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def restore_pre_run_state(
    manifest_path: Path, *, expected_manifest_sha256: str, capture_id: str,
    as_of: str, store: LocalStore, destination: Path,
) -> Path:
    """Restore an externally bound pre-state to a new, writable offline root.

    It neither restores into canonical roots nor establishes a decision binding.
    The seven-file inventory is exact; SQLite reads use only frozen main bytes.
    """
    manifest_path = Path(manifest_path).absolute()
    if manifest_path.is_symlink() or manifest_path.parent.is_symlink():
        raise ValueError("pre-state manifest symlink is not allowed")
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("pre-state manifest digest mismatch")
    manifest = json.loads(raw)
    formats = _state_formats(as_of)
    if not isinstance(capture_id, str) or len(capture_id) != 32 or uuid.UUID(hex=capture_id).hex != capture_id:
        raise ValueError("pre-state capture identity is invalid")
    if (manifest.get("schema_version") != _PRE_STATE_SCHEMA
            or manifest.get("evidence_role") != _PRE_STATE_ROLE
            or manifest.get("capture_id") != capture_id or manifest.get("as_of") != as_of
            or set(manifest["artifacts"]) != set(formats)):
        raise ValueError("pre-state manifest binding mismatch")
    required = manifest.get("required_artifacts")
    if (not isinstance(required, list) or any(not isinstance(name, str) or name not in formats for name in required)
            or required != sorted(set(required))):
        raise ValueError("pre-state required artifact inventory mismatch")
    roots = manifest.get("source_roots_at_capture")
    if (not isinstance(roots, dict) or set(roots) != {"data", "archive", "history", "legacy"}
            or any(not isinstance(value, str) or not Path(value).is_absolute() for value in roots.values())):
        raise ValueError("pre-state source roots are missing")
    root = manifest_path.parent
    current_roots = [store.archive_dir.parent, store.archive_dir, store.history_dir, store.legacy_history_dir]
    destination = _destination(destination, [root, *current_roots, *map(Path, roots.values())])
    stage = Path(tempfile.mkdtemp(prefix=".pre-run-state-", dir=destination.parent))
    try:
        for name, kind in formats.items():
            entry = manifest["artifacts"][name]
            relative = f"archive/{name}"
            if entry == _absent_state_entry(kind):
                if name in required:
                    raise ValueError(f"required pre-state artifact missing: {name}")
                continue
            if entry.get("availability") != "PRESENT" or entry.get("format") != kind:
                raise ValueError("pre-state artifact binding mismatch")
            content = _verified_bytes(root, entry, relative)
            if kind == "SQLITE_BACKUP":
                source = root / relative
                with closing(sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
                    if _sqlite_state_hash(connection) != entry.get("logical_sha256"):
                        raise ValueError("pre-state SQLite logical digest mismatch")
            else:
                _check_state_json(content, kind)
                if entry.get("logical_sha256") is not None:
                    raise ValueError("pre-state artifact binding mismatch")
            _write(stage, relative, content)
            (stage / relative).chmod(0o600)
        _write(stage, "original_manifest.json", raw)
        os.rename(stage, destination)
        return destination
    finally:
        if stage.exists():
            shutil.rmtree(stage)
