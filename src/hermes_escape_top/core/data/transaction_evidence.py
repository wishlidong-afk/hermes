"""Strict, standard-library-only inventory for score transaction v2."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from uuid import UUID

SCHEMA_V2 = "hermes-score-run-transaction-v2"


def business_paths(as_of: str) -> set[str]:
    if date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError("transaction requires an exact ISO decision date")
    return {f"archive/{name}" for name in (
        "hermes_state.sqlite", "reentry_state.sqlite", "mirror_reference.sqlite", "flow_reference.sqlite",
        "audit_log.jsonl", "signal_journal.jsonl", f"soft_adapter_snapshot_{as_of}.json",
    )}


def validate_inventory(record: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    if record.get("schema_version") != SCHEMA_V2:
        raise ValueError("unsupported transaction evidence schema")
    if record.get("status") not in {"PREPARING", "PREPARED", "PENDING", "COMMITTED", "ROLLED_BACK", "RECOVERED_ROLLBACK"}:
        raise ValueError("unknown transaction status")
    capture_id = record.get("capture_id")
    if not isinstance(capture_id, str) or len(capture_id) != 32 or UUID(hex=capture_id).hex != capture_id:
        raise ValueError("invalid transaction capture_id")
    metadata = record["metadata"]
    if metadata.get("run_type") != "scheduled" or metadata.get("shadow") is not False:
        raise ValueError("v2 evidence requires non-shadow scheduled metadata")
    expected = business_paths(metadata["as_of"])
    prefix = f"archive/decision_inputs/{capture_id}/"
    business: set[str] = set()
    evidence: set[str] = set()
    rows = record["artifacts"]
    if not isinstance(rows, list):
        raise ValueError("transaction artifact inventory is not a list")
    for row in rows:
        path = row["path"]
        if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                or ".." in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path
                or path in business | evidence or not isinstance(row.get("existed"), bool)):
            raise ValueError("invalid or duplicate transaction artifact")
        if row.get("role") == "BUSINESS":
            business.add(path)
        elif row.get("role") == "DECISION_INPUT_EVIDENCE" and path.startswith(prefix):
            if row["existed"]:
                raise ValueError("new capture evidence must not overwrite an existing file")
            evidence.add(path)
        else:
            raise ValueError("unknown transaction artifact role or evidence path")
    if business != expected:
        raise ValueError("business artifacts mismatch")
    if len(evidence) < 2 or prefix + "manifest.json" not in evidence:
        raise ValueError("transaction evidence manifest or files missing")
    return business, evidence


def checked_path(data_root: Path, relative: str) -> Path:
    root = Path(data_root).resolve()
    current = root
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or ".." in parts:
        raise ValueError("invalid transaction evidence path")
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("transaction evidence symlink is not allowed")
    return current


def validate_input_evidence(record: Mapping[str, Any], data_root: Path) -> None:
    business, evidence = validate_inventory(record)
    binding = record.get("input_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("transaction input binding missing")
    manifest_path = f"archive/decision_inputs/{record['capture_id']}/manifest.json"
    if binding.get("manifest_path") != manifest_path:
        raise ValueError("transaction input manifest path mismatch")
    expected = {"run_id": record["run_id"], "capture_id": record["capture_id"],
                "as_of": record["metadata"]["as_of"], "decision_id": binding.get("decision_id"),
                "input_hash": binding.get("input_hash")}
    if (not isinstance(expected["decision_id"], str) or not expected["decision_id"]
            or not _is_digest(expected["input_hash"]) or not _is_digest(binding.get("manifest_sha256"))):
        raise ValueError("transaction input identity or digest missing")
    raw_manifest = checked_path(data_root, manifest_path).read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest() != binding["manifest_sha256"]:
        raise ValueError("transaction input manifest digest mismatch")
    manifest = json.loads(raw_manifest)
    if (manifest.get("schema_version") != "hermes-in-run-input-binding-v1"
            or manifest.get("capture_mode") != "IN_RUN_CAPTURE" or manifest.get("binding") != expected):
        raise ValueError("transaction input manifest binding mismatch")
    files = manifest["files"]
    if not isinstance(files, list):
        raise ValueError("transaction input file inventory is not a list")
    listed = {item["path"]: item["sha256"] for item in files}
    if len(listed) != len(files) or set(listed) != evidence - {manifest_path}:
        raise ValueError("transaction input file inventory mismatch")
    for row in record["artifacts"]:
        path = checked_path(data_root, row["path"])
        if not path.is_file():
            raise ValueError("transaction output file missing")
        if row["path"] in business:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_digest = binding["manifest_sha256"] if row["path"] == manifest_path else listed[row["path"]]
        if not _is_digest(expected_digest) or digest != expected_digest or digest != row.get("after_sha256"):
            raise ValueError("transaction evidence file digest mismatch")
    bundle = checked_path(data_root, f"archive/decision_inputs/{record['capture_id']}")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ValueError("transaction evidence symlink is not allowed")
        if path.is_file():
            actual.add(path.relative_to(Path(data_root).resolve()).as_posix())
    if actual != evidence:
        raise ValueError("unregistered transaction evidence file")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
